"""Enrolment, the send-time interlock, and the two stop paths.

`execute` is the irreversible act in this system. After it, the copy lives on
the LGM lead and cannot be edited — LGM reads from the lead, not from us — so
the only remaining levers are stopping one sequence or the whole campaign.

Everything here is written on the assumption that it will one day be called
against a real provider with a real recipient at the other end, so:

* pre-flight is re-run inside `execute`, not trusted from the caller;
* one lead failing to write costs that sequence, not the campaign;
* a stop is recorded even when the provider call fails, because a stop that
  silently did not happen is worse than one that errored loudly.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, Contact
from app.models.campaign import CadenceShape, OutreachCampaign, OutreachSequence
from app.models.config import SalesRules
from app.models.content import Draft, Touch
from app.models.execution import ExecutionRecord
from app.models.strategy import StrategyThread
from app.services import preflight
from app.services.lgm import LgmAdapter, LgmError

log = logging.getLogger(__name__)


class PreflightFailedError(RuntimeError):
    """Execution refused. Carries the failing checks so the caller can say why."""

    def __init__(self, result: preflight.Preflight):
        self.result = result
        super().__init__(result.summary())


class ContentFrozenError(RuntimeError):
    """A draft edit was attempted after enrolment. Surfaces as 409."""


@dataclass
class ExecutionOutcome:
    campaign_id: uuid.UUID
    enrolled: list[uuid.UUID] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)
    #: The people and their copy are in LGM's audience, and the campaign there
    #: has never been launched — so nothing is sending yet. LGM will not launch
    #: a campaign with an empty audience, which is why this state exists at all
    #: rather than being refused: this write is what makes the launch possible.
    awaiting_launch: bool = False
    #: The audience they were written into, named so a rep can find it in LGM.
    audience: str | None = None

    @property
    def any_enrolled(self) -> bool:
        return bool(self.enrolled)


# ---------------------------------------------------------------------------
# the send-time interlock
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class InterlockVerdict:
    proceed: bool
    reason: str | None = None
    snapshot: dict = field(default_factory=dict)


async def check_interlock(
    session: AsyncSession, sequence: OutreachSequence, *, channel: str | None = None
) -> InterlockVerdict:
    """Re-check the facts immediately before a send.

    The one deliberate exception to "nothing flows backward". A campaign is
    decoupled from its queue, so a company that lands on the no-go list today
    would otherwise keep receiving touches from a campaign approved last week.
    This is a compliance guard, not a sync: the send stops and nothing
    propagates back.
    """
    from app.services.promotion import person_of

    contact, _ = await person_of(session, sequence)
    account = await session.get(Account, contact.account_id) if contact else None
    if account is None or contact is None:
        return InterlockVerdict(False, "sequence_stopped", {"reason": "orphaned sequence"})

    snapshot = {
        "account_status": account.status,
        "domain": account.domain,
        "email_status": contact.email_status,
        "sequence_status": sequence.status,
        "checked_at": datetime.now(UTC).isoformat(),
    }

    if sequence.status in ("stopped", "cancelled", "completed"):
        return InterlockVerdict(False, "sequence_stopped", snapshot)

    if account.status == "disqualified":
        return InterlockVerdict(False, "account_disqualified", snapshot)

    rules = (
        await session.execute(select(SalesRules).where(SalesRules.is_active.is_(True)))
    ).scalar_one_or_none()
    no_go = {
        str(d).strip().upper()
        for d in ((rules.no_go or {}).get("domains", []) if rules else [])
    }
    if account.domain and account.domain.strip().upper() in no_go:
        return InterlockVerdict(False, "no_go_list", snapshot)

    # An email touch to an unverified address is a bounce, and bounce rate is
    # the metric the whole sending domain's reputation rests on.
    if channel in ("email", "inmail") and contact.email_status != "verified":
        return InterlockVerdict(False, "contact_unverified", snapshot)

    return InterlockVerdict(True, None, snapshot)


# ---------------------------------------------------------------------------
# execution
# ---------------------------------------------------------------------------
def _attributes_for(
    touches: list[Touch], drafts: dict[uuid.UUID, Draft], shape=None
) -> dict[str, str]:
    """Map every touch's current draft onto the attribute its step consumes.

    A subject needs its **own** attribute, named by that step's subject
    template in LGM. This used to write one to `<body attribute>_subject`, a
    field that does not exist — and an unknown field makes LGM reject the whole
    lead, so body and subject were both lost. Now a custom subject is only sent
    where the registration recorded a slot for it, and pre-flight refuses the
    campaign when one is missing rather than dropping the line quietly.
    """
    subject_map = (shape.subject_attribute_map or {}) if shape is not None else {}
    attributes: dict[str, str] = {}
    for touch in sorted(touches, key=lambda t: t.step_no):
        draft = drafts.get(touch.id)
        if draft is None or touch.lgm_attribute is None:
            continue
        attributes[touch.lgm_attribute] = draft.body
        if touch.subject_source == "custom_attribute" and draft.subject:
            slot = subject_map.get(str(touch.step_no))
            if slot:
                attributes[slot] = draft.subject
    return attributes


async def _person_for(session: AsyncSession, contact):
    """The matching fields LGM keeps, plus our id as its `crm_id`.

    `crm_id` is what makes a reply traceable back to a person here: LGM echoes
    it on lead lookups and conversation records, so nothing downstream has to
    match on an email address that may have been updated since.
    """
    from app.models.account import Account
    from app.services.lgm_client import LgmPerson, split_name

    account = await session.get(Account, contact.account_id) if contact else None
    first, last = split_name(contact.full_name if contact else None)
    return LgmPerson(
        first_name=first or None,
        last_name=last or None,
        company_name=account.name if account else None,
        company_url=f"https://{account.domain}" if account and account.domain else None,
        job_title=contact.title if contact else None,
        crm_id=str(contact.id) if contact else None,
    )


async def execute(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    lgm: LgmAdapter,
) -> ExecutionOutcome:
    """Write every approved draft to its lead, enrol, and start the campaign.

    Pre-flight is re-run here rather than trusted from the caller: the checklist
    the rep looked at may be minutes old, and an account can be disqualified in
    between.
    """
    checks = await preflight.run(session, campaign_id)
    if not checks.passed:
        raise PreflightFailedError(checks)

    campaign = await session.get(OutreachCampaign, campaign_id)
    shape = (
        await session.get(CadenceShape, campaign.cadence_shape_id)
        if campaign.cadence_shape_id
        else None
    )
    outcome = ExecutionOutcome(campaign_id=campaign_id)

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

    for sequence in sequences:
        verdict = await check_interlock(session, sequence)
        if not verdict.proceed:
            outcome.skipped[str(sequence.id)] = verdict.reason or "skipped"
            session.add(
                ExecutionRecord(
                    sequence_id=sequence.id, status="skipped",
                    skip_reason=verdict.reason, action="enrol",
                    interlock_snapshot=verdict.snapshot,
                )
            )
            continue

        from app.services.promotion import person_of

        contact, _ = await person_of(session, sequence)
        touches = list(
            (
                await session.execute(
                    select(Touch).where(Touch.sequence_id == sequence.id)
                )
            ).scalars()
        )
        drafts = {
            d.touch_id: d
            for d in (
                await session.execute(
                    select(Draft).where(
                        Draft.touch_id.in_([t.id for t in touches]),
                        Draft.is_current.is_(True),
                    )
                )
            ).scalars()
        }

        try:
            lead = await lgm.upsert_lead(
                email=contact.email,
                linkedin_url=contact.linkedin_url,
                attributes=_attributes_for(touches, drafts, shape),
                # The audience is the enrolment: LGM campaigns read one, and
                # there is no call that adds a lead to a campaign directly.
                audience=shape.lgm_audience_name if shape else None,
                person=await _person_for(session, contact),
            )
            ref = await lgm.enrol(
                lead_id=lead.lead_id,
                lgm_campaign_id=shape.lgm_campaign_id if shape else "",
            )
        except LgmError as exc:
            # One lead failing must not cost the campaign — the rest are still
            # approved and still correct.
            log.warning("execution.enrol_failed sequence=%s err=%s", sequence.id, exc)
            outcome.failed[str(sequence.id)] = str(exc)
            session.add(
                ExecutionRecord(
                    sequence_id=sequence.id, status="failed",
                    error=str(exc), action="enrol",
                )
            )
            continue

        written_at = datetime.now(UTC)
        for touch in touches:
            touch.content_sync_status = "written"
            touch.content_written_at = written_at

        if ref.endswith(":awaiting_launch"):
            outcome.awaiting_launch = True
        sequence.status = "executing"
        sequence.lgm_lead_id = lead.lead_id
        sequence.lgm_campaign_id = shape.lgm_campaign_id if shape else None
        session.add(
            ExecutionRecord(
                sequence_id=sequence.id, status="sent", action="enrol",
                provider_ref=ref, sent_at=written_at,
                interlock_snapshot=verdict.snapshot,
            )
        )
        outcome.enrolled.append(sequence.id)

    if outcome.any_enrolled:
        campaign.status = "executing"
        campaign.started_at = datetime.now(UTC)
        outcome.audience = shape.lgm_audience_name if shape else None
        if outcome.awaiting_launch:
            log.info(
                "execution.awaiting_launch campaign=%s audience=%r leads=%d",
                campaign_id, outcome.audience, len(outcome.enrolled),
            )
    await session.flush()
    return outcome


# ---------------------------------------------------------------------------
# stop paths
# ---------------------------------------------------------------------------
async def stop_sequence(
    session: AsyncSession,
    *,
    sequence_id: uuid.UUID,
    lgm: LgmAdapter,
    reason: str = "manual",
) -> OutreachSequence:
    """Halt one contact's remaining touches.

    The local state is written **whether or not** the provider call succeeds. A
    stop that silently did not happen is far worse than one that errored: the
    sequence would keep sending while the UI showed it stopped.
    """
    sequence = await session.get(OutreachSequence, sequence_id)
    if sequence is None:
        raise ValueError(f"sequence {sequence_id} not found")

    error: str | None = None
    if sequence.lgm_lead_id and sequence.lgm_campaign_id:
        try:
            await lgm.stop_lead(
                lead_id=sequence.lgm_lead_id, lgm_campaign_id=sequence.lgm_campaign_id
            )
        except LgmError as exc:
            error = str(exc)
            log.warning("execution.stop_failed sequence=%s err=%s", sequence_id, exc)

    sequence.status = "stopped"
    for touch in (
        await session.execute(
            select(Touch).where(
                Touch.sequence_id == sequence_id, Touch.status == "pending"
            )
        )
    ).scalars():
        touch.status = "skipped"
        touch.stop_reason = reason

    session.add(
        ExecutionRecord(
            sequence_id=sequence_id,
            status="failed" if error else "skipped",
            skip_reason=None if error else "sequence_stopped",
            error=error,
            action=f"stop:{reason}",
        )
    )
    await session.flush()
    return sequence


async def stop_campaign(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    lgm: LgmAdapter,
    reason: str = "manual",
) -> int:
    """Stop every live sequence in a campaign, then the campaign itself."""
    campaign = await session.get(OutreachCampaign, campaign_id)
    if campaign is None:
        raise ValueError(f"campaign {campaign_id} not found")

    live = list(
        (
            await session.execute(
                select(OutreachSequence).where(
                    OutreachSequence.campaign_id == campaign_id,
                    OutreachSequence.status.in_(
                        ("pending_approval", "approved", "executing", "paused")
                    ),
                )
            )
        ).scalars()
    )
    for sequence in live:
        await stop_sequence(session, sequence_id=sequence.id, lgm=lgm, reason=reason)

    shape = (
        await session.get(CadenceShape, campaign.cadence_shape_id)
        if campaign.cadence_shape_id
        else None
    )
    if shape:
        try:
            await lgm.stop_campaign(shape.lgm_campaign_id)
        except LgmError as exc:
            log.warning("execution.stop_campaign_failed campaign=%s err=%s", campaign_id, exc)

    campaign.status = "cancelled"
    await session.flush()
    return len(live)


# ---------------------------------------------------------------------------
async def assert_editable(session: AsyncSession, sequence_id: uuid.UUID) -> None:
    """Raise if content is frozen. The 409 path for any draft edit.

    Frozen means enrolled: LGM holds the copy, and changing our row would make
    the UI and the recipient disagree with nobody able to tell.
    """
    sequence = await session.get(OutreachSequence, sequence_id)
    if sequence is None:
        raise ValueError(f"sequence {sequence_id} not found")

    # `approved` is not enrolled: an edit there sends it back for approval
    # (`campaign_drafts`), it does not diverge from anything LGM holds.
    if sequence.status not in ("draft", "pending_eval", "pending_approval", "approved"):
        raise ContentFrozenError(
            f"sequence is {sequence.status!r}; content is frozen on the LGM lead. "
            "Stop the sequence and re-enrol to change the words"
        )

    written = (
        await session.execute(
            select(Touch).where(
                Touch.sequence_id == sequence_id, Touch.content_sync_status == "written"
            )
        )
    ).scalars().first()
    if written is not None:
        raise ContentFrozenError(
            "this sequence's content has already been written to the LGM lead"
        )
