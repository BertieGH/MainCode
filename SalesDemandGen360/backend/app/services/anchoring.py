"""Whether an account is still anchored, and what happens when it is not.

A list is a workspace — a way of organising accounts to build campaigns from —
not what decides whether an account's data lives. An account is **anchored**
while it is on at least one account list or in at least one campaign queue.
Campaigns guard themselves further down: a campaign that reached La Growth
Machine cannot be deleted, and a queue that fed a campaign is locked.

When something removes an anchor — a list deleted, accounts removed from a
list, a queue member removed, a draft queue deleted — the accounts it touched
are assessed:

* **Still anchored** — on another list, or in a queue — nothing changes.
* **Unanchored with work behind it** goes **dormant**: hidden from the screens,
  nothing deleted. Its evidence (never deleted, invariant 2), signals, scores,
  contacts and company check are kept for the day a new list brings it back.
* **Unanchored with nothing behind it** — a company imported and never worked
  on — is deleted, but only when a whole list is deleted. That is how a bad
  import is undone; removing a few rows from a list is curation, and keeps them.

`revive` is the way back: joining a list clears `dormant_at`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountListMember, Contact, ContactSuggestion, Run
from app.models.campaign import CampaignQueueContact, CampaignQueueMember, DeferredEnrolment
from app.models.context import AccountContext, Qualification
from app.models.signal import Evidence, Signal
from app.models.strategy import PersonaServiceScore, StrategyThread


@dataclass
class Assessment:
    #: Still on another list.
    on_lists: set[uuid.UUID] = field(default_factory=set)
    #: On no other list, but kept live by a campaign queue.
    in_queues: set[uuid.UUID] = field(default_factory=set)
    dormant: set[uuid.UUID] = field(default_factory=set)
    deleted: set[uuid.UUID] = field(default_factory=set)

    def counts(self) -> dict[str, int]:
        return {
            "on_other_lists": len(self.on_lists),
            "in_queues": len(self.in_queues),
            "dormant": len(self.dormant),
            "deleted": len(self.deleted),
        }


async def _ids(session: AsyncSession, stmt) -> set[uuid.UUID]:
    return {r for r in (await session.execute(stmt)).scalars() if r is not None}


async def worked_on(session: AsyncSession, account_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    """Accounts with anything behind them worth keeping.

    Research, signals, context, a score, a run, a company check; contacts a
    provider found, verified or reached through strategy or enrolment;
    suggestions a rep decided on. Contacts a CSV named, and nothing more, are
    not work — they came from the file and come back with it.
    """
    ids = set(account_ids)
    if not ids:
        return set()
    probes = (
        select(Account.id).where(
            Account.id.in_(ids),
            or_(
                Account.dormant_at.is_not(None),
                Account.company_check.is_not(None),
                Account.icp_match_score.is_not(None),
                Account.research_status != "not_started",
                Account.enrichment_status != "not_started",
            ),
        ),
        select(Evidence.account_id).where(Evidence.account_id.in_(ids)),
        select(Signal.account_id).where(Signal.account_id.in_(ids)),
        select(Qualification.account_id).where(Qualification.account_id.in_(ids)),
        select(AccountContext.account_id).where(AccountContext.account_id.in_(ids)),
        select(Run.account_id).where(Run.account_id.in_(ids)),
        select(Contact.account_id).where(
            Contact.account_id.in_(ids),
            or_(
                Contact.email_status == "verified",
                Contact.email_provider.in_(("apollo", "contactout")),
                Contact.apollo_person_id.is_not(None),
            ),
        ),
        select(ContactSuggestion.account_id).where(
            ContactSuggestion.account_id.in_(ids),
            ContactSuggestion.status.in_(("rejected", "revealed", "not_found")),
        ),
        # Referenced without a cascade: deleting these would fail on a foreign
        # key, and a person somebody planned outreach to is work.
        select(Contact.account_id)
        .join(StrategyThread, StrategyThread.contact_id == Contact.id)
        .where(Contact.account_id.in_(ids)),
        select(Contact.account_id)
        .join(PersonaServiceScore, PersonaServiceScore.contact_id == Contact.id)
        .where(Contact.account_id.in_(ids)),
        select(Contact.account_id)
        .join(DeferredEnrolment, DeferredEnrolment.contact_id == Contact.id)
        .where(Contact.account_id.in_(ids)),
    )
    found: set[uuid.UUID] = set()
    for probe in probes:
        found |= await _ids(session, probe.distinct())
        if found >= ids:
            break
    return found & ids


async def assess(
    session: AsyncSession,
    account_ids,
    *,
    ignoring_list: uuid.UUID | None = None,
    ignoring_queue: uuid.UUID | None = None,
    delete_empty: bool = False,
) -> Assessment:
    """What losing an anchor would do to these accounts. Writes nothing.

    `ignoring_list` / `ignoring_queue` assess as though that list or queue were
    already gone — so the same call previews a delete and performs it.
    """
    ids = set(account_ids)
    result = Assessment()
    if not ids:
        return result

    on_lists = select(AccountListMember.account_id).where(AccountListMember.account_id.in_(ids))
    if ignoring_list is not None:
        on_lists = on_lists.where(AccountListMember.list_id != ignoring_list)
    result.on_lists = await _ids(session, on_lists.distinct())

    rest = ids - result.on_lists
    if rest:
        in_queues = select(CampaignQueueMember.account_id).where(
            CampaignQueueMember.account_id.in_(rest)
        )
        people = select(CampaignQueueContact.account_id).where(
            CampaignQueueContact.account_id.in_(rest)
        )
        if ignoring_queue is not None:
            in_queues = in_queues.where(CampaignQueueMember.queue_id != ignoring_queue)
            people = people.where(CampaignQueueContact.queue_id != ignoring_queue)
        # A person chosen for a queue keeps their company live as well.
        result.in_queues = await _ids(session, in_queues.distinct()) | await _ids(
            session, people.distinct()
        )

    loose = ids - result.on_lists - result.in_queues
    if delete_empty:
        worked = await worked_on(session, loose)
        result.dormant = loose & worked
        result.deleted = loose - worked
    else:
        result.dormant = loose
    return result


async def apply(
    session: AsyncSession, assessment: Assessment, *, reason: str, now: datetime | None = None
) -> None:
    """Make dormant and delete what the assessment says. Call after the anchor is gone."""
    now = now or datetime.now(UTC)
    if assessment.dormant:
        await session.execute(
            update(Account)
            .where(Account.id.in_(assessment.dormant), Account.dormant_at.is_(None))
            .values(dormant_at=now, dormant_reason=reason)
            .execution_options(synchronize_session=False)
        )
    if assessment.deleted:
        await session.execute(
            delete(Account)
            .where(Account.id.in_(assessment.deleted))
            .execution_options(synchronize_session=False)
        )


async def release(
    session: AsyncSession, account_ids, *, reason: str, delete_empty: bool = False
) -> Assessment:
    """Assess and apply in one step, for callers that have already removed the anchor."""
    assessment = await assess(session, account_ids, delete_empty=delete_empty)
    await apply(session, assessment, reason=reason)
    return assessment


async def revive(session: AsyncSession, account_ids) -> set[uuid.UUID]:
    """Bring dormant accounts back. Returns the ones that were dormant."""
    ids = set(account_ids)
    if not ids:
        return set()
    dormant = await _ids(
        session, select(Account.id).where(Account.id.in_(ids), Account.dormant_at.is_not(None))
    )
    if dormant:
        await session.execute(
            update(Account)
            .where(Account.id.in_(dormant))
            .values(dormant_at=None, dormant_reason=None)
            .execution_options(synchronize_session=False)
        )
    return dormant
