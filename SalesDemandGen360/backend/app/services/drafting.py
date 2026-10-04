"""Arc validation and storage.

Three guards, each closing a failure a rep could not catch at approval:

* **Durability banding.** A late touch anchored to a dated signal reads
  perfectly on day 0 and reads as automation on day 15. `docs/06` bands the arc
  and forbids `dated` copy in the late third.
* **Attribute budget.** LGM allows ten custom attributes per lead, globally.
  Exceeding it does not error there — the overflow is silently dropped, and the
  touch sends whatever the lead already held.
* **Approved proof points only.** Blocked at generation rather than caught at
  review, because a claim that reaches the model can be drafted with.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign import CadenceShape, OutreachSequence
from app.models.config import ProofPoint
from app.models.content import Draft, Touch
from app.schemas.draft import ArcProblem, DraftSet
from app.services.lgm import ATTRIBUTE_MAX_CHARS

#: LGM's per-lead cap, global across campaigns. Twenty, confirmed live.
ATTRIBUTE_BUDGET = 20

Band = str  # "early" | "middle" | "late"


def band_for_step(step_no: int, touch_count: int) -> Band:
    """Which third of the arc a step sits in.

    Thirds rather than fixed step numbers, because a 4-touch nurture and an
    8-touch enterprise cadence have different middles. Hardcoding "5–6 is late"
    would leave touch 8 of an enterprise sequence unguarded.
    """
    if touch_count <= 1:
        return "early"
    position = (step_no - 1) / (touch_count - 1)
    if position <= 1 / 3:
        return "early"
    if position <= 2 / 3:
        return "middle"
    return "late"


#: What each band may anchor to when nothing datable is cited. The thirds are
#: a fallback now, not the rule: where a touch names its signals we can ask the
#: real question — is this still true on the day it sends?
PERMITTED: dict[Band, set[str]] = {
    "early": {"dated", "implied", "durable"},
    "middle": {"dated", "implied", "durable"},
    "late": {"dated", "implied", "durable"},
}


def attributes_needed(draft_set: DraftSet) -> int:
    """How many custom attributes this arc consumes on the lead.

    One per body, plus one per touch that needs its own subject line. Subjects
    default to LGM-native precisely because the budget is small.
    """
    bodies = len(draft_set.touches)
    subjects = sum(1 for t in draft_set.touches if t.subject)
    return bodies + subjects


async def _signal_expiries(session: AsyncSession, ids: set[str]) -> dict[str, date | None]:
    """When each cited signal stops being true. Ids nothing matches are absent.

    A superseded signal is dated to `date.min`: it is no longer the current
    reading of that fact, so it cannot carry a claim stated as current however
    long its own expiry runs.
    """
    from app.models.signal import Signal

    wanted: list[uuid.UUID] = []
    for value in ids:
        try:
            wanted.append(uuid.UUID(str(value)))
        except (ValueError, AttributeError, TypeError):
            continue
    if not wanted:
        return {}
    rows = await session.execute(
        select(Signal.id, Signal.expires_at, Signal.superseded_by).where(Signal.id.in_(wanted))
    )
    return {
        str(sid): (expires if superseded is None else date.min)
        for sid, expires, superseded in rows.all()
    }


async def validate_arc(
    session: AsyncSession,
    draft_set: DraftSet,
    *,
    shape: CadenceShape | None = None,
    today: date | None = None,
) -> list[ArcProblem]:
    """Every reason this arc cannot be stored. Empty means it is sound.

    All problems are returned rather than the first, so a regeneration fixes
    the whole set instead of surfacing them one round trip at a time.
    """
    problems: list[ArcProblem] = []
    count = len(draft_set.touches)

    # --- is a dated claim true, and re-checkable? ---
    #
    # This rule has narrowed twice. It began as a ban on `dated` past the first
    # third of an arc — a guess about expiry. It became an exact comparison of
    # each signal's expiry against the day that touch would send. That was
    # still wrong, for a reason that only showed up against a live account:
    # **we do not know the days.** LGM schedules its own steps and exposes the
    # schedule nowhere, so every offset in that comparison was either typed by
    # a rep or invented by the model.
    #
    # What is left is the part that was ever ours to check: the signal has to
    # exist, and it has to be live on the day the copy is written. Expiry after
    # that is LGM's window to manage, and the pre-send freshness check is what
    # actually stops a stale claim leaving — it runs against the real date,
    # with no guess in it at all.
    dated = [t for t in draft_set.touches if t.signal_dependence == "dated"]
    expiries = await _signal_expiries(session, {s for t in dated for s in t.cited_signal_ids})
    start = today or date.today()
    for touch in sorted(dated, key=lambda t: t.step_no):
        # Only a volunteered offset gives a send date. Without one the claim is
        # judged as of today, which is when it is being written.
        sends_on = start + timedelta(days=touch.day_offset) if touch.day_offset is not None else start
        for cited in touch.cited_signal_ids:
            if cited not in expiries:
                problems.append(
                    ArcProblem(
                        step_no=touch.step_no,
                        reason="unknown_signal",
                        detail=(
                            f"step {touch.step_no} states {cited} as current fact, and no such "
                            "signal exists — a dated claim has to be re-checkable before it sends"
                        ),
                    )
                )
                continue
            expires = expiries[cited]
            if expires is None or expires >= sends_on:
                continue
            # Two different failures, and a rep fixes them differently. A
            # signal already dead on the day of writing means the claim is
            # simply untrue and the copy has to change. One that dies between
            # writing and sending can only be known where a day was
            # volunteered, which since timing became LGM's is nothing new.
            if expires < start:
                problems.append(
                    ArcProblem(
                        step_no=touch.step_no,
                        reason="signal_expired",
                        detail=(
                            f"step {touch.step_no} of {count} states a signal as current fact, but "
                            f"it expired {expires:%d %b %Y} and today is {start:%d %b %Y} — cite "
                            "something still true, or write it as 'implied' or 'durable'"
                        ),
                    )
                )
            else:
                problems.append(
                    ArcProblem(
                        step_no=touch.step_no,
                        reason="signal_expires_before_it_sends",
                        detail=(
                            f"step {touch.step_no} of {count} states a signal as current fact and "
                            f"sends on day {touch.day_offset} ({sends_on:%d %b %Y}), but that "
                            f"signal expires {expires:%d %b %Y} — write it as 'implied' or "
                            "'durable', or make the claim earlier in the arc"
                        ),
                    )
                )

    # --- shape agreement ---
    if shape is not None:
        if count != shape.touch_count:
            problems.append(
                ArcProblem(
                    step_no=None,
                    reason="touch_count_mismatch",
                    detail=(
                        f"the arc has {count} touches but shape {shape.key!r} registers "
                        f"{shape.touch_count}; LGM runs the shape, so the extra copy would "
                        "never send and a missing one would leave a step empty"
                    ),
                )
            )
        # A subject can only appear where that step's subject template in LGM
        # names an attribute. Written anywhere else it is not a worse subject,
        # it is one nobody will ever see — and before this it was dropped in
        # silence at execution, so the arc a rep approved and the message that
        # sent were different things.
        subject_map = shape.subject_attribute_map or {}
        for touch in draft_set.touches:
            if not touch.subject:
                continue
            if not subject_map.get(str(touch.step_no)):
                problems.append(
                    ArcProblem(
                        step_no=touch.step_no,
                        reason="subject_has_nowhere_to_go",
                        detail=(
                            f"step {touch.step_no} has a written subject line, but that step in "
                            f"{shape.key!r} shows La Growth Machine's own subject — or none at "
                            "all, on LinkedIn. Leave it empty, or add a "
                            "{{customAttributeN}} to that step's subject in LGM"
                        ),
                    )
                )

        # Only checkable where both numbers exist, which since timing became
        # LGM's means only for arcs and shapes recorded before it did. Nothing
        # new has a span to disagree with.
        offsets = [t.day_offset for t in draft_set.touches if t.day_offset is not None]
        if shape.span_days is not None and offsets:
            longest = max(offsets)
            if longest > shape.span_days:
                problems.append(
                    ArcProblem(
                        step_no=None,
                        reason="span_mismatch",
                        detail=(
                            f"the last touch is day {longest} but shape {shape.key!r} spans "
                            f"{shape.span_days} days"
                        ),
                    )
                )

    # --- what fits in one attribute ---
    #
    # LGM stores 1000 characters per custom attribute and truncates the rest.
    # A truncated touch still sends, mid-sentence, so it is refused here rather
    # than discovered by a recipient.
    for touch in draft_set.touches:
        for what, value in (("body", touch.body), ("subject", touch.subject or "")):
            if len(value) > ATTRIBUTE_MAX_CHARS:
                problems.append(
                    ArcProblem(
                        step_no=touch.step_no,
                        reason="attribute_too_long",
                        detail=(
                            f"step {touch.step_no}'s {what} is {len(value)} characters; La Growth "
                            f"Machine stores {ATTRIBUTE_MAX_CHARS} per attribute and silently "
                            "truncates the rest"
                        ),
                    )
                )

    # --- attribute budget ---
    needed = attributes_needed(draft_set)
    subjects = sum(1 for t in draft_set.touches if t.subject)
    allowed = max(ATTRIBUTE_BUDGET - count, 0)
    if needed > ATTRIBUTE_BUDGET:
        problems.append(
            ArcProblem(
                step_no=None,
                reason="attribute_budget",
                detail=(
                    f"this arc needs {needed} custom attributes but LGM allows "
                    f"{ATTRIBUTE_BUDGET} per lead: {count} bodies and {subjects} custom "
                    f"subject lines. With {count} touches at most {allowed} of them may carry "
                    "their own subject — the rest use the campaign's. The overflow is dropped "
                    "silently and those touches would send whatever the lead already held"
                ),
            )
        )

    # --- proof points must be approved ---
    cited: set[uuid.UUID] = set()
    for touch in draft_set.touches:
        for pid in touch.cited_proof_point_ids:
            try:
                cited.add(uuid.UUID(str(pid)))
            except ValueError:
                problems.append(
                    ArcProblem(
                        step_no=touch.step_no,
                        reason="unknown_proof_point",
                        detail=f"{pid!r} is not a proof point id",
                    )
                )
    if cited:
        approved = set(
            (
                await session.execute(
                    select(ProofPoint.id).where(
                        ProofPoint.id.in_(cited), ProofPoint.is_approved.is_(True)
                    )
                )
            ).scalars()
        )
        for touch in draft_set.touches:
            bad = [
                p for p in touch.cited_proof_point_ids
                if _as_uuid(p) is not None and _as_uuid(p) not in approved
            ]
            if bad:
                problems.append(
                    ArcProblem(
                        step_no=touch.step_no,
                        reason="unapproved_proof_point",
                        detail=(
                            f"step {touch.step_no} cites {bad}, which is not an approved "
                            "proof point — only approved claims may reach a prospect"
                        ),
                    )
                )

    return problems


def _as_uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


class ArcRejectedError(ValueError):
    """The arc failed validation and was not stored."""

    def __init__(self, problems: list[ArcProblem]):
        self.problems = problems
        super().__init__("; ".join(f"{p.reason}: {p.detail}" for p in problems))


@dataclass
class StoredArc:
    sequence_id: uuid.UUID
    touch_ids: list[uuid.UUID]
    draft_ids: list[uuid.UUID]


async def store_arc(
    session: AsyncSession,
    *,
    sequence: OutreachSequence,
    draft_set: DraftSet,
    shape: CadenceShape | None = None,
    model: str = "claude-opus-5",
    prompt_version: str | None = None,
) -> StoredArc:
    """Write every touch and its draft together, or write nothing.

    One pass, matching how the arc was generated. A half-stored sequence would
    be approvable in the UI while missing the touches that justify it.
    """
    if sequence.status not in ("draft", "pending_eval"):
        # Content is frozen once a sequence leaves drafting. Re-drafting in
        # place would diverge from what LGM already holds on the lead.
        raise ArcRejectedError(
            [
                ArcProblem(
                    step_no=None,
                    reason="sequence_not_draftable",
                    detail=(
                        f"sequence is {sequence.status!r}; content is frozen at enrolment. "
                        "Stop and re-enrol to change the words"
                    ),
                )
            ]
        )

    problems = await validate_arc(session, draft_set, shape=shape)
    if problems:
        raise ArcRejectedError(problems)

    attribute_map = (shape.attribute_map or {}) if shape else {}
    touch_ids: list[uuid.UUID] = []
    draft_ids: list[uuid.UUID] = []

    for spec in sorted(draft_set.touches, key=lambda t: t.step_no):
        touch = Touch(
            sequence_id=sequence.id,
            step_no=spec.step_no,
            day_offset=spec.day_offset,
            channel=spec.channel,
            purpose=spec.purpose,
            status="pending",
            lgm_attribute=attribute_map.get(str(spec.step_no)),
            content_sync_status="pending",
            subject_source="custom_attribute" if spec.subject else "lgm_template",
        )
        session.add(touch)
        await session.flush()
        touch_ids.append(touch.id)

        draft = Draft(
            touch_id=touch.id,
            version=1,
            subject=spec.subject,
            body=spec.body,
            cited_proof_point_ids=list(spec.cited_proof_point_ids),
            cited_signal_ids=list(spec.cited_signal_ids),
            signal_dependence=spec.signal_dependence,
            model=model,
            prompt_version=prompt_version,
            generated_as="arc",
            is_current=True,
        )
        session.add(draft)
        await session.flush()
        draft_ids.append(draft.id)

    return StoredArc(sequence_id=sequence.id, touch_ids=touch_ids, draft_ids=draft_ids)


async def regenerate_draft(
    session: AsyncSession,
    *,
    touch: Touch,
    body: str,
    reason: str,
    subject: str | None = None,
    signal_dependence: str = "durable",
) -> Draft:
    """Add a version. Never overwrites, and refused after enrolment.

    Regeneration is only possible before content is written to the LGM lead.
    After that the words on the lead and the words in our database would
    diverge, and nobody would notice until a recipient got copy nobody
    approved.
    """
    sequence = await session.get(OutreachSequence, touch.sequence_id)
    editable = ("draft", "pending_eval", "pending_approval")
    if sequence is not None and sequence.status not in editable:
        raise ArcRejectedError(
            [
                ArcProblem(
                    step_no=touch.step_no,
                    reason="content_frozen",
                    detail=(
                        f"sequence is {sequence.status!r}; content is frozen at enrolment. "
                        "Stop the sequence and re-enrol to change the words"
                    ),
                )
            ]
        )
    if touch.content_sync_status == "written":
        raise ArcRejectedError(
            [
                ArcProblem(
                    step_no=touch.step_no,
                    reason="content_frozen",
                    detail="this touch has already been written to the LGM lead",
                )
            ]
        )

    current = (
        await session.execute(
            select(Draft).where(Draft.touch_id == touch.id, Draft.is_current.is_(True))
        )
    ).scalar_one_or_none()
    next_version = 1
    if current is not None:
        # Cleared before the new row is added: the partial unique index allows
        # exactly one current draft per touch.
        current.is_current = False
        next_version = current.version + 1
        await session.flush()

    draft = Draft(
        touch_id=touch.id,
        version=next_version,
        subject=subject,
        body=body,
        signal_dependence=signal_dependence,
        generated_as="regeneration",
        regenerated_reason=reason,
        is_current=True,
    )
    session.add(draft)
    await session.flush()
    return draft


async def mark_content_written(
    session: AsyncSession, sequence_id: uuid.UUID, *, when: datetime | None = None
) -> int:
    """Move every touch to `written` in one batch, sharing a timestamp.

    Per-step writes would let a campaign start half-written, which is invisible
    until a recipient gets the wrong message.
    """
    when = when or datetime.now(UTC)
    touches = list(
        (
            await session.execute(select(Touch).where(Touch.sequence_id == sequence_id))
        ).scalars()
    )
    unmapped = [t.step_no for t in touches if not t.lgm_attribute]
    if unmapped:
        raise ArcRejectedError(
            [
                ArcProblem(
                    step_no=None,
                    reason="unmapped_steps",
                    detail=(
                        f"steps {unmapped} have no LGM attribute; they would send whatever "
                        "the lead already held"
                    ),
                )
            ]
        )
    for t in touches:
        t.content_sync_status = "written"
        t.content_written_at = when
    await session.flush()
    return len(touches)
