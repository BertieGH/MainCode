"""Cadence drafts for a campaign's people: write, edit, save for approval.

Each person's sequence runs on the cadence chosen at promotion. Drafting fills
that registered shape — touch count and timing belong to LGM — in one model call
per person, from their strategy. A rep may then edit any touch; the edit is
saved as a new version (`rep_edit`), never over the model's words.

A sequence moves `draft` → `pending_approval` when the rep **saves** it for
approval, and to `approved` when approved individually or through the sample.
Any change after saving — an edit or a rewrite — returns it to `draft`, so an
approval never covers words nobody approved. Once content has been written to
the LGM lead nothing changes: stop and re-enrol is the only lever.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, Contact
from app.models.campaign import CadenceShape, OutreachCampaign, OutreachSequence
from app.models.content import Draft, Touch
from app.models.governance import Approval
from app.schemas.draft import DraftSet, TouchDraft
from app.services import context as context_service
from app.services import drafting
from app.services.promotion import person_of

log = logging.getLogger(__name__)

#: Saved for approval, or approved.
READY = ("pending_approval", "approved")
#: An approval counts only while the sequence is in one of these.
APPROVED = ("approved", "executing", "paused", "completed")
#: Enrolled or finished — the words can no longer change.
ENROLLED = ("executing", "paused", "completed", "stopped", "cancelled")

STATE_LABELS = {
    "strategy_needed": "strategy needed",
    "not_drafted": "not drafted",
    "drafted": "drafted — not saved",
    "saved": "saved for approval",
    "approved": "approved",
    "enrolled": "enrolled",
    "withdrawn": "withdrawn",
}


class DraftingRefusedError(RuntimeError):
    """Drafts cannot be written or changed for this person, with the reason."""


async def repoint_to_shape(session: AsyncSession, shape: CadenceShape) -> dict:
    """Re-point every unsent touch at the slot its step reads *now*.

    A touch's `lgm_attribute` is not a decision anybody made: it is a copy of
    the shape's mapping taken when the arc was drafted. When a template moves
    in LGM and the registration is re-read, that copy is stale — and stale here
    means step 1's email body addressed to the slot step 2's LinkedIn message
    reads. The words would send, to the right person, in the wrong message.

    So it follows the shape, for everything that has not been written to LGM
    yet. Enrolled sequences are left exactly as they are: LGM already holds
    their copy in the old slot, and changing our row would describe a sequence
    that is not the one running (invariant 4 — content is frozen at enrolment).

    Returns what moved, so a caller can say so rather than fixing things in
    silence.
    """
    from app.models.content import Touch
    from app.services.promotion import WITHDRAWABLE

    body_map = shape.attribute_map or {}
    subject_map = shape.subject_attribute_map or {}

    rows = (
        await session.execute(
            select(Touch, OutreachSequence)
            .join(OutreachSequence, OutreachSequence.id == Touch.sequence_id)
            .where(
                OutreachSequence.cadence_shape_id == shape.id,
                OutreachSequence.status.in_(WITHDRAWABLE),
            )
        )
    ).all()

    moved: list[str] = []
    frozen = 0
    for touch, _sequence in rows:
        wanted = body_map.get(str(touch.step_no))
        if wanted and touch.lgm_attribute != wanted:
            moved.append(f"step {touch.step_no}: {touch.lgm_attribute} → {wanted}")
            touch.lgm_attribute = wanted
        # A subject the step can no longer carry goes back to LGM's own. The
        # words stay on the draft; they simply stop claiming a slot that would
        # not show them.
        if touch.subject_source == "custom_attribute" and not subject_map.get(str(touch.step_no)):
            touch.subject_source = "lgm_template"
            moved.append(f"step {touch.step_no}: subject back to LGM's own")

    still_enrolled = await session.scalar(
        select(func.count())
        .select_from(OutreachSequence)
        .where(
            OutreachSequence.cadence_shape_id == shape.id,
            OutreachSequence.status.not_in(WITHDRAWABLE),
            OutreachSequence.status != "cancelled",
        )
    )
    frozen = still_enrolled or 0
    if moved:
        await session.flush()
        log.info(
            "campaign_drafts.repointed shape=%s moved=%d frozen=%d",
            shape.key, len(moved), frozen,
        )
    return {"moved": moved, "frozen": frozen}


async def shape_of(session: AsyncSession, sequence: OutreachSequence) -> CadenceShape | None:
    """The cadence this person's copy is written for.

    The campaign's, not the sequence's, whenever the campaign has one: the
    campaign is what enrols, and drafting for a different number of steps than
    the sequence will actually send is how touches 5 and 6 go out empty.
    """
    campaign = (
        await session.get(OutreachCampaign, sequence.campaign_id)
        if sequence.campaign_id
        else None
    )
    shape_id = (campaign.cadence_shape_id if campaign else None) or sequence.cadence_shape_id
    return await session.get(CadenceShape, shape_id) if shape_id else None


async def arc_of(session: AsyncSession, sequence_id) -> list[tuple[Touch, Draft | None]]:
    touches = list(
        (
            await session.execute(
                select(Touch).where(Touch.sequence_id == sequence_id).order_by(Touch.step_no)
            )
        ).scalars()
    )
    if not touches:
        return []
    drafts = {
        d.touch_id: d
        for d in (
            await session.execute(
                select(Draft).where(
                    Draft.touch_id.in_([t.id for t in touches]), Draft.is_current.is_(True)
                )
            )
        ).scalars()
    }
    return [(t, drafts.get(t.id)) for t in touches]


def state_of(sequence: OutreachSequence, has_strategy: bool, arc: list) -> str:
    if sequence.status == "cancelled":
        return "withdrawn"
    if sequence.status in ENROLLED:
        return "enrolled"
    if not has_strategy:
        return "strategy_needed"
    if not arc:
        return "not_drafted"
    if sequence.status == "approved":
        return "approved"
    if sequence.status == "pending_approval":
        return "saved"
    return "drafted"


def edited(arc: list) -> bool:
    return any(d is not None and d.generated_as == "rep_edit" for _, d in arc)


async def approved_ids(session: AsyncSession, sequences: list[OutreachSequence]) -> set[uuid.UUID]:
    """Sequences whose approval still counts.

    An approval row is kept forever, but it covers the words as they were: a
    sequence edited since has returned to `draft`, and one with no touches was
    never approvable. So the row counts only while the sequence is approved (or
    beyond) and has content.
    """
    candidates = [s.id for s in sequences if s.status in APPROVED]
    if not candidates:
        return set()
    with_rows = set(
        (
            await session.execute(
                select(Approval.subject_id).where(
                    Approval.subject_type == "outreach_sequence",
                    Approval.subject_id.in_(candidates),
                    Approval.decision == "approve",
                )
            )
        ).scalars()
    )
    with_content = set(
        (
            await session.execute(
                select(Touch.sequence_id).where(Touch.sequence_id.in_(candidates)).distinct()
            )
        ).scalars()
    )
    return with_rows & with_content


def _refuse_if_withdrawn(sequence: OutreachSequence, name: str) -> None:
    """A withdrawn person is out of the campaign until somebody puts them back.

    Checked before the frozen-content refusal: both stop the write, and only
    one of them tells a rep what to do next.
    """
    if sequence.status == "cancelled":
        raise DraftingRefusedError(
            f"{name} was withdrawn from this campaign ({sequence.withdraw_reason}) — "
            "put them back first"
        )


def _refuse_if_enrolled(sequence: OutreachSequence, arc: list) -> None:
    if sequence.status in ENROLLED or any(t.content_sync_status == "written" for t, _ in arc):
        raise DraftingRefusedError(
            "content is frozen at enrolment — LGM reads the words from the lead. "
            "Stop the sequence and re-enrol to change them"
        )


def _reopen(sequence: OutreachSequence) -> None:
    """A change after saving needs saving — and approving — again."""
    if sequence.status in READY:
        sequence.status = "draft"


async def rows(session: AsyncSession, campaign: OutreachCampaign) -> list[dict]:
    """Every person in the campaign with their cadence and where their drafts stand."""
    sequences = (
        await session.execute(
            select(OutreachSequence, Contact, Account)
            .join(Contact, Contact.id == OutreachSequence.contact_id)
            .join(Account, Account.id == Contact.account_id)
            .where(OutreachSequence.campaign_id == campaign.id)
            .order_by(Account.name, Contact.full_name)
        )
    ).all()
    from app.services import icp_scores
    from app.services.promotion import queue_gate

    minimum = await queue_gate(session)
    gates: dict = {}
    out = []
    for sequence, contact, account in sequences:
        if account.id not in gates:
            gates[account.id] = await icp_scores.gate_for(
                session, account.id, campaign.icp_profile_id, min_band=minimum
            )
        _, thread = await person_of(session, sequence)
        shape = await shape_of(session, sequence)
        arc = await arc_of(session, sequence.id)
        state = state_of(sequence, thread is not None, arc)
        out.append({
            "sequence_id": sequence.id,
            "contact_id": contact.id,
            "full_name": contact.full_name,
            "title": contact.title,
            "account_id": account.id,
            "account_name": account.name,
            "cadence_key": shape.key if shape else None,
            "cadence_label": shape.label if shape else None,
            "cadence_touches": shape.touch_count if shape else None,
            "cadence_days": shape.span_days if shape else None,
            "has_strategy": thread is not None,
            "touch_count": len(arc),
            "edited": edited(arc),
            "state": state,
            "state_label": STATE_LABELS[state],
            "status": sequence.status,
            "withdraw_reason": sequence.withdraw_reason,
            **gates[account.id],
        })
    return out


async def _thread_payload(session: AsyncSession, thread) -> dict:
    """The argument drafting writes from: the selected angle (`docs/18`).

    The thread's fields mirror whichever angle is selected — the top-ranked
    one, or the one a rep picked. Added here: the angle's name, the approved
    proof it cites (the full text, since drafting may only use approved
    claims — invariant 8) and the company read every angle hangs off.

    No channel list: the cadence's channels are fixed by LGM and arrive as
    `cadence`; a second, invented sequence here only gave the model two
    answers to reconcile.
    """
    from app.models.config import ProofPoint
    from app.models.strategy import Strategy, StrategyAngle

    angle = (
        await session.execute(
            select(StrategyAngle).where(
                StrategyAngle.thread_id == thread.id, StrategyAngle.is_selected.is_(True)
            )
        )
    ).scalar_one_or_none()
    strategy = await session.get(Strategy, thread.strategy_id)
    proof = []
    if angle is not None and angle.proof_point_ids:
        ids = [uuid.UUID(str(p)) for p in angle.proof_point_ids]
        proof = [
            {"id": str(p.id), "title": p.title, "body": p.body, "metrics": p.metrics or {}}
            for p in (
                await session.execute(
                    select(ProofPoint)
                    .where(ProofPoint.id.in_(ids), ProofPoint.is_approved.is_(True))
                    .order_by(ProofPoint.title)
                )
            ).scalars()
        ]
    return {
        **({"angle": angle.angle} if angle is not None else {}),
        "problem_hypothesis": thread.problem_hypothesis,
        "why_now": thread.trigger_summary,
        "trigger_signal_ids": list(thread.trigger_signal_ids or []),
        "positioning": thread.positioning,
        "cta": thread.cta,
        "avoid_list": list(thread.avoid_list or []),
        "proof_to_use": proof,
        **({"account_angle": strategy.account_angle} if strategy and strategy.account_angle else {}),
        "built_without_a_live_signal": bool(thread.without_live_trigger),
    }


async def write(session: AsyncSession, sequence: OutreachSequence, *, draft=None) -> int:
    """Write every touch for one person, in one model call. Returns the touch count.

    A first write stores the arc; a rewrite adds a version to each touch. Either
    way the sequence is back in `draft` until the rep saves it.
    """
    from app.services import stages

    contact, thread = await person_of(session, sequence)
    if contact is None:
        raise DraftingRefusedError("this sequence names nobody")
    if thread is None:
        raise DraftingRefusedError(f"no strategy yet for {contact.full_name} — build it first")
    shape = await shape_of(session, sequence)
    if shape is None:
        raise DraftingRefusedError(f"no cadence was selected for {contact.full_name}")
    arc = await arc_of(session, sequence.id)
    _refuse_if_withdrawn(sequence, contact.full_name)
    _refuse_if_enrolled(sequence, arc)

    account = await session.get(Account, contact.account_id)
    signals = await context_service.live_signals(session, account.id)
    from app.services.lgm import ATTRIBUTE_BUDGET

    cadence = {
        "key": shape.key,
        "label": shape.label,
        "touch_count": shape.touch_count,
        # Absent unless this shape predates timing belonging to LGM. Sending
        # `null` would invite the model to fill it in; saying so in words is
        # what stops it proposing a schedule nobody here controls.
        **({"span_days": shape.span_days} if shape.span_days is not None else {}),
        **({"durable_from_step": shape.durable_from_step} if shape.durable_from_step else {}),
        "timing": (
            "La Growth Machine schedules every step and does not publish the delays. "
            "Write the words for each step in order; do not propose days, and do not "
            "write copy that depends on how long ago the last step went out."
        ),
        "channels": list(shape.lgm_channels or []),
        # Per step, not a count. A count said "you may write four subjects"
        # without saying where one could appear, so subjects were written for
        # LinkedIn steps that have no subject line, and for email steps whose
        # subject template is fixed copy. Either way the words vanished.
        "steps": [
            {
                "step": n,
                "channel": (shape.step_channels or {}).get(str(n), "unknown"),
                # What this step is called in LGM, where its intent lives.
                # "Not Accepted - Email" and "Accepted - DM" are two branches
                # of one moment, not step one and step two — so a touch that
                # reads as a follow-up is wrong whenever the other never sent.
                **(
                    {"named_in_lgm": (shape.step_meta or {}).get(str(n), {}).get("name")}
                    if (shape.step_meta or {}).get(str(n), {}).get("name")
                    else {}
                ),
                "subject": (
                    "allowed"
                    if (shape.subject_attribute_map or {}).get(str(n))
                    else "not available — this step shows LGM's own subject, or has none"
                ),
            }
            for n in range(1, shape.touch_count + 1)
        ],
        "attribute_budget": ATTRIBUTE_BUDGET,
    }
    if draft is None:
        async def draft(**kwargs):
            return await stages.draft_arc(session, **kwargs)

    # A draft is the one campaign call that is also about one person, so it
    # carries both — the campaign the bill belongs to and who it was for.
    with stages.attributed(
        account_id=account.id,
        contact_id=contact.id,
        campaign_id=sequence.campaign_id,
        scope="campaign",
    ):
        result = await draft(
            account=account, contact=contact, thread=await _thread_payload(session, thread), shape=cadence, signals=signals,
        )
    draft_set: DraftSet = result.parsed
    model = getattr(result, "model", "") or None

    _reopen(sequence)
    if arc and len(arc) != shape.touch_count:
        # The cadence changed under them — a campaign moved from four steps to
        # six, say. Their touches describe a sequence that will never run, and
        # versioning copy onto steps that no longer exist would leave the extra
        # steps of the real cadence empty. Nothing has been written to LGM
        # (`_refuse_if_enrolled` guarantees it), so the old arc is replaced
        # wholesale rather than half-updated.
        log.info(
            "campaign_drafts.recadenced sequence=%s from=%d to=%d",
            sequence.id, len(arc), shape.touch_count,
        )
        for touch, _ in arc:
            await session.delete(touch)
        await session.flush()
        arc = []

    if not arc:
        await drafting.store_arc(session, sequence=sequence, draft_set=draft_set, shape=shape, model=model or "unknown")
        return len(draft_set.touches)

    problems = await drafting.validate_arc(session, draft_set, shape=shape)
    if problems:
        raise drafting.ArcRejectedError(problems)
    by_step = draft_set.by_step()
    if set(by_step) != {t.step_no for t, _ in arc}:
        raise DraftingRefusedError("the rewrite does not match the cadence's steps")
    attribute_map = shape.attribute_map or {}
    for touch, current in arc:
        spec = by_step[touch.step_no]
        touch.day_offset, touch.channel, touch.purpose = spec.day_offset, spec.channel, spec.purpose
        touch.subject_source = "custom_attribute" if spec.subject else "lgm_template"
        # Re-pointed on every rewrite, not only on a first draft. This path
        # updated the words and left the slot, so a shape corrected after a
        # template moved in LGM kept sending step 1's body to step 2's
        # attribute however many times it was redrafted.
        touch.lgm_attribute = attribute_map.get(str(touch.step_no), touch.lgm_attribute)
        await _add_version(
            session, touch, current, subject=spec.subject, body=spec.body,
            signal_dependence=spec.signal_dependence, cited_signal_ids=list(spec.cited_signal_ids),
            cited_proof_point_ids=list(spec.cited_proof_point_ids), generated_as="regeneration",
            reason="rewritten by AI at the rep's request", model=model,
        )
    return len(draft_set.touches)


async def _add_version(
    session: AsyncSession, touch: Touch, current: Draft | None, *, subject, body, signal_dependence,
    cited_signal_ids, cited_proof_point_ids, generated_as, reason=None, model=None,
) -> Draft:
    version = 1
    if current is not None:
        # Cleared first: exactly one current draft per touch.
        current.is_current = False
        version = current.version + 1
        await session.flush()
    row = Draft(
        touch_id=touch.id, version=version, subject=subject, body=body,
        cited_signal_ids=cited_signal_ids, cited_proof_point_ids=cited_proof_point_ids,
        signal_dependence=signal_dependence, generated_as=generated_as,
        regenerated_reason=reason, model=model, is_current=True,
    )
    session.add(row)
    await session.flush()
    return row


async def edit_touch(
    session: AsyncSession, sequence: OutreachSequence, step_no: int, *, subject: str | None, body: str
) -> Draft:
    """Save the rep's wording for one touch as a new version."""
    arc = await arc_of(session, sequence.id)
    _refuse_if_enrolled(sequence, arc)
    found = next(((t, d) for t, d in arc if t.step_no == step_no), None)
    if found is None:
        raise DraftingRefusedError(f"step {step_no} has not been drafted")
    touch, current = found
    body = (body or "").strip()
    if not body:
        raise DraftingRefusedError("a touch needs a body")
    subject = (subject or "").strip() or None

    # The whole arc, with this edit, must still fit the cadence and the lead's
    # attribute budget — a new subject line spends an attribute.
    proposed = DraftSet(touches=[
        TouchDraft(
            step_no=t.step_no, day_offset=t.day_offset, channel=t.channel, purpose=t.purpose or "—",
            subject=subject if t.step_no == step_no else (d.subject if d else None),
            body=body if t.step_no == step_no else (d.body if d and d.body else "—"),
            signal_dependence=d.signal_dependence if d else "durable",
            cited_signal_ids=list(d.cited_signal_ids or []) if d else [],
            cited_proof_point_ids=list(d.cited_proof_point_ids or []) if d else [],
        )
        for t, d in arc
    ])
    problems = await drafting.validate_arc(session, proposed, shape=await shape_of(session, sequence))
    if problems:
        raise drafting.ArcRejectedError(problems)

    touch.subject_source = "custom_attribute" if subject else "lgm_template"
    row = await _add_version(
        session, touch, current, subject=subject, body=body,
        signal_dependence=current.signal_dependence if current else "durable",
        cited_signal_ids=list(current.cited_signal_ids or []) if current else [],
        cited_proof_point_ids=list(current.cited_proof_point_ids or []) if current else [],
        generated_as="rep_edit",
    )
    _reopen(sequence)
    return row


async def save(session: AsyncSession, sequence: OutreachSequence) -> None:
    """Save a person's drafts for approval.

    Raises `IntegrityError` from the enrolment lock when the person already has
    a live sequence in another campaign — the caller rolls back and says so.
    """
    contact, thread = await person_of(session, sequence)
    arc = await arc_of(session, sequence.id)
    name = contact.full_name if contact else "this person"
    _refuse_if_withdrawn(sequence, name)
    _refuse_if_enrolled(sequence, arc)
    if thread is None:
        raise DraftingRefusedError(f"no strategy yet for {name}")
    if not arc or any(d is None for _, d in arc):
        raise DraftingRefusedError(f"{name}'s cadence has not been drafted")
    # The arc has to fit the cadence that will actually send it. Drafts written
    # for four touches and enrolled into a six-step campaign leave steps 5 and
    # 6 sending whatever the lead already held — and an approval spent reading
    # four touches would have approved a sequence nobody has seen in full.
    shape = await shape_of(session, sequence)
    if shape is not None and len(arc) != shape.touch_count:
        raise DraftingRefusedError(
            f"{name} has {len(arc)} touches drafted, but this campaign runs {shape.key} "
            f"({shape.touch_count} steps) — write their drafts again"
        )
    if sequence.status == "draft":
        sequence.status = "pending_approval"
        await session.flush()


async def versions(session: AsyncSession, sequence_id, step_no: int) -> list[Draft]:
    touch = (
        await session.execute(
            select(Touch).where(Touch.sequence_id == sequence_id, Touch.step_no == step_no)
        )
    ).scalar_one_or_none()
    if touch is None:
        return []
    return list(
        (
            await session.execute(
                select(Draft).where(Draft.touch_id == touch.id).order_by(Draft.version.desc())
            )
        ).scalars()
    )
