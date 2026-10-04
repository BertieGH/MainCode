"""Stratified approval sampling.

Uniform sampling is the flaw this design exists to avoid: a random 6 of 18
could miss all four threads that actually needed looking at. So the population
is split first, and only the clean stratum is sampled.

Two properties are structural rather than conventional:

* **A flagged thread is never in a sample.** `draw` is only ever handed the
  clean stratum, and `stratify` is the only thing that decides which is which.
* **The rep cannot hand-pick.** `draw` takes no candidate list from the caller,
  the ids are written server-side, and `accept` compares what came back against
  what was stored. A sample recomputed per request could be reshaped by asking
  again until the answer suited.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.governance import Approval, ApprovalSample

#: One rejection in a sample doubles the next draw; two drop the whole batch to
#: individual review. A single miss is evidence the rate is too low; two is
#: evidence the batch itself is not trustworthy.
DOUBLE_AT = 1
INDIVIDUAL_AT = 2


@dataclass(frozen=True)
class Candidate:
    """One thread awaiting approval, with everything that could flag it."""

    sequence_id: uuid.UUID
    contact_name: str = ""
    evaluation_verdict: str = "pass"
    contact_verified: bool = True
    strategy_confidence: float | None = None
    cadence_matches_template: bool = True
    #: The rep pursued someone the sales rules left out.
    chosen_by_rep: bool = False
    #: The strategy was built with no live signal to cite.
    without_live_trigger: bool = False
    #: The rep rewrote some of the words — they approve what they wrote.
    edited_by_rep: bool = False


@dataclass
class Stratum:
    flagged: list[Candidate] = field(default_factory=list)
    clean: list[Candidate] = field(default_factory=list)
    #: sequence_id → why it needs eyes. Shown on the card, so a rep knows what
    #: to look at rather than just that something is wrong.
    reasons: dict[uuid.UUID, list[str]] = field(default_factory=dict)


#: Below this, a strategy is not confident enough to accept unread.
CONFIDENCE_FLOOR = 0.6


def flag_reasons(candidate: Candidate) -> list[str]:
    """Why this thread must be read individually. Empty means it is clean."""
    reasons: list[str] = []
    if candidate.evaluation_verdict in ("warn", "fail"):
        reasons.append(f"evaluation returned {candidate.evaluation_verdict}")
    if not candidate.contact_verified:
        reasons.append("contact is not verified for this channel")
    if (
        candidate.strategy_confidence is not None
        and candidate.strategy_confidence < CONFIDENCE_FLOOR
    ):
        reasons.append(
            f"strategy confidence {candidate.strategy_confidence:.2f} is below "
            f"{CONFIDENCE_FLOOR}"
        )
    if not candidate.cadence_matches_template:
        reasons.append("cadence deviates from the registered template")
    if candidate.chosen_by_rep:
        reasons.append("chosen by a rep although the sales rules left this person out")
    if candidate.without_live_trigger:
        reasons.append("strategy built without a live signal")
    if candidate.edited_by_rep:
        reasons.append("drafts edited by you — approve them as read")
    return reasons


def stratify(candidates: list[Candidate]) -> Stratum:
    """Split before sampling. This ordering is the whole design."""
    stratum = Stratum()
    for candidate in candidates:
        reasons = flag_reasons(candidate)
        if reasons:
            stratum.flagged.append(candidate)
            stratum.reasons[candidate.sequence_id] = reasons
        else:
            stratum.clean.append(candidate)
    return stratum


def sample_size_for(stratum_size: int, rate: float, *, doublings: int = 0) -> int:
    """How many to read, rounded up so a small stratum is never sampled at zero.

    A rate of 0.4 over 3 threads rounds down to 1 either way, but 0.1 over 4
    would round down to 0 — a sample of nothing that reports as a sample.
    """
    if stratum_size <= 0:
        return 0
    effective = min(1.0, rate * (2**doublings))
    size = int(-(-stratum_size * effective // 1))  # ceil
    return max(1, min(size, stratum_size))


async def draw(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    stratum: Stratum,
    rate: float,
    doublings: int = 0,
    escalated: bool = False,
) -> ApprovalSample:
    """Draw a fresh sample over the clean stratum and store it.

    Only `stratum.clean` is ever passed to the random choice — the flagged
    list is not in scope here at all, which is why a flagged thread cannot end
    up sampled by accident.

    `secrets.SystemRandom` rather than `random`: the draw must not be
    reproducible from a guessable seed, or "randomly sampled" becomes a
    property anyone who knows the seed can work around.
    """
    previous = (
        await session.execute(
            select(ApprovalSample).where(
                ApprovalSample.campaign_id == campaign_id,
                ApprovalSample.is_current.is_(True),
            )
        )
    ).scalar_one_or_none()
    if previous is not None:
        # Superseded, never mutated — the record of how hard we looked has to
        # survive a redraw.
        previous.is_current = False
        await session.flush()

    clean_ids = [c.sequence_id for c in stratum.clean]
    size = 0 if escalated else sample_size_for(len(clean_ids), rate, doublings=doublings)
    chosen = (
        clean_ids
        if escalated
        else secrets.SystemRandom().sample(clean_ids, size)
    )

    row = ApprovalSample(
        campaign_id=campaign_id,
        draw_number=(previous.draw_number + 1) if previous else 1,
        sequence_ids=[str(s) for s in chosen],
        stratum_size=len(clean_ids),
        sample_size=len(chosen),
        sample_rate=rate,
        escalated_to_individual=escalated,
    )
    session.add(row)
    await session.flush()
    return row


class SampleTamperedError(ValueError):
    """The ids submitted are not the ids that were drawn."""


class SampleEscalatedError(RuntimeError):
    """Too many rejections — this batch must be read individually."""


async def record_rejections(
    session: AsyncSession, *, sample: ApprovalSample, rejected: int
) -> ApprovalSample:
    """Apply the escalation rule and redraw or escalate accordingly.

    One rejection doubles the next draw; two send the batch to individual
    review. Both are made visible in the returned row rather than being applied
    quietly, because a rep needs to see that the system reacted.
    """
    sample.rejections = rejected
    await session.flush()

    if rejected >= INDIVIDUAL_AT:
        sample.escalated_to_individual = True
        await session.flush()
        raise SampleEscalatedError(
            f"{rejected} rejections in a sample of {sample.sample_size} — "
            "the whole batch drops to individual review"
        )
    return sample


async def accept_sample(
    session: AsyncSession,
    *,
    sample: ApprovalSample,
    reviewed: dict[uuid.UUID, str],
    reviewer_id: str,
) -> list[Approval]:
    """Approve the drawn threads and inherit the rest of the stratum.

    `reviewed` must cover exactly the drawn ids. Submitting a different set —
    more, fewer, or substituted — is a tampered sample and is refused, because
    accepting it would let a rep choose which threads counted as read.
    """
    if sample.escalated_to_individual:
        raise SampleEscalatedError(
            "this batch escalated to individual review; there is no sample to accept"
        )

    drawn = {uuid.UUID(s) for s in sample.sequence_ids}
    submitted = set(reviewed)
    if submitted != drawn:
        raise SampleTamperedError(
            f"expected decisions for exactly the {len(drawn)} drawn sequences; "
            f"got {len(submitted)} "
            f"(missing {sorted(str(d) for d in drawn - submitted)}, "
            f"unexpected {sorted(str(s) for s in submitted - drawn)})"
        )

    rejected = sum(1 for d in reviewed.values() if d == "reject")
    if rejected:
        # A rejection means the stratum cannot be accepted on this draw. The
        # escalation rule decides whether that means a bigger sample or no
        # sampling at all — record_rejections raises either way.
        await record_rejections(session, sample=sample, rejected=rejected)
        raise SampleEscalatedError(
            f"{rejected} rejection in a sample of {sample.sample_size} — the sample "
            "doubles and must be redrawn before the stratum can be accepted"
        )

    written: list[Approval] = []
    for sequence_id, decision in reviewed.items():
        written.append(
            _approval(
                sequence_id, decision, reviewer_id, sample, depth="sampled"
            )
        )

    sample.accepted_at = datetime.now(UTC)
    for approval in written:
        session.add(approval)
    await session.flush()
    return written


def inherit(
    *,
    sample: ApprovalSample,
    unsampled: list[uuid.UUID],
    reviewer_id: str,
) -> list[Approval]:
    """Approvals for the stratum nobody read, marked honestly as `inherited`.

    This is the column the Learning layer compares against `sampled`. If the
    unread group underperforms, that is evidence to raise the rate — and
    without the distinction the sampling model can only be assumed safe.
    """
    return [
        _approval(sequence_id, "approve", reviewer_id, sample, depth="inherited")
        for sequence_id in unsampled
    ]


def _approval(
    sequence_id: uuid.UUID,
    decision: str,
    reviewer_id: str,
    sample: ApprovalSample,
    *,
    depth: str,
) -> Approval:
    return Approval(
        subject_type="outreach_sequence",
        subject_id=sequence_id,
        decision=decision,
        reviewer_id=reviewer_id,
        review_depth=depth,
        sample_id=sample.id,
        sample_size=sample.sample_size,
        stratum_size=sample.stratum_size,
    )
