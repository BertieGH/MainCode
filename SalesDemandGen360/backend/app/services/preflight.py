"""The execute checklist.

Every item blocks. There is no "warn and proceed" tier, because the button this
guards is the irreversible one: after execute, the copy is frozen on the LGM
lead and the only remaining levers are stopping one sequence or the whole
campaign.

Each check returns a **reason**, not a boolean. A rep who is told "pre-flight
failed" cannot act; one told "3 of 18 threads are unapproved" can.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.campaign import (
    SEQUENCE_NON_TERMINAL,
    CadenceShape,
    OutreachCampaign,
    OutreachSequence,
)
from app.models.config import SalesRules
from app.models.content import Touch
from app.services.cadence import check_enrolment
from app.services.drafting import ATTRIBUTE_BUDGET


@dataclass
class Check:
    key: str
    label: str
    passed: bool
    detail: str
    #: Ids a rep can act on — the unapproved threads, the conflicting contacts.
    subjects: list[str] = field(default_factory=list)
    #: The same subjects as people: {sequence_id, contact_id, name}. A list of
    #: uuids is not something anybody can act on, and "2 of 4 not approved"
    #: without saying *which two* sends a rep hunting through the campaign.
    people: list[dict] = field(default_factory=list)


@dataclass
class Preflight:
    campaign_id: uuid.UUID
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]

    def summary(self) -> str:
        if self.passed:
            return "all checks pass"
        return "; ".join(f"{c.label}: {c.detail}" for c in self.failures)


async def run(
    session: AsyncSession, campaign_id: uuid.UUID, *, live: bool = True
) -> Preflight:
    """Every check, always — never short-circuit on the first failure.

    A rep fixing a campaign needs the whole list. Stopping at the first problem
    turns one review into four round trips, and the screen is the gate metric.

    `live` asks LGM whether this campaign's registered cadence still exists
    there. It is on by default because the answer cannot be inferred from
    anything stored: a campaign deleted in LGM leaves a registration that looks
    verified and healthy, and this checklist reported the whole campaign ready
    to execute against one. Pass `live=False` in tests and anywhere a network
    call would be wrong.
    """
    result = Preflight(campaign_id=campaign_id)
    campaign = await session.get(OutreachCampaign, campaign_id)
    if campaign is None:
        result.checks.append(
            Check("campaign", "Campaign exists", False, "campaign not found")
        )
        return result

    sequences = list(
        (
            await session.execute(
                # Withdrawn people are out of this campaign: they block
                # nothing and are enrolled by nothing.
                select(OutreachSequence).where(
                    OutreachSequence.campaign_id == campaign_id,
                    OutreachSequence.status != "cancelled",
                )
            )
        ).scalars()
    )

    shape = (
        await session.get(CadenceShape, campaign.cadence_shape_id)
        if campaign.cadence_shape_id
        else None
    )

    result.checks.append(await _has_threads(sequences))
    result.checks.append(await _has_strategy(session, sequences))
    result.checks.append(await _threads_approved(session, sequences))
    if live:
        await _confirm_shape_still_exists(session, campaign)
    result.checks.append(await _cadence_current(session, campaign))
    result.checks.append(await _attribute_budget(session, sequences))
    result.checks.append(await _enrolment_lock(session, sequences))
    result.checks.append(await _screened(session, sequences))
    result.checks.append(await _not_suppressed(session, sequences))
    result.checks.append(await _one_cadence(session, campaign, sequences))
    result.checks.append(await _content_ready(session, sequences, shape))
    await _name_subjects(session, result, sequences)
    return result


async def _name_subjects(session: AsyncSession, result: Preflight, sequences) -> None:
    """Turn each check's subject ids into people, once for the whole run."""
    from app.services.promotion import person_of

    known: dict[str, dict] = {}
    for sequence in sequences:
        contact, _ = await person_of(session, sequence)
        known[str(sequence.id)] = {
            "sequence_id": str(sequence.id),
            "contact_id": str(contact.id) if contact else None,
            "name": contact.full_name if contact else "somebody who no longer exists",
        }
    for check in result.checks:
        check.people = [known[s] for s in check.subjects if s in known]


async def _has_threads(sequences: list[OutreachSequence]) -> Check:
    return Check(
        "has_threads",
        "Campaign has threads",
        bool(sequences),
        f"{len(sequences)} sequence(s)" if sequences
        else "no sequences — nothing to execute",
    )


async def _has_strategy(session: AsyncSession, sequences: list[OutreachSequence]) -> Check:
    """Every person has a strategy — required before execution, not at promotion.

    A person chosen by name is promoted before any strategy exists; this is the
    gate that stops them being sent anything until one is built. A strategy
    built since promotion is linked on the way (`promotion.person_of`).
    """
    from app.services.promotion import person_of

    missing: list[str] = []
    names: list[str] = []
    for sequence in sequences:
        contact, thread = await person_of(session, sequence)
        if thread is None:
            missing.append(str(sequence.id))
            names.append(contact.full_name if contact else "a sequence with no person")
    return Check(
        "strategy",
        "Every person has a strategy",
        not missing,
        "every sequence has a strategy" if not missing
        else f"no strategy yet for {', '.join(names)} — build it before executing",
        missing,
    )


async def _threads_approved(session: AsyncSession, sequences: list[OutreachSequence]) -> Check:
    """Nothing sends without a human approval row. This is the gate."""
    if not sequences:
        return Check("approved", "Threads approved", False, "no sequences to approve")

    from app.services import campaign_drafts

    # A row counts only while the words are as approved: an edit since returns
    # the sequence to draft, and a sequence with no content was never approvable.
    approved = await campaign_drafts.approved_ids(session, sequences)
    missing = [s for s in sequences if s.id not in approved]
    return Check(
        "approved",
        "Threads approved",
        not missing,
        f"all {len(sequences)} approved" if not missing
        else f"{len(missing)} of {len(sequences)} thread(s) not approved",
        [str(s.id) for s in missing],
    )


async def _confirm_shape_still_exists(session: AsyncSession, campaign: OutreachCampaign) -> None:
    """Ask LGM whether this campaign's cadence is still there, before judging it.

    One listing, and only when a key is stored. Anything that goes wrong —
    no key, no reach, an empty answer — leaves the stored status alone: a
    network problem is not evidence that somebody deleted a campaign.
    """
    if campaign.cadence_shape_id is None:
        return
    shape = await session.get(CadenceShape, campaign.cadence_shape_id)
    if shape is None:
        return
    from app.services import lgm_client
    from app.services.lgm import LgmError

    adapter = await lgm_client.from_credentials(session)
    if adapter is None:
        return
    try:
        live = {str(c.get("id")) for c in await adapter.campaigns() if c.get("id")}
    except LgmError:
        return
    if not live:
        return
    if shape.lgm_campaign_id not in live:
        shape.lgm_status = lgm_client.STATUS_MISSING
        shape.verified_at, shape.verified_by = None, None
        await session.flush()
    elif shape.lgm_status == lgm_client.STATUS_MISSING:
        shape.lgm_status = None
        await session.flush()


async def _cadence_current(session: AsyncSession, campaign: OutreachCampaign) -> Check:
    """A changed-in-LGM shape blocks: a stale attribute map writes copy into
    the wrong step, and the message sends looking perfectly plausible."""
    if campaign.cadence_shape_id is None:
        return Check(
            "cadence", "Cadence registration current", False,
            "no cadence shape selected for this campaign",
        )
    shape = await session.get(CadenceShape, campaign.cadence_shape_id)
    if shape is None:
        return Check("cadence", "Cadence registration current", False, "shape not found")

    blocks = [b for b in check_enrolment(shape) if b.blocking]
    warnings = [b for b in check_enrolment(shape) if not b.blocking]
    if blocks:
        detail = "; ".join(b.detail for b in blocks)
    elif warnings:
        # Passes, and still says so: a campaign that has never been launched
        # takes the copy now and sends nothing until somebody launches it in
        # LGM. Silence here would look like "sending has started".
        detail = "; ".join(b.detail for b in warnings)
    else:
        detail = f"{shape.key} verified and unchanged"
    return Check(
        "cadence",
        "Cadence registration current",
        not blocks,
        detail,
        [b.reason for b in blocks + warnings],
    )


async def _attribute_budget(session: AsyncSession, sequences: list[OutreachSequence]) -> Check:
    """LGM drops the overflow silently, so this must be caught before the write."""
    over: list[str] = []
    worst = 0
    for sequence in sequences:
        touches = list(
            (
                await session.execute(select(Touch).where(Touch.sequence_id == sequence.id))
            ).scalars()
        )
        needed = len(touches) + sum(
            1 for t in touches if t.subject_source == "custom_attribute"
        )
        worst = max(worst, needed)
        if needed > ATTRIBUTE_BUDGET:
            over.append(str(sequence.id))

    return Check(
        "attributes",
        f"Attribute budget within {ATTRIBUTE_BUDGET}",
        not over,
        f"largest sequence uses {worst} of {ATTRIBUTE_BUDGET}" if not over
        else f"{len(over)} sequence(s) exceed the {ATTRIBUTE_BUDGET}-attribute cap; "
             "LGM refuses the write, which would fail the campaign part-enrolled",
        over,
    )


async def _enrolment_lock(session: AsyncSession, sequences: list[OutreachSequence]) -> Check:
    """A contact already holding a live sequence elsewhere.

    Surfaced here rather than left to the index, because the index would reject
    the insert mid-execution and leave the campaign half-enrolled. The rep can
    act on it now.
    """
    conflicts: list[str] = []
    unresolved: list[str] = []
    for sequence in sequences:
        if sequence.lgm_identity_id is None:
            unresolved.append(str(sequence.id))
            continue
        held = (
            await session.execute(
                select(func.count())
                .select_from(OutreachSequence)
                .where(
                    OutreachSequence.lgm_identity_id == sequence.lgm_identity_id,
                    OutreachSequence.status.in_(SEQUENCE_NON_TERMINAL),
                    OutreachSequence.campaign_id != sequence.campaign_id,
                )
            )
        ).scalar() or 0
        if held:
            conflicts.append(str(sequence.id))

    problems = conflicts + unresolved
    parts = []
    if conflicts:
        parts.append(
            f"{len(conflicts)} contact(s) already hold a live sequence in another campaign"
        )
    if unresolved:
        parts.append(f"{len(unresolved)} contact(s) have no resolved LGM identity")
    return Check(
        "enrolment_lock",
        "Contact enrolment lock",
        not problems,
        "no contact holds a competing sequence" if not problems else "; ".join(parts),
        problems,
    )


async def _screened(session: AsyncSession, sequences: list[OutreachSequence]) -> Check:
    """No-go list, disqualified accounts, and unverified contacts on email."""
    from app.services.promotion import person_of

    rules = (
        await session.execute(select(SalesRules).where(SalesRules.is_active.is_(True)))
    ).scalar_one_or_none()
    no_go = {
        str(d).strip().upper()
        for d in ((rules.no_go or {}).get("domains", []) if rules else [])
    }

    blocked: list[str] = []
    reasons: list[str] = []
    for sequence in sequences:
        contact, _ = await person_of(session, sequence)
        if contact is None:
            continue
        account = await session.get(Account, contact.account_id)
        if account is None:
            continue

        if account.status == "disqualified":
            blocked.append(str(sequence.id))
            reasons.append(f"{account.name} is disqualified")
        elif account.domain and account.domain.strip().upper() in no_go:
            blocked.append(str(sequence.id))
            reasons.append(f"{account.name} is on the no-go list")
        elif contact.email_status != "verified" and _uses_email(
            await _touch_channels(session, sequence.id)
        ):
            blocked.append(str(sequence.id))
            reasons.append(f"{contact.full_name} has an unverified email but has email touches")

    return Check(
        "screened",
        "No-go and verification screened",
        not blocked,
        "nothing screened out" if not blocked else "; ".join(dict.fromkeys(reasons)),
        blocked,
    )


async def _one_cadence(
    session: AsyncSession, campaign, sequences: list[OutreachSequence]
) -> Check:
    """Everybody runs the campaign's cadence, and their drafts fit it.

    An LGM campaign is one sequence — six steps or four, never both — and the
    copy lands in that sequence's attribute slots. Somebody drafted for four
    touches and enrolled into a six-touch campaign leaves steps 5 and 6 sending
    whatever the lead already held, which is the failure nobody sees until a
    recipient does.
    """
    from app.models.campaign import CadenceShape
    from app.models.content import Touch
    from app.services.promotion import person_of

    shape = (
        await session.get(CadenceShape, campaign.cadence_shape_id)
        if campaign.cadence_shape_id
        else None
    )
    if shape is None:
        return Check(
            "one_cadence", "One cadence for the campaign", False,
            "this campaign has no cadence — promotion chooses one, and every person runs it",
            [],
        )

    wrong: list[str] = []
    detail: list[str] = []
    for sequence in sequences:
        contact, _ = await person_of(session, sequence)
        name = contact.full_name if contact else str(sequence.id)
        if sequence.cadence_shape_id and sequence.cadence_shape_id != shape.id:
            other = await session.get(CadenceShape, sequence.cadence_shape_id)
            wrong.append(str(sequence.id))
            detail.append(f"{name} is on {other.key if other else 'another cadence'}")
            continue
        touches = await session.scalar(
            select(func.count()).select_from(Touch).where(Touch.sequence_id == sequence.id)
        )
        if touches and touches != shape.touch_count:
            wrong.append(str(sequence.id))
            detail.append(
                f"{name} has {touches} touches drafted for a {shape.touch_count}-step cadence "
                "— write their drafts again"
            )

    return Check(
        "one_cadence",
        "One cadence for the campaign",
        not wrong,
        f"everyone runs {shape.key}" if not wrong else "; ".join(dict.fromkeys(detail)),
        wrong,
    )


async def _not_suppressed(session: AsyncSession, sequences: list[OutreachSequence]) -> Check:
    """Nobody marked do-not-contact is still in the campaign.

    Checked here rather than only at queueing: somebody is usually marked
    *because* of what a campaign did, and the campaign holding them was
    promoted before that happened.
    """
    from app.services.promotion import person_of

    blocked: list[str] = []
    names: list[str] = []
    for sequence in sequences:
        contact, _ = await person_of(session, sequence)
        if contact is not None and contact.do_not_contact:
            blocked.append(str(sequence.id))
            names.append(f"{contact.full_name} ({contact.do_not_contact_reason})")
    return Check(
        "do_not_contact",
        "Nobody is marked do-not-contact",
        not blocked,
        "nobody is suppressed" if not blocked
        else "remove them from this campaign first — " + "; ".join(names),
        blocked,
    )


async def _content_ready(
    session: AsyncSession, sequences: list[OutreachSequence], shape: CadenceShape | None = None
) -> Check:
    """Every touch mapped to an attribute, and none already failed to write.

    Content in our database is not content on the LGM lead — a half-written
    campaign is invisible until a recipient gets the wrong message.

    Subjects are checked separately from bodies because they are separate
    fields in LGM: a custom subject can only appear where that step's subject
    template names an attribute. A subject with nowhere to go used to be
    written to an invented field, which made LGM reject the entire lead.
    """
    subject_map = (shape.subject_attribute_map or {}) if shape is not None else {}
    problems: list[str] = []
    detail: list[str] = []
    for sequence in sequences:
        touches = list(
            (
                await session.execute(select(Touch).where(Touch.sequence_id == sequence.id))
            ).scalars()
        )
        if not touches:
            problems.append(str(sequence.id))
            detail.append("a sequence has no touches")
            continue
        if any(t.lgm_attribute is None for t in touches):
            problems.append(str(sequence.id))
            detail.append("a sequence has steps with no LGM attribute mapped")
        if any(t.content_sync_status == "failed" for t in touches):
            problems.append(str(sequence.id))
            detail.append("a previous attribute write failed and was not retried")
        homeless = [
            t.step_no
            for t in touches
            if t.subject_source == "custom_attribute" and not subject_map.get(str(t.step_no))
        ]
        if homeless and shape is not None:
            problems.append(str(sequence.id))
            detail.append(
                f"step(s) {', '.join(str(n) for n in sorted(homeless))} have a written subject line, "
                f"but {shape.key!r} has no subject attribute for them — add a "
                "{{customAttributeN}} to that step's subject in LGM, or let the step use its own"
            )

    return Check(
        "content_ready",
        "Content mapped and writable",
        not problems,
        "every touch maps to an attribute" if not problems
        else "; ".join(dict.fromkeys(detail)),
        problems,
    )


async def _touch_channels(session: AsyncSession, sequence_id: uuid.UUID) -> list[str]:
    return list(
        (
            await session.execute(
                select(Touch.channel).where(Touch.sequence_id == sequence_id)
            )
        ).scalars()
    )


def _uses_email(channels: list[str]) -> bool:
    return any(c in ("email", "inmail") for c in channels)
