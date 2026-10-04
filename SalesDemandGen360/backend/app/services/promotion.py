"""Promoting a queue into a campaign.

Promotion is the point of no return for a queue: it locks, permanently. To make
a variant you clone it into a new draft. Re-opening a locked queue would make
"which version of the queue did campaign 2 use?" unanswerable, and that question
is asked precisely when something has gone wrong.

The contact lock is **not** enforced here. It is enforced by a partial unique
index on `outreach_sequence`, and this module deliberately relies on the
database raising rather than checking first. An application-level check passes a
sequential test and loses a race in production: two promotions can both read
"no live sequence", both decide to proceed, and both insert.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Contact
from app.models.campaign import (
    SEQUENCE_NON_TERMINAL,
    CadenceShape,
    CampaignQueue,
    CampaignQueueContact,
    CampaignQueueMember,
    DeferredEnrolment,
    OutreachCampaign,
    OutreachCampaignSource,
    OutreachSequence,
)
from app.models.strategy import StrategyThread

log = logging.getLogger(__name__)


class QueueLockedError(RuntimeError):
    """The queue has already been promoted. Clone it instead."""


class ContactAlreadyEnrolledError(RuntimeError):
    """Raised when the partial unique index rejects a second live sequence."""


@dataclass
class PromotionResult:
    campaign_id: uuid.UUID
    enrolled: list[uuid.UUID] = field(default_factory=list)
    deferred: list[uuid.UUID] = field(default_factory=list)
    blocked: dict[str, str] = field(default_factory=dict)


#: A person can be taken out while the campaign is still being prepared.
#: Once enrolled, the lever is `stop`: LGM already holds the lead.
WITHDRAWABLE = ("draft", "pending_eval", "pending_approval", "approved")


class NotWithdrawableError(RuntimeError):
    """This person cannot be taken out of the campaign, with the reason."""


async def withdraw(session: AsyncSession, sequence, *, reason: str) -> None:
    """Take one person out of a campaign, before anything is sent.

    Not a delete. The sequence stays as `cancelled` with the reason, its drafts
    stay attached to it, and the strategy stays where it is — a campaign that
    quietly loses somebody is how the same person is approached twice by two
    campaigns. What ends is their part in *this* one; `cancelled` is outside the
    enrolment lock, so they can be queued into another immediately.
    """
    if not (reason or "").strip():
        raise NotWithdrawableError("a withdrawal needs a reason")
    if sequence.status not in WITHDRAWABLE:
        raise NotWithdrawableError(
            f"this sequence is {sequence.status} — stop it instead; once enrolled, La Growth "
            "Machine already holds the lead"
        )
    sequence.status = "cancelled"
    sequence.withdraw_reason = reason.strip()
    sequence.withdrawn_at = datetime.now(UTC)
    await session.flush()


async def reinstate(session: AsyncSession, sequence) -> None:
    """Put a withdrawn person back, to be drafted and approved again.

    Their drafts are still there; approval is not, and is not inherited — the
    words have to be read again before anything can send.
    """
    if sequence.status != "cancelled":
        raise NotWithdrawableError("this person was not withdrawn")
    sequence.status = "draft"
    sequence.withdraw_reason = None
    sequence.withdrawn_at = None
    await session.flush()


class MixedTargetsError(RuntimeError):
    """Queues built for different services or ICPs cannot feed one campaign."""


async def clone_queue(
    session: AsyncSession, queue_id: uuid.UUID, *, label: str
) -> CampaignQueue:
    """The only way to get an editable copy of a promoted queue."""
    source = await session.get(CampaignQueue, queue_id)
    if source is None:
        raise ValueError(f"queue {queue_id} not found")

    clone = CampaignQueue(
        label=label,
        description=source.description,
        status="draft",
        cloned_from_queue_id=source.id,
        service_id=source.service_id,
        icp_profile_id=source.icp_profile_id,
        icp_version=source.icp_version,
    )
    session.add(clone)
    await session.flush()

    members = (
        await session.execute(
            select(CampaignQueueMember).where(CampaignQueueMember.queue_id == queue_id)
        )
    ).scalars()
    for m in members:
        session.add(
            CampaignQueueMember(
                queue_id=clone.id,
                account_id=m.account_id,
                # Provenance travels with the copy; it is a stamp, not a link.
                source_list_id=m.source_list_id,
                qualification_id=m.qualification_id,
                added_by=m.added_by,
            )
        )
    people = (
        await session.execute(
            select(CampaignQueueContact).where(CampaignQueueContact.queue_id == queue_id)
        )
    ).scalars()
    for p in people:
        session.add(
            CampaignQueueContact(
                queue_id=clone.id,
                contact_id=p.contact_id,
                account_id=p.account_id,
                source_list_id=p.source_list_id,
                added_by=p.added_by,
            )
        )
    await session.flush()
    return clone


class NotEligibleError(RuntimeError):
    """This account may not join a queue, with the reason.

    Deliberately not a `ValueError`: the routes map `ValueError` to 404, and an
    ineligible account exists — it is in the wrong state, which is a 409.
    """


def queue_ineligibility(
    account, *, band: str | None = None, min_band: str = "low"
) -> str | None:
    """Why this account cannot join a queue, or `None` if it can.

    The same rule the account table shows (`ACCOUNT_ACTIONS.queue` in the web
    app), held here so the server refuses for the reasons the screen gives.
    Until this existed the rule was the screen's alone, and any other caller —
    a script, a second client, a hand-built request — could queue an account
    nobody had confirmed.

    * **Identity must be confirmed.** A queue feeds campaigns; an unconfirmed
      account is a company nobody has verified, and research and drafting
      downstream would be about whoever the spreadsheet row happened to match.
    * **Disqualified accounts stay out.** Qualification said no; a queue is
      where that decision would otherwise be quietly reversed.
    * **The band gate**, when one is set. `min_band` of `low` is no
      restriction; above it, `band` must reach it — and an account with no
      qualification at all cannot, because nobody has judged it.
    """
    if account.resolution_status != "resolved":
        return f"identity not confirmed ({account.resolution_status})"
    if account.status == "disqualified":
        return "account is disqualified"
    if min_band != "low":
        if band is None:
            return (
                f"not qualified yet — the queue takes {min_band} and above, "
                "so this account needs qualifying first"
            )
        if BAND_ORDER[band] < BAND_ORDER[min_band]:
            return f"priority band {band}, below the queue's minimum of {min_band}"
    return None


def reachable(contact) -> bool:
    """A verified email or a LinkedIn profile — something outreach can use."""
    return bool(
        (contact.email and contact.email_status == "verified") or contact.linkedin_url
    )


def contact_ineligibility(
    account, contact, *, band: str | None = None, min_band: str = "low"
) -> str | None:
    """Why this person cannot join a queue, or `None` if they can.

    Their company must pass the queue rule, and they must be reachable.
    """
    reason = queue_ineligibility(account, band=band, min_band=min_band)
    if reason is not None:
        return reason
    if contact.do_not_contact:
        return f"marked do not contact — {contact.do_not_contact_reason}"
    if not reachable(contact):
        return "no verified email or LinkedIn profile"
    return None


#: Weakest to strongest, for comparing a band against the gate.
BAND_ORDER = {"low": 0, "medium": 1, "high": 2}


async def queue_gate(session: AsyncSession) -> str:
    """The minimum band in force. `low` when nothing is configured."""
    from app.models.config import ScoringConfig

    row = (
        await session.execute(
            select(ScoringConfig).where(ScoringConfig.is_active.is_(True))
        )
    ).scalar_one_or_none()
    return getattr(row, "min_queue_band", "low") or "low"


async def latest_band(session: AsyncSession, account_id, icp_profile_id=None) -> str | None:
    """The band of this account's most recent qualification, if it has one.

    Read for the queue's ICP when it has one: the company is qualified once,
    and fit and buyer are recomputed for each ICP (`icp_scores`).
    """
    from app.models.context import Qualification
    from app.services import icp_scores

    if icp_profile_id is not None:
        score = await icp_scores.score_for(session, account_id, icp_profile_id)
        if score is not None:
            return score.priority_band
    return (
        await session.execute(
            select(Qualification.priority_band)
            .where(Qualification.account_id == account_id)
            .order_by(Qualification.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def add_member(
    session: AsyncSession,
    *,
    queue_id: uuid.UUID,
    account_id: uuid.UUID,
    source_list_id: uuid.UUID | None = None,
    qualification_id: uuid.UUID | None = None,
    added_by: str | None = None,
) -> CampaignQueueMember | None:
    """Copy an account in. Refused once the queue is locked, or if the account
    is not eligible — see `queue_ineligibility`."""
    from app.models.account import Account

    queue = await session.get(CampaignQueue, queue_id)
    if queue is None:
        raise ValueError(f"queue {queue_id} not found")
    if queue.status == "locked":
        raise QueueLockedError(
            f"queue {queue.label!r} was locked at {queue.locked_at}; "
            "clone it to make a variant rather than re-opening it"
        )

    # Looked up rather than left to the foreign key. A missing account used to
    # reach the INSERT and fail there, aborting the caller's whole transaction.
    account = await session.get(Account, account_id)
    if account is None:
        raise ValueError("account no longer exists")
    min_band = await queue_gate(session)
    reason = queue_ineligibility(
        account,
        band=await latest_band(session, account_id, queue.icp_profile_id) if min_band != "low" else None,
        min_band=min_band,
    )
    if reason is not None:
        raise NotEligibleError(reason)

    existing = (
        await session.execute(
            select(CampaignQueueMember).where(
                CampaignQueueMember.queue_id == queue_id,
                CampaignQueueMember.account_id == account_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        # A queue built from overlapping lists must not double-count.
        return None

    row = CampaignQueueMember(
        queue_id=queue_id,
        account_id=account_id,
        source_list_id=source_list_id,
        qualification_id=qualification_id,
        added_by=added_by,
    )
    session.add(row)
    await session.flush()
    return row


async def add_contact(
    session: AsyncSession,
    *,
    queue_id: uuid.UUID,
    contact_id: uuid.UUID,
    source_list_id: uuid.UUID | None = None,
    added_by: str | None = None,
) -> CampaignQueueContact | None:
    """Choose a person for a queue. `None` when they are already in it."""
    from app.models.account import Account

    queue = await session.get(CampaignQueue, queue_id)
    if queue is None:
        raise ValueError(f"queue {queue_id} not found")
    if queue.status == "locked":
        raise QueueLockedError(
            f"queue {queue.label!r} was locked at {queue.locked_at}; "
            "clone it to make a variant rather than re-opening it"
        )
    contact = await session.get(Contact, contact_id)
    if contact is None:
        raise ValueError("contact no longer exists")
    account = await session.get(Account, contact.account_id)
    if account is None:
        raise ValueError("contact no longer exists")
    min_band = await queue_gate(session)
    reason = contact_ineligibility(
        account,
        contact,
        band=await latest_band(session, account.id, queue.icp_profile_id) if min_band != "low" else None,
        min_band=min_band,
    )
    if reason is not None:
        raise NotEligibleError(f"{reason} — {contact.full_name}")

    existing = (
        await session.execute(
            select(CampaignQueueContact).where(
                CampaignQueueContact.queue_id == queue_id,
                CampaignQueueContact.contact_id == contact_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return None
    row = CampaignQueueContact(
        queue_id=queue_id,
        contact_id=contact_id,
        account_id=account.id,
        source_list_id=source_list_id,
        added_by=added_by,
    )
    session.add(row)
    await session.flush()
    return row


async def pursued_thread_for(
    session: AsyncSession, contact, *, campaign_id: uuid.UUID | None = None
) -> StrategyThread | None:
    """The strategy being pursued for this person.

    The campaign's own strategy when it has one for their company — it argues
    for the campaign's service and ICP, and a person it leaves out has none.
    Otherwise their company's latest company-wide strategy, from before
    strategies belonged to campaigns.
    """
    from app.models.strategy import Strategy

    scopes = [Strategy.campaign_id.is_(None)]
    if campaign_id is not None:
        scopes.insert(0, (Strategy.campaign_id == campaign_id) & (Strategy.status != "superseded"))
    strategy = None
    for scope in scopes:
        strategy = (
            await session.execute(
                select(Strategy)
                .where(Strategy.account_id == contact.account_id, scope)
                .order_by(Strategy.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if strategy is not None:
            break
    if strategy is None:
        return None
    return (
        await session.execute(
            select(StrategyThread)
            .where(
                StrategyThread.strategy_id == strategy.id,
                StrategyThread.contact_id == contact.id,
                StrategyThread.thread_status.in_(PURSUED),
            )
            .order_by(StrategyThread.rank)
            .limit(1)
        )
    ).scalar_one_or_none()


async def person_of(session: AsyncSession, sequence) -> tuple:
    """The person a sequence is for, and their strategy thread if one exists.

    A sequence promoted from a chosen person has no thread until a strategy is
    built; once one is being pursued for them it is linked here, so every later
    reader — approval, pre-flight, execution — sees it.
    """
    thread = (
        await session.get(StrategyThread, sequence.thread_id) if sequence.thread_id else None
    )
    contact_id = sequence.contact_id or (thread.contact_id if thread else None)
    contact = await session.get(Contact, contact_id) if contact_id else None
    if contact is not None and sequence.contact_id is None:
        sequence.contact_id = contact.id
    if thread is None and contact is not None:
        thread = await pursued_thread_for(session, contact, campaign_id=sequence.campaign_id)
        if thread is not None:
            sequence.thread_id = thread.id
    return contact, thread


async def live_thread_count(session: AsyncSession, account_id: uuid.UUID) -> int:
    """Live sequences for an account, across **every** campaign.

    With no cross-queue dedup, `sales_rules.max_concurrent_threads` is the only
    thing stopping one account being worked by two campaigns at once — so this
    counts globally rather than per campaign, and is checked at promotion where
    a rep can act on the conflict. A send-time skip is invisible.
    """
    count = await session.scalar(
        select(func.count())
        .select_from(OutreachSequence)
        .join(StrategyThread, StrategyThread.id == OutreachSequence.thread_id)
        .join(Contact, Contact.id == StrategyThread.contact_id)
        .where(
            Contact.account_id == account_id,
            OutreachSequence.status.in_(SEQUENCE_NON_TERMINAL),
        )
    )
    return count or 0


async def enrol_thread(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    thread: StrategyThread,
    lgm_identity_id: uuid.UUID | None,
    cadence_shape_id: uuid.UUID | None = None,
    selection_log: dict | None = None,
    defer_if_blocked: bool = True,
) -> OutreachSequence | DeferredEnrolment:
    """Create the sequence, letting the index decide whether it may exist.

    No pre-check. The insert is attempted and a unique violation is caught —
    that is the whole point of putting the rule in an index. Checking first and
    inserting second is a race with a comfortable-looking test.
    """
    sequence = OutreachSequence(
        thread_id=thread.id,
        campaign_id=campaign_id,
        cadence_shape_id=cadence_shape_id,
        lgm_identity_id=lgm_identity_id,
        start_offset_days=thread.start_offset_days,
        status="pending_approval",
        selection_log=selection_log,
    )
    session.add(sequence)
    try:
        # A SAVEPOINT, so a rejection costs this enrolment and not the whole
        # promotion — the rest of the campaign still goes in.
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as exc:
        if "one_active_sequence_per_lgm_identity" not in str(exc.orig):
            raise
        if not defer_if_blocked:
            raise ContactAlreadyEnrolledError(
                f"contact {thread.contact_id} already holds a live sequence"
            ) from exc

        blocker = (
            await session.execute(
                select(OutreachSequence).where(
                    OutreachSequence.lgm_identity_id == lgm_identity_id,
                    OutreachSequence.status.in_(SEQUENCE_NON_TERMINAL),
                )
            )
        ).scalar_one_or_none()

        deferral = DeferredEnrolment(
            campaign_id=campaign_id,
            contact_id=thread.contact_id,
            blocked_by_sequence_id=blocker.id if blocker else None,
            status="waiting",
        )
        session.add(deferral)
        await session.flush()
        return deferral

    return sequence


#: Thread statuses that actually get a sequence. `queued` is above the
#: threshold but beyond the concurrent cap, and `not_activated` fell below it —
#: neither is being pursued, so neither becomes a sequence.
PURSUED = ("active_primary", "active_secondary")


async def _sequences_for_member(
    session: AsyncSession,
    *,
    campaign: OutreachCampaign,
    account_id: uuid.UUID,
    default_shape_id: uuid.UUID | None,
    done_contacts: set | None = None,
) -> tuple[list[OutreachSequence], list[str]]:
    """Copy one account's pursued strategy threads into the campaign.

    Copy, not link: the sequence is the campaign's own record from here on, and
    nothing flows back to the strategy it came from.
    """
    from app.models.account import Account
    from app.models.campaign import CadenceShape
    from app.models.context import Qualification
    from app.models.strategy import Strategy
    from app.services import sizing
    from app.services.cadence import SelectionInput, select_shape_key
    from app.services.lgm_identity import UnresolvableContactError, keys_for, resolve

    account = await session.get(Account, account_id)
    if account is None:
        return [], [f"account {account_id} not found"]

    strategy = (
        await session.execute(
            select(Strategy)
            .where(Strategy.account_id == account_id)
            .order_by(Strategy.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if strategy is None:
        return [], [f"{account.name}: no strategy built yet"]

    threads = list(
        (
            await session.execute(
                select(StrategyThread)
                .where(
                    StrategyThread.strategy_id == strategy.id,
                    StrategyThread.thread_status.in_(PURSUED),
                )
                .order_by(StrategyThread.rank)
            )
        ).scalars()
    )
    if not threads:
        return [], [f"{account.name}: no threads are being pursued"]

    qualification = (
        await session.execute(
            select(Qualification)
            .where(Qualification.account_id == account_id)
            .order_by(Qualification.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    made: list[OutreachSequence] = []
    skipped: list[str] = []
    done_contacts = done_contacts if done_contacts is not None else set()
    for thread in threads:
        contact = await session.get(Contact, thread.contact_id)
        if contact is None:
            skipped.append("a thread has no contact")
            continue
        if contact.id in done_contacts:
            # Chosen as a person in this promotion already: one sequence each.
            continue
        done_contacts.add(contact.id)
        sequence, note = await _sequence_for(
            session, campaign=campaign, contact=contact, account=account, thread=thread,
            qualification=qualification, default_shape_id=default_shape_id,
        )
        if note:
            skipped.append(note)
        if sequence is not None:
            made.append(sequence)

    return made, skipped


async def _sequence_for_person(
    session: AsyncSession,
    *,
    campaign: OutreachCampaign,
    contact_id: uuid.UUID,
    default_shape_id: uuid.UUID | None,
) -> tuple[OutreachSequence | None, str | None]:
    """A sequence for a person chosen by name. No strategy is needed yet."""
    from app.models.account import Account
    from app.models.context import Qualification

    contact = await session.get(Contact, contact_id)
    if contact is None:
        return None, "a queued person no longer exists"
    account = await session.get(Account, contact.account_id)
    if account is None:
        return None, f"{contact.full_name}: their company no longer exists"
    qualification = (
        await session.execute(
            select(Qualification)
            .where(Qualification.account_id == account.id)
            .order_by(Qualification.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    thread = await pursued_thread_for(session, contact, campaign_id=campaign.id)
    return await _sequence_for(
        session, campaign=campaign, contact=contact, account=account, thread=thread,
        qualification=qualification, default_shape_id=default_shape_id,
    )


async def _sequence_for(
    session: AsyncSession,
    *,
    campaign: OutreachCampaign,
    contact,
    account,
    thread: StrategyThread | None,
    qualification,
    default_shape_id: uuid.UUID | None,
) -> tuple[OutreachSequence | None, str | None]:
    """One person's sequence: their LGM lead, their cadence, and the enrolment lock."""
    from app.models.campaign import CadenceShape
    from app.services import sizing
    from app.services.cadence import SelectionInput, select_shape_key
    from app.services.lgm_identity import UnresolvableContactError, keys_for, resolve

    # Resolve to the LGM lead this person would become. Done at promotion so a
    # conflict surfaces here rather than at send time.
    identity_id = contact.lgm_identity_id
    if identity_id is None:
        try:
            identity = await resolve(
                session,
                keys_for(
                    linkedin_url=contact.linkedin_url,
                    email=contact.email,
                    full_name=contact.full_name,
                    company=account.name,
                ),
            )
        except UnresolvableContactError as exc:
            return None, f"{contact.full_name}: {exc}"
        contact.lgm_identity_id = identity.id
        identity_id = identity.id

    # Deterministic shape selection, logged so "why did this account get the
    # enterprise cadence?" is answerable from the row months later.
    shape_key, selection_log = select_shape_key(
        SelectionInput(
            email_status=contact.email_status,
            size_band=sizing.band_for(account.employee_count),
            priority_band=qualification.priority_band if qualification else "low",
        )
    )
    suggested = (
        await session.execute(select(CadenceShape).where(CadenceShape.key == shape_key))
    ).scalar_one_or_none()
    # **The campaign's cadence wins.** One campaign is one LGM campaign, and an
    # LGM campaign is one sequence: six steps or four, not both. Copy is written
    # into that sequence's attribute slots, so a person drafted for a four-touch
    # cadence and enrolled into a six-touch one leaves steps 5 and 6 sending
    # whatever the lead already held. The rules still run — what they chose is
    # recorded, and a different answer is worth seeing when the campaign is
    # built — but they advise; they do not split a campaign in two.
    shape = await session.get(CadenceShape, default_shape_id) if default_shape_id else suggested
    if shape is not None and suggested is not None and suggested.id != shape.id:
        selection_log = {
            **selection_log,
            "overridden_by_campaign": (
                f"the rules chose {suggested.key}; this campaign runs {shape.key}"
            ),
        }
    if shape is None:
        return None, f"{contact.full_name}: cadence {shape_key!r} is not registered"

    sequence = OutreachSequence(
        thread_id=thread.id if thread else None,
        contact_id=contact.id,
        campaign_id=campaign.id,
        cadence_shape_id=shape.id,
        lgm_identity_id=identity_id,
        start_offset_days=thread.start_offset_days if thread else 0,
        # Draft, not pending_approval: there is no content yet. Drafting is its
        # own stage, and a sequence cannot be approved before the arc exists.
        status="draft",
        selection_log=selection_log,
    )
    session.add(sequence)
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as exc:
        if "one_active_sequence_per_lgm_identity" not in str(exc.orig):
            raise
        # The person already holds a live sequence elsewhere. Recorded rather
        # than dropped, so a worker can enrol them when it frees up.
        session.add(
            DeferredEnrolment(campaign_id=campaign.id, contact_id=contact.id, status="waiting")
        )
        await session.flush()
        return None, f"{contact.full_name}: already holds a live sequence — deferred"
    return sequence, None


async def promote(
    session: AsyncSession,
    *,
    queue_ids: list[uuid.UUID],
    label: str | None = None,
    cadence_shape_id: uuid.UUID | None = None,
) -> OutreachCampaign:
    """Lock the source queues, open a campaign, and copy the threads in.

    Locking happens here and nowhere else. A queue that fed a campaign is a
    historical record from this moment on.

    `label` defaults to the first source queue's label. Carrying the name
    across is deliberate: the queue and the campaign it became are the same
    piece of work to everyone who has to follow it, and renaming at the
    boundary breaks the thread for no gain.

    Sequences are created here — `docs/03`: promotion "copies its members'
    strategy threads into the campaign". They are created **without content**;
    drafting is its own stage and a sequence stays `draft` until an arc exists.
    """
    queues: list[CampaignQueue] = []
    for queue_id in queue_ids:
        queue = await session.get(CampaignQueue, queue_id)
        if queue is None:
            raise ValueError(f"queue {queue_id} not found")
        if queue.status == "locked":
            raise QueueLockedError(
                f"queue {queue.label!r} was already promoted at {queue.locked_at}; "
                "clone it rather than promoting it twice"
            )
        queues.append(queue)

    # Everyone in a campaign is approached about one service, for one ICP.
    targets = {
        (q.service_id, q.icp_profile_id, q.icp_version) for q in queues if q.service_id is not None
    }
    if len(targets) > 1:
        raise MixedTargetsError(
            "these queues were built for different services or ICPs — a campaign argues for one. "
            "Promote them separately."
        )
    service_id, icp_profile_id, icp_version = next(iter(targets), (None, None, None))

    campaign = OutreachCampaign(
        label=label or queues[0].label,
        status="draft",
        cadence_shape_id=cadence_shape_id,
        service_id=service_id,
        icp_profile_id=icp_profile_id,
        icp_version=icp_version,
    )
    session.add(campaign)
    await session.flush()

    now = datetime.now(UTC)
    account_ids: list[uuid.UUID] = []
    contact_ids: list[uuid.UUID] = []
    for queue in queues:
        queue.status = "locked"
        queue.locked_at = now
        queue.promoted_to_campaign_id = campaign.id
        session.add(
            OutreachCampaignSource(campaign_id=campaign.id, queue_id=queue.id)
        )
        account_ids.extend(
            (
                await session.execute(
                    select(CampaignQueueMember.account_id).where(
                        CampaignQueueMember.queue_id == queue.id
                    )
                )
            ).scalars()
        )
        contact_ids.extend(
            (
                await session.execute(
                    select(CampaignQueueContact.contact_id).where(
                        CampaignQueueContact.queue_id == queue.id
                    )
                )
            ).scalars()
        )

    # Deduplicated: two overlapping queues must not create two sequences for
    # one account's threads.
    #
    # `promotion_notes` is attached to the returned object for the caller to
    # surface; it is not a column. What was skipped and why has to reach the
    # rep, or a campaign quietly comes out smaller than the queue that fed it.
    notes: list[str] = []
    done_contacts: set[uuid.UUID] = set()
    # People chosen by name come first — campaigns are built from people. No
    # strategy is needed yet: it is required before execution, and linked to
    # the sequence once it exists.
    for contact_id in dict.fromkeys(contact_ids):
        done_contacts.add(contact_id)
        _, note = await _sequence_for_person(
            session, campaign=campaign, contact_id=contact_id, default_shape_id=cadence_shape_id,
        )
        if note:
            notes.append(note)
    for account_id in dict.fromkeys(account_ids):
        _, skipped = await _sequences_for_member(
            session,
            campaign=campaign,
            account_id=account_id,
            default_shape_id=cadence_shape_id,
            done_contacts=done_contacts,
        )
        notes.extend(skipped)

    campaign.promotion_notes = notes
    await session.flush()
    return campaign


# ---------------------------------------------------------------------------
# changing which LGM campaign a campaign runs on
# ---------------------------------------------------------------------------
class CadenceSwapRefused(RuntimeError):
    """The cadence cannot be changed without losing or misplacing copy."""


async def change_cadence(
    session: AsyncSession, *, campaign_id: uuid.UUID, shape_id: uuid.UUID
) -> dict:
    """Point a campaign at a different registered cadence.

    Not something anybody planned to need. It became necessary the first time
    an LGM campaign was **deleted and rebuilt**: the registration died with it,
    and the campaign behind it held a strategy and approved drafts that were
    still perfectly good. Without this the only way forward was to build the
    campaign again and throw that work away.

    Two things make a swap safe, and both are checked rather than assumed.

    * **Nothing may have been written to LGM.** Once a sequence is enrolled its
      copy is frozen — LGM holds it — and repointing our row would describe a
      sequence that is not the one running.
    * **The steps must line up.** Each touch's body is written into a specific
      `custom_attribute_N` that one step's template reads. A different step
      count means the arcs no longer fit, and a different map means every
      touch would be sending into the wrong step: the same words, the right
      person, the wrong message. So the touches are re-pointed through the new
      shape's map here, and a step the new shape does not map is a refusal.
    """
    campaign = await session.get(OutreachCampaign, campaign_id)
    if campaign is None:
        raise ValueError(f"campaign {campaign_id} not found")
    shape = await session.get(CadenceShape, shape_id)
    if shape is None:
        raise ValueError(f"cadence shape {shape_id} not found")
    if campaign.cadence_shape_id == shape.id:
        return {"changed": False, "detail": f"already running {shape.key}", "touches_remapped": 0}

    sequences = list(
        (
            await session.execute(
                select(OutreachSequence).where(
                    OutreachSequence.campaign_id == campaign_id,
                    OutreachSequence.status != "cancelled",
                )
            )
        ).scalars()
    )
    enrolled = [s for s in sequences if s.status not in WITHDRAWABLE]
    if enrolled:
        raise CadenceSwapRefused(
            f"{len(enrolled)} sequence(s) have already been written to La Growth Machine; their "
            "content is frozen there. Stop them and re-enrol to move them to another cadence"
        )

    from app.models.content import Touch

    arcs = {
        s.id: list(
            (
                await session.execute(
                    select(Touch).where(Touch.sequence_id == s.id).order_by(Touch.step_no)
                )
            ).scalars()
        )
        for s in sequences
    }
    mismatched = [s for s in sequences if arcs[s.id] and len(arcs[s.id]) != shape.touch_count]
    if mismatched:
        raise CadenceSwapRefused(
            f"{len(mismatched)} sequence(s) are drafted for {len(arcs[mismatched[0].id])} steps and "
            f"{shape.key!r} runs {shape.touch_count}. Withdraw them or draft them again first — a "
            "short arc would leave the later steps sending whatever the lead already held"
        )

    attribute_map = shape.attribute_map or {}
    remapped = 0
    for sequence in sequences:
        for touch in arcs[sequence.id]:
            attribute = attribute_map.get(str(touch.step_no))
            if not attribute:
                raise CadenceSwapRefused(
                    f"{shape.key!r} maps no attribute for step {touch.step_no}; copy written there "
                    "would never appear in the message"
                )
            if touch.lgm_attribute != attribute:
                touch.lgm_attribute = attribute
                remapped += 1
        sequence.cadence_shape_id = shape.id

    previous = campaign.cadence_shape_id
    campaign.cadence_shape_id = shape.id
    await session.flush()
    log.info(
        "promotion.cadence_changed campaign=%s from=%s to=%s remapped=%d",
        campaign_id, previous, shape.id, remapped,
    )
    return {
        "changed": True,
        "touches_remapped": remapped,
        "sequences": len(sequences),
        "detail": (
            f"{campaign.label!r} now runs {shape.key}"
            + (f", {remapped} touch(es) re-pointed to its attributes" if remapped else "")
        ),
    }
