"""Sales prep — what a rep needs to know before a call, one contact at a time.

**This router serves the facts; generation comes later.** The screen is built
around a brief the `sales_prep` stage writes, but everything underneath it —
who the person is, how old the picture is, what each qualification dimension
rests on, what has actually been sent — exists today and is worth reading on
its own. A rep can open this before any model has run and still learn more than
the account screen tells them.

Two decisions shape the module, both from the design review.

**Freshness is three questions, not one.** When we last looked, how old what we
found is, and whether anything has ever been sent. Measured on one real
account: researched today, strongest signal one day old, *oldest signal nine
months old*, nothing ever sent. One number would have read as "fresh" and been
wrong in two directions at once.

**Engagement is a ladder, and every rung is a different claim.** A drafted
message is not an approved one; an approved one is not sent; a sent one is not
delivered; a delivered one is not interest. A rep who walks into a call
believing the prospect read something they never received has been actively
misled, so this reports the furthest rung actually reached and names the rungs
it cannot observe rather than reporting them as zero.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_session, requires
from app.models.account import Account, AccountListMember, Contact, Run
from app.models.campaign import OutreachSequence
from app.models.config import ProofPoint
from app.models.content import Touch
from app.models.context import Qualification
from app.models.execution import OutreachEvent
from app.models.governance import Evaluation
from app.models.prep import SalesPrep
from app.models.research import ResearchCoverage
from app.models.signal import Evidence, Signal, signal_evidence
from app.models.strategy import StrategyThread
from app.services import stages
from app.services.apollo_list_builder import persona_of
from app.services.llm import LlmUnavailableError
from app.services.providers import ProviderError

router = APIRouter(tags=["prep"])

#: The rungs in order, so "furthest reached" is a scan from the end. A rung is
#: never inferred from an earlier one.
#:
#: **`delivered` is deliberately not here.** The review's chain — drafted,
#: approved, sent, delivered, replied — is right in principle, but La Growth
#: Machine's event vocabulary is `message_sent`, `message_received`,
#: `unsubscribed`, `status_change` and `other`. It never reports delivery. So
#: that rung is not "waiting on the webhook receiver"; it is a thing this
#: provider will not tell us, and a ladder listing it would imply it is coming.
#: `NEVER_OBSERVABLE` says so instead.
LADDER = ("drafted", "approved", "sent", "replied")

#: Rungs no amount of plumbing will fill, with the reason. Reported every time,
#: because "we never learn this" has to be distinguishable from "not yet".
NEVER_OBSERVABLE = {
    "delivered": (
        "La Growth Machine reports messages sent and received, never delivery, "
        "so a send is the furthest thing we can confirm about reaching someone."
    )
}

#: The six as the scorer computes them — ours, not the review's proposed
#: taxonomy. These are already versioned in `scoring_config` and already carry
#: a basis and evidence ids per dimension; renaming them would be a migration
#: plus a re-score of the whole book for a vocabulary change.
DIMENSIONS = ("fit", "opportunity", "buyer", "commercial", "intent", "engagement")


class FreshnessOut(BaseModel):
    """One of the three ages, and what it does *not* tell you."""

    kind: str
    #: Days, or None when it has never happened. Zero and None are different
    #: answers — "today" against "never" — and a screen rendering both as 0
    #: tells a rep research is current when nobody has looked.
    days: int | None
    at: datetime | None = None
    detail: str


class EngagementOut(BaseModel):
    #: The furthest rung actually reached, or None when nothing was drafted.
    reached: str | None
    counts: dict[str, int]
    #: Rungs this installation cannot observe. Named, so the screen can say
    #: "we cannot see this" instead of showing zero and implying none.
    unobservable: list[str] = []
    #: Why, for the ones that will never be observable rather than merely not
    #: yet. A rep told "delivery unknown" deserves to know it stays unknown.
    unobservable_why: dict[str, str] = {}
    detail: str


class LastRunOut(BaseModel):
    """What the last research run actually did, per family.

    Shown before a refresh is bought rather than after it, so "is another one
    worth 9 cents" is answerable: nine families planned and seven returning is
    a different proposition from nine planned and two failing.
    """

    at: datetime | None
    status: str | None
    planned: int
    ran: int
    empty: int
    failed: int
    evidence: int


class ProofOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    body: str | None
    metrics: dict = {}
    #: Whether a measured outcome is attached. A case study without one may
    #: describe a capability but must not claim a result, and the screen has to
    #: say which it is holding.
    has_metric: bool


class ThreadOut(BaseModel):
    id: uuid.UUID
    thread_status: str
    problem_hypothesis: str
    trigger_summary: str
    positioning: str
    cta: str
    channel_sequence: list = []
    #: How well the approach fits the context — **not** whether the problem is
    #: real, and not how reliable the evidence is. Three different confidences
    #: that one unlabelled number used to stand for.
    strategy_confidence: float | None
    without_live_trigger: bool = False
    avoid_list: list = []
    #: The angle being pitched, by name (`docs/18`).
    angle: str | None = None
    #: The person's other angles — fall-back talk tracks for the call if the
    #: pitched one does not land.
    alternative_angles: list[dict] = []
    #: The one-sentence read of the company every angle hangs off.
    account_angle: str | None = None


async def _current_thread(session: AsyncSession, contact_id: uuid.UUID) -> StrategyThread | None:
    """The thread this person is being pitched on now.

    Read through their sequence, which always points at the current strategy's
    thread. This used to take rank 1 among every thread ever built for them —
    superseded versions included — and a brief was written from a strategy two
    rebuilds old (`docs/18`). The newest campaign wins if there are several.
    """
    thread_id = (
        await session.execute(
            select(OutreachSequence.thread_id)
            .where(OutreachSequence.contact_id == contact_id, OutreachSequence.thread_id.is_not(None))
            .order_by(OutreachSequence.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return await session.get(StrategyThread, thread_id) if thread_id else None


async def _proof_for(session: AsyncSession, thread: StrategyThread | None) -> list[ProofPoint]:
    """Approved proof for the service this person is pitched, plus general
    proof — the pitched angle's own first. Every approved claim for every
    service used to go in, and a brief could cite another service's demo."""
    from app.models.strategy import StrategyAngle

    query = select(ProofPoint).where(ProofPoint.is_approved.is_(True))
    if thread is not None:
        query = query.where((ProofPoint.service_id == thread.service_id) | (ProofPoint.service_id.is_(None)))
    rows = list((await session.execute(query.order_by(ProofPoint.title, ProofPoint.id))).scalars())
    if thread is None:
        return rows
    angle = (
        await session.execute(
            select(StrategyAngle).where(StrategyAngle.thread_id == thread.id, StrategyAngle.is_selected.is_(True))
        )
    ).scalar_one_or_none()
    first = {str(x) for x in ((angle.proof_point_ids or []) if angle else [])}
    return sorted(rows, key=lambda p: str(p.id) not in first)


async def _already_sent(session: AsyncSession, contact_id: uuid.UUID) -> list[dict]:
    """What this person has actually been sent: the words, in order.

    Hardcoded empty until now, so a brief after a reply still did not know
    what the prospect had been told (`docs/18`). Only touches that sent — a
    draft the prospect never received must not appear as something they read.
    """
    from app.models.content import Draft

    rows = (
        await session.execute(
            select(Touch, Draft)
            .join(OutreachSequence, OutreachSequence.id == Touch.sequence_id)
            .outerjoin(Draft, (Draft.touch_id == Touch.id) & Draft.is_current.is_(True))
            .where(OutreachSequence.contact_id == contact_id, Touch.status == "sent")
            .order_by(Touch.sent_at, Touch.step_no)
        )
    ).all()
    return [
        {
            "step": t.step_no,
            "channel": t.channel,
            "sent_on": t.sent_at.date().isoformat() if t.sent_at else None,
            "subject": d.subject if d else None,
            "body": d.body if d else None,
        }
        for t, d in rows
    ]


async def _prep_targets(session: AsyncSession, thread: StrategyThread | None):
    """The campaign's ICP and service as a prompt block, and the ICP version."""
    from app.models.campaign import OutreachCampaign
    from app.models.strategy import Strategy
    from app.services import campaign_strategy, strategy_context

    if thread is None:
        return {}, None
    strategy = await session.get(Strategy, thread.strategy_id)
    campaign = await session.get(OutreachCampaign, strategy.campaign_id) if strategy and strategy.campaign_id else None
    if campaign is None:
        return {}, None
    try:
        t = await campaign_strategy.targets(session, campaign)
    except campaign_strategy.NotReadyError:
        return {}, None
    return strategy_context.targets_brief(
        service=t.service, icp_name=t.icp_name, icp_description=t.icp_description, icp_version=t.icp_version,
    ), t.icp_version


async def _angles_for_prep(session: AsyncSession, thread: StrategyThread) -> dict:
    """The pitched angle's name, the others as talk tracks, and the company read."""
    from app.models.strategy import Strategy
    from app.services.campaign_strategy import angles_of

    angles = await angles_of(session, thread.id)
    chosen = next((a for a in angles if a["is_selected"]), None)
    strategy = await session.get(Strategy, thread.strategy_id)
    return {
        "angle": chosen["angle"] if chosen else None,
        "alternative_angles": [
            {k: a[k] for k in ("angle", "problem_hypothesis", "why_now", "positioning", "cta")}
            for a in angles
            if not a["is_selected"]
        ],
        "account_angle": strategy.account_angle if strategy else None,
    }


class DimensionOut(BaseModel):
    dimension: str
    score: float
    basis: str
    reason: str
    evidence_count: int


class QualificationOut(BaseModel):
    priority_score: float
    priority_band: str
    scoring_config_version: int
    dimensions: list[DimensionOut]
    man: dict = {}
    #: The average across dimensions the scorer could actually assess.
    #:
    #: **The headline number is not a verdict on the account.** One real case
    #: scores 49 "low" while averaging 68.75 over the four dimensions that were
    #: actually assessable; the two zeroes are missing firmographics and the
    #: fact that nobody has been contacted yet, neither of which says anything
    #: about whether the company is worth calling. A rep shown only 49 draws
    #: the wrong conclusion, so both are returned and labelled.
    assessed_average: float | None
    #: Dimensions the scorer had nothing to go on for. Not low scores — absent
    #: ones, and the difference decides whether a rep researches or walks away.
    unassessed: list[str] = []


#: What a rep may say about a signal, and how it lands in `evaluation`.
#:
#: "Outdated" is not "inaccurate": the first says our refresh cadence is wrong,
#: the second that our reading is. Flattened to one verdict the evaluation
#: layer could not tell us which to fix, so the word is kept in `issues`.
REP_VERDICTS = {
    "accurate": "pass",
    "needs_verification": "warn",
    "inaccurate": "fail",
    "outdated": "fail",
    "irrelevant": "fail",
}


class EvidenceOut(BaseModel):
    """One passage behind a signal, with where and when it came from.

    Two dates, not one. `observed_at` is when the source says the thing
    happened; `retrieved_at` is when we read it. A nine-month-old post read
    this morning is fresh research into a stale fact, and a screen showing one
    date cannot say which it is holding.
    """

    id: uuid.UUID
    source_name: str | None
    source_url: str | None
    excerpt: str
    observed_at: date | None
    retrieved_at: datetime | None
    reliability: float | None


class SignalBriefOut(BaseModel):
    id: uuid.UUID
    signal_type: str
    scope: str
    summary: str
    business_implication: str | None
    strength: str
    #: How reliably the source supports the fact. Distinct from the thread's
    #: strategy confidence.
    evidence_confidence: float
    observed_at: date | None
    expires_at: date | None
    lifecycle_state: str
    is_hypothesis: bool
    age_days: int | None
    #: Days until it expires. Negative never appears — an expired signal is
    #: filtered out before this.
    expires_in_days: int | None = None
    evidence_count: int
    sources: list[str] = []
    #: The passages themselves, so a rep can read what was actually written
    #: rather than our summary of it.
    evidence: list[EvidenceOut] = []
    #: Why this signal matters *here*, derived rather than written.
    #:
    #: Omitted when nothing cites it, which is itself worth seeing: a signal
    #: the strategy does not rest on and no dimension scored from is one we
    #: paid to find and have not used.
    relevance: str | None = None
    #: What a rep said about this signal, if they have said anything.
    rep_verdict: str | None = None


class PrepOut(BaseModel):
    contact_id: uuid.UUID
    contact_name: str
    title: str | None
    seniority: str | None
    persona_role: str | None
    buying_role: str | None
    #: Whether the persona came from a source or from reading a job title.
    #: "Economic buyer" inferred from "CEO" is a fair guess and not an org
    #: chart, and a rep deciding who to call should know which they hold.
    persona_basis: str
    #: Carried so the screen can say a person is unreachable by email without
    #: the address itself ever reaching the response. A prep brief needs no
    #: address, and invariant 9 keeps it out.
    email_status: str | None
    do_not_contact: bool
    do_not_contact_reason: str | None
    linkedin_url: str | None

    account_id: uuid.UUID
    account_name: str
    domain: str | None
    industry: str | None
    employee_count: int | None

    #: Research, signals, engagement — in that order, because that is the order
    #: in which a rep's trust in the brief degrades.
    freshness: list[FreshnessOut]
    engagement: EngagementOut
    qualification: QualificationOut | None
    #: The account's live signals, newest first, with this person's own
    #: included: a call is with someone.
    signals: list[SignalBriefOut]
    thread: ThreadOut | None
    #: Only `is_approved` proof may appear in anything a rep says aloud.
    proof: list[ProofOut]
    #: The most recent generated brief, if one exists. Absent until the stage
    #: runs, and the screen is useful without it.
    brief: dict | None = None
    brief_id: uuid.UUID | None = None
    brief_generated_at: datetime | None = None
    #: The mode the stored brief was *written* in, which can differ from the
    #: mode the facts imply today — a reply arriving after generation is
    #: exactly when a rep must be told the brief predates it.
    brief_mode: str | None = None
    #: True when something has happened since the brief was written. The brief
    #: is not wrong, it is simply older than the facts beside it, and saying so
    #: is cheaper than regenerating on every view.
    brief_is_stale: bool = False
    hypothesis_verdict: str | None = None
    outcome: str | None = None
    #: Which question opened it up, what we had wrong. Free text, because the
    #: useful part of a debrief is never in a fixed vocabulary.
    rep_note: str | None = None
    last_run: LastRunOut | None = None
    #: The lists this account is on. A refresh needs to know which ICPs decide
    #: what to look for; with exactly one the route resolves it itself.
    list_ids: list[uuid.UUID] = []
    #: Decided from the ladder, not chosen by hand: nothing sent means there is
    #: no conversation to be aware of, and a brief opening on an observation
    #: the prospect already answered wastes the call.
    mode: str


def _relevance(
    signal: Signal,
    trigger_ids: set[str],
    evidence_by_signal: dict[uuid.UUID, list["EvidenceOut"]],
    dimension_of_evidence: dict[str, list[str]],
) -> str | None:
    """Why this signal matters here, read off what actually cites it.

    Derived rather than written, because a sentence the model composes about
    its own importance is not a fact about anything. The strategy names the
    signal it rests on, and the scorer names the evidence each dimension used;
    both are already stored, and between them they say whether a signal is
    load-bearing or merely true.
    """
    if str(signal.id) in trigger_ids:
        return "The trigger this approach rests on."
    dims: list[str] = []
    for passage in evidence_by_signal.get(signal.id, []):
        for name in dimension_of_evidence.get(str(passage.id), []):
            if name not in dims:
                dims.append(name)
    if dims:
        joined = " and ".join([", ".join(dims[:-1]), dims[-1]] if len(dims) > 1 else dims)
        return f"Scored the {joined} dimension{'s' if len(dims) > 1 else ''}."
    return None


def _days_since(when: datetime | date | None) -> int | None:
    if when is None:
        return None
    if isinstance(when, datetime):
        at = when if when.tzinfo else when.replace(tzinfo=UTC)
        return max((datetime.now(UTC) - at).days, 0)
    return max((date.today() - when).days, 0)


@router.get("/prep/{contact_id}", response_model=PrepOut)
async def prep_for_contact(
    contact_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """Everything the prep screen reads, in one round trip.

    One request rather than six, for the same reason the account screen carries
    its contacts' profiles: "who am I calling and what do we know about them"
    is one question, asked once.
    """
    contact = (
        await session.execute(
            select(Contact)
            .options(selectinload(Contact.account))
            .where(Contact.id == contact_id)
        )
    ).scalar_one_or_none()
    if contact is None:
        raise HTTPException(404, "No such contact.")
    account: Account = contact.account

    # --- signals, and the two ages they carry ---
    #
    # Expired and superseded are both excluded: `drafting` refuses to cite
    # either, so a brief must not argue from one.
    # "Live" is `context.live_signals` — not expired by date, not superseded —
    # the definition strategy and drafting use. This read a lifecycle flag,
    # and the stages could disagree about what was live (`docs/18`).
    from app.services import context as context_service

    signal_rows = await context_service.live_signals(session, account.id)
    dated = [s.observed_at for s in signal_rows if s.observed_at]
    newest = max(dated) if dated else None
    oldest = min(dated) if dated else None

    looked = _days_since(account.research_completed_at)
    freshness = [
        FreshnessOut(
            kind="research",
            days=looked,
            at=account.research_completed_at,
            detail=(
                f"last run {account.research_status}"
                if looked is not None
                else "nobody has looked at this account yet"
            ),
        ),
        FreshnessOut(
            kind="signals",
            days=_days_since(newest),
            detail=(
                f"{len(signal_rows)} live · newest {_days_since(newest)}d · "
                f"oldest {_days_since(oldest)}d"
                if dated
                else "no live signal — a brief here argues from no trigger"
            ),
        ),
    ]

    # --- the ladder ---
    touches = list(
        (
            await session.execute(
                select(Touch)
                .join(OutreachSequence, OutreachSequence.id == Touch.sequence_id)
                .where(OutreachSequence.contact_id == contact.id)
            )
        ).scalars()
    )
    events = list(
        (
            await session.execute(
                select(OutreachEvent).where(OutreachEvent.contact_id == contact.id)
            )
        ).scalars()
    )
    counts = {
        "drafted": sum(1 for t in touches if t.content_written_at is not None),
        # Approval is at sequence level, never per touch (invariant 3). A touch
        # only reaches `scheduled` through an approved sequence, so that is the
        # observable rather than a per-touch flag that does not exist.
        "approved": sum(1 for t in touches if t.status in {"scheduled", "sent"}),
        "sent": sum(1 for t in touches if t.status == "sent"),
        # `received`, not `inbound`. The first version read `direction ==
        # "inbound"`, which the column's own CHECK constraint does not allow —
        # so reply detection could never fire and the brief would have stayed
        # in cold-approach mode after a prospect had written back. A test
        # inserting a real reply caught it.
        "replied": sum(1 for e in events if e.direction == "received"),
    }
    reached = next((rung for rung in reversed(LADDER) if counts.get(rung)), None)
    sent_at = [t.sent_at for t in touches if t.sent_at]
    freshness.append(
        FreshnessOut(
            kind="engagement",
            days=_days_since(max(sent_at)) if sent_at else None,
            at=max(sent_at) if sent_at else None,
            detail=(
                f"furthest rung reached: {reached}"
                if reached
                else f"{len(touches)} touch(es) planned, none sent"
            ),
        )
    )
    engagement = EngagementOut(
        reached=reached,
        counts=counts,
        # Delivery is never knowable from this provider; replies are, but only
        # once events start arriving. Until then a zero means "we cannot see
        # it" rather than "there were none", and saying which is the difference
        # between an honest brief and a confidently wrong one.
        unobservable=(
            list(NEVER_OBSERVABLE) if events else [*NEVER_OBSERVABLE, "replied"]
        ),
        unobservable_why=dict(NEVER_OBSERVABLE),
        detail=(
            "Nothing has been sent to this contact, so there is no conversation "
            "to be aware of."
            if not counts["sent"]
            else f"{counts['sent']} sent · {counts['replied']} recorded reply/replies"
        ),
    )

    # --- qualification, unpacked ---
    qual = (
        await session.execute(
            select(Qualification)
            .where(Qualification.account_id == account.id)
            .order_by(Qualification.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    qual_out = None
    if qual is not None:
        reasons = qual.reasons or {}
        dims: list[DimensionOut] = []
        assessed: list[float] = []
        unassessed: list[str] = []
        for name in DIMENSIONS:
            raw = reasons.get(name) or {}
            score = float(getattr(qual, f"{name}_score", 0) or 0)
            basis = str(raw.get("basis") or "unknown")
            ids = raw.get("evidence_ids") or []
            dims.append(
                DimensionOut(
                    dimension=name,
                    score=score,
                    basis=basis,
                    reason=str(raw.get("reason") or ""),
                    evidence_count=len(ids),
                )
            )
            # **An absence is not a finding.** `no_evidence` is the scorer
            # saying it had nothing to compare; `outreach` with nothing sent is
            # the engagement dimension being structurally zero until a campaign
            # runs. Neither says anything about whether the account is worth
            # calling, and averaging them in drags the number toward a verdict
            # the data does not support — on the real case it pulled 69 down to
            # 55. `contacts` is a genuine basis and stays in.
            if basis in {"no_evidence", "unknown"} or (
                basis == "outreach" and not counts["sent"]
            ):
                unassessed.append(name)
            else:
                assessed.append(score)
        qual_out = QualificationOut(
            priority_score=float(qual.priority_score or 0),
            priority_band=qual.priority_band or "low",
            scoring_config_version=qual.scoring_config_version,
            dimensions=dims,
            man={
                "money": qual.man_money,
                "authority": qual.man_authority,
                "need": qual.man_need,
            },
            assessed_average=(
                round(sum(assessed) / len(assessed), 2) if assessed else None
            ),
            unassessed=unassessed,
        )

    thread = await _current_thread(session, contact.id)
    trigger_ids = {str(x) for x in (thread.trigger_signal_ids or [])} if thread else set()

    # Which dimensions each evidence row helped score, so a signal that is not
    # the trigger can still say what it is doing here.
    dimension_of_evidence: dict[str, list[str]] = {}
    if qual is not None:
        for name, raw in (qual.reasons or {}).items():
            if not isinstance(raw, dict):
                continue
            for eid in raw.get("evidence_ids") or []:
                dimension_of_evidence.setdefault(str(eid), []).append(name)

    # --- where each signal came from ---
    #
    # One query for every signal's sources rather than one per signal: a
    # well-covered account holds dozens, and the screen opens with them.
    source_rows = (
        await session.execute(
            select(signal_evidence.c.signal_id, Evidence)
            .join(Evidence, Evidence.id == signal_evidence.c.evidence_id)
            .where(Evidence.account_id == account.id)
        )
    ).all()
    by_signal: dict[uuid.UUID, list[str]] = {}
    evidence_by_signal: dict[uuid.UUID, list[EvidenceOut]] = {}
    for signal_id, row in source_rows:
        names = by_signal.setdefault(signal_id, [])
        if row.source_name and row.source_name not in names:
            names.append(row.source_name)
        evidence_by_signal.setdefault(signal_id, []).append(
            EvidenceOut(
                id=row.id,
                source_name=row.source_name,
                source_url=row.source_url,
                excerpt=row.excerpt,
                observed_at=row.observed_at,
                retrieved_at=row.retrieved_at,
                reliability=float(row.reliability) if row.reliability is not None else None,
            )
        )

    # Rep verdicts, one query for the set. `issues` holds the specific word;
    # the verdict column holds only pass/warn/fail.
    verdicts: dict[uuid.UUID, str] = {}
    if signal_rows:
        for ev in (
            await session.execute(
                select(Evaluation)
                .where(
                    Evaluation.method == "rep",
                    Evaluation.subject_type == "signal",
                    Evaluation.subject_id.in_([s.id for s in signal_rows]),
                )
                .order_by(Evaluation.created_at.desc())
            )
        ).scalars():
            # Newest first, so the first seen per signal is the current one.
            if ev.subject_id in verdicts:
                continue
            # `scores`, not `issues`. An "accurate" verdict maps to `pass`,
            # a pass stores no issues, and the first version therefore read
            # the rep's word back as "pass" — a value no button matches, so a
            # recorded verdict vanished on reload. The word lives in `scores`
            # where it is recorded for every verdict, and `issues` keeps the
            # ones that are genuinely issues.
            scores = ev.scores or {}
            verdicts[ev.subject_id] = scores.get("rep_verdict") or ev.verdict

    signals_out = [
        SignalBriefOut(
            id=s.id,
            signal_type=s.signal_type,
            scope=s.scope,
            summary=s.summary,
            business_implication=s.business_implication,
            strength=s.strength,
            evidence_confidence=float(s.confidence or 0),
            observed_at=s.observed_at,
            expires_at=s.expires_at,
            lifecycle_state=s.lifecycle_state,
            is_hypothesis=s.is_hypothesis,
            age_days=_days_since(s.observed_at),
            expires_in_days=(
                max((s.expires_at - date.today()).days, 0) if s.expires_at else None
            ),
            evidence_count=len(evidence_by_signal.get(s.id, [])),
            sources=by_signal.get(s.id, []),
            evidence=evidence_by_signal.get(s.id, []),
            relevance=_relevance(s, trigger_ids, evidence_by_signal, dimension_of_evidence),
            rep_verdict=verdicts.get(s.id),
        )
        for s in signal_rows
    ]

    proof = await _proof_for(session, thread)

    last = (
        await session.execute(
            select(Run)
            .where(Run.account_id == account.id, Run.finished_at.is_not(None))
            .order_by(Run.finished_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    last_run = None
    if last is not None:
        rows = list(
            (
                await session.execute(
                    select(ResearchCoverage).where(ResearchCoverage.run_id == last.id)
                )
            ).scalars()
        )
        last_run = LastRunOut(
            at=last.finished_at,
            status=last.status,
            planned=len(rows),
            ran=sum(1 for r in rows if r.status == "ran"),
            empty=sum(1 for r in rows if r.status == "empty"),
            failed=sum(1 for r in rows if r.status == "failed"),
            evidence=sum(r.evidence_count or 0 for r in rows),
        )

    lists = list(
        (
            await session.execute(
                select(AccountListMember.list_id).where(
                    AccountListMember.account_id == account.id
                )
            )
        ).scalars()
    )

    stored = (
        await session.execute(
            select(SalesPrep)
            .where(SalesPrep.contact_id == contact.id)
            .order_by(SalesPrep.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    # Compared against what was true when it was written, not against a
    # timestamp: a brief written before three signals arrived is stale in the
    # way that matters, and one written an hour ago with nothing new since is
    # not stale at all.
    brief_is_stale = bool(
        stored
        and (
            stored.signal_count != len(signal_rows)
            or stored.touches_sent != counts["sent"]
            or stored.replies_seen != counts["replied"]
        )
    )

    # **The basis has to match what actually happened.** The first version of
    # this returned "inferred from job title" for every contact with a title
    # while `persona_role` came back null — asserting an inference nobody had
    # made, which is the exact failure the fact/inference/hypothesis labelling
    # exists to prevent. `persona_role` is stored on 2 of 124 contacts, so for
    # almost everyone the honest options are to derive it here or to say it is
    # not established.
    #
    # Derived with the same `persona_of` the Apollo builder pairs contacts
    # with, so the screen and the list that produced the contact cannot
    # disagree about who someone is. It returns None for a title neither ladder
    # recognises, and None is reported rather than guessed at.
    if contact.persona_role:
        persona = contact.persona_role
        persona_basis = "recorded on the contact"
    else:
        persona, _rank = persona_of(contact.title)
        persona_basis = (
            "inferred from job title"
            if persona
            else "not established — the title matches no persona ladder"
        )

    return PrepOut(
        contact_id=contact.id,
        contact_name=contact.full_name,
        title=contact.title,
        seniority=contact.seniority,
        buying_role=contact.buying_role,
        persona_role=persona,
        persona_basis=persona_basis,
        email_status=contact.email_status,
        do_not_contact=bool(contact.do_not_contact),
        do_not_contact_reason=contact.do_not_contact_reason,
        linkedin_url=contact.linkedin_url,
        account_id=account.id,
        account_name=account.name,
        domain=account.domain,
        industry=account.industry,
        employee_count=account.employee_count,
        freshness=freshness,
        engagement=engagement,
        qualification=qual_out,
        signals=signals_out,
        thread=(
            ThreadOut(
                id=thread.id,
                thread_status=thread.thread_status,
                problem_hypothesis=thread.problem_hypothesis,
                trigger_summary=thread.trigger_summary,
                positioning=thread.positioning,
                cta=thread.cta,
                channel_sequence=thread.channel_sequence or [],
                strategy_confidence=(
                    float(thread.confidence) if thread.confidence is not None else None
                ),
                without_live_trigger=bool(thread.without_live_trigger),
                avoid_list=thread.avoid_list or [],
                **(await _angles_for_prep(session, thread)),
            )
            if thread is not None
            else None
        ),
        proof=[
            ProofOut(
                id=p.id,
                kind=p.kind,
                title=p.title,
                body=p.body,
                metrics=p.metrics or {},
                has_metric=bool(p.metrics),
            )
            for p in proof
        ],
        brief=(stored.payload if stored else None),
        brief_id=(stored.id if stored else None),
        brief_generated_at=(stored.created_at if stored else None),
        brief_mode=(stored.mode if stored else None),
        brief_is_stale=brief_is_stale,
        hypothesis_verdict=(stored.hypothesis_verdict if stored else None),
        outcome=(stored.outcome if stored else None),
        rep_note=(stored.rep_note if stored else None),
        last_run=last_run,
        list_ids=lists,
        mode="engagement_aware" if counts["replied"] else "pre_engagement",
    )


class PrepRowOut(BaseModel):
    contact_id: uuid.UUID
    contact_name: str
    title: str | None
    persona_role: str | None
    account_id: uuid.UUID
    account_name: str
    #: What changed, not that something did. A contact with no trigger says so
    #: rather than being hidden from the list — the spec is explicit that prep
    #: by search must not be gated on having a reason.
    why_now: str
    why_now_kind: str
    #: Days since the account was last looked at, or None if never.
    research_days: int | None
    #: The furthest engagement rung reached, or None.
    engagement: str | None
    has_thread: bool
    do_not_contact: bool


class PrepIndexOut(BaseModel):
    #: Those with a reason to prep now — a meeting booked, or a reply asking
    #: for a call.
    queue: list[PrepRowOut]
    #: Why the queue is empty, when it is empty for a structural reason rather
    #: than because nothing qualifies. The difference matters: "no events can
    #: arrive yet" is a build state, "nobody has replied" is a sales fact.
    queue_blocked: str | None
    results: list[PrepRowOut]
    total: int


@router.get("/prep", response_model=PrepIndexOut)
async def prep_index(
    q: str | None = None,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
):
    """Search any contact, plus the queue of those with a reason to prep.

    **The queue is a convenience, not a gate.** A rep who wants to prepare
    before there is a calendar invite should not be blocked by the data model,
    so search covers every contact and the queue is additive.
    """
    stmt = (
        select(Contact, Account)
        .join(Account, Account.id == Contact.account_id)
        .order_by(Contact.full_name)
        .limit(max(1, min(limit, 200)))
    )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            Contact.full_name.ilike(like)
            | Contact.title.ilike(like)
            | Account.name.ilike(like)
        )
    pairs = (await session.execute(stmt)).all()

    account_ids = {a.id for _c, a in pairs}
    contact_ids = {c.id for c, _a in pairs}

    # The newest live signal per account, for "why now". One query for the set
    # rather than one per row.
    newest: dict[uuid.UUID, Signal] = {}
    if account_ids:
        for s in (
            await session.execute(
                select(Signal)
                .where(
                    Signal.account_id.in_(account_ids),
                    Signal.lifecycle_state != "expired",
                    Signal.superseded_by.is_(None),
                )
                .order_by(Signal.observed_at.desc().nullslast())
            )
        ).scalars():
            newest.setdefault(s.account_id, s)

    # The current thread per person, through their newest sequence — as
    # `_current_thread` reads it. Taking the first thread found could pick a
    # superseded strategy's (`docs/18`).
    threads: dict[uuid.UUID, StrategyThread] = {}
    if contact_ids:
        for seq_contact, t in (
            await session.execute(
                select(OutreachSequence.contact_id, StrategyThread)
                .join(StrategyThread, StrategyThread.id == OutreachSequence.thread_id)
                .where(OutreachSequence.contact_id.in_(contact_ids))
                .order_by(OutreachSequence.created_at.desc())
            )
        ).all():
            threads.setdefault(seq_contact, t)

    sent_by_contact: dict[uuid.UUID, int] = {}
    if contact_ids:
        for seq_contact, status in (
            await session.execute(
                select(OutreachSequence.contact_id, Touch.status)
                .join(Touch, Touch.sequence_id == OutreachSequence.id)
                .where(OutreachSequence.contact_id.in_(contact_ids))
            )
        ).all():
            if status == "sent":
                sent_by_contact[seq_contact] = sent_by_contact.get(seq_contact, 0) + 1

    rows = []
    for contact, account in pairs:
        signal = newest.get(account.id)
        thread = threads.get(contact.id)
        if signal is not None:
            why, kind = signal.summary, "signal"
        elif thread is not None and thread.trigger_summary:
            # A thread built without a live trigger says so in its own words;
            # passing it through as a trigger would overstate it.
            why = thread.trigger_summary
            kind = "no_trigger" if thread.without_live_trigger else "thread"
        else:
            why, kind = "No active signal", "none"
        persona = contact.persona_role or persona_of(contact.title)[0]
        rows.append(
            PrepRowOut(
                contact_id=contact.id,
                contact_name=contact.full_name,
                title=contact.title,
                persona_role=persona,
                account_id=account.id,
                account_name=account.name,
                why_now=why,
                why_now_kind=kind,
                research_days=_days_since(account.research_completed_at),
                engagement=("sent" if sent_by_contact.get(contact.id) else None),
                has_thread=thread is not None,
                do_not_contact=bool(contact.do_not_contact),
            )
        )

    # The queue is driven by `meeting_booked` and positive-reply events. Until
    # the webhook receiver exists nothing can arrive, so the emptiness is
    # structural and the screen is told as much rather than left to imply that
    # nobody qualifies.
    any_event = (
        await session.execute(select(OutreachEvent.id).limit(1))
    ).scalar_one_or_none()
    queue_rows = [r for r in rows if r.engagement == "sent"] if any_event else []

    return PrepIndexOut(
        queue=queue_rows,
        queue_blocked=(
            None
            if any_event
            else (
                "The queue fills from meeting-booked and reply events, which arrive "
                "through the outreach webhook receiver. No event has ever been "
                "received, so nothing can be queued yet — search still works, and a "
                "contact with no meeting can be prepped anyway."
            )
        ),
        results=rows,
        total=len(rows),
    )


class GenerateOut(BaseModel):
    prep_id: uuid.UUID
    mode: str
    brief: dict
    generated_at: datetime


class VerdictIn(BaseModel):
    #: Whether the brief's hypothesis survived contact with the prospect.
    hypothesis_verdict: str | None = None
    outcome: str | None = None
    #: Which question opened it up, what we had wrong. Free text, because the
    #: useful part of a debrief is never in a fixed vocabulary.
    rep_note: str | None = None
    last_run: LastRunOut | None = None
    #: The lists this account is on. A refresh needs to know which ICPs decide
    #: what to look for; with exactly one the route resolves it itself.
    list_ids: list[uuid.UUID] = []
    rep_note: str | None = None


@router.post(
    "/prep/{contact_id}/generate",
    response_model=GenerateOut,
    dependencies=[Depends(requires("llm"))],
)
async def generate_prep_brief(
    contact_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """Write the brief for this contact, now.

    **One contact, on demand, never in batch and never in advance.** At two
    dozen threads and a handful of meetings, generating for everyone is about
    eightfold waste, and a brief written on day 0 for a call on day 18 argues
    from a picture that predates the whole conversation.

    The mode is decided here from what has actually been sent rather than
    offered as a choice: a rep cannot know better than the record, and a brief
    opening on an observation the prospect already answered wastes the call.
    """
    facts = await prep_for_contact(contact_id, session)
    contact = await session.get(Contact, contact_id)
    account = await session.get(Account, facts.account_id)
    if contact is None or account is None:  # pragma: no cover — prep_for_contact 404s first
        raise HTTPException(404, "No such contact.")

    replies = list(
        (
            await session.execute(
                select(OutreachEvent.preview)
                .where(
                    OutreachEvent.contact_id == contact_id,
                    OutreachEvent.direction == "received",
                )
                .order_by(OutreachEvent.occurred_at)
            )
        ).scalars()
    )

    from app.services import strategy_context

    thread = await _current_thread(session, contact_id)
    targets, icp_version = await _prep_targets(session, thread)
    # Ranked as strategy ranks them, the pitch's trigger marked, evidence on
    # every one (a call argues from the whole picture) and no URLs.
    ranked_signals = await strategy_context.signal_brief(
        session, account_id=account.id, contact_id=contact.id, icp_version=icp_version,
        cited={str(x) for x in ((thread.trigger_signal_ids or []) if thread else [])},
        evidence_for_all=True,
    )
    sent = await _already_sent(session, contact_id)

    try:
        # Prep is the stage a human waits on, and the only one aimed at one
        # person with no run behind it. Attributed so the cost screen can say
        # whose brief took sixteen seconds.
        with stages.attributed(
            account_id=account.id, contact_id=contact.id, scope="contact"
        ):
            result = await stages.generate_prep(
                session,
                account=account,
                contact=contact,
                thread=(facts.thread.model_dump(mode="json") if facts.thread else {}),
                # Only touches that actually sent. A drafted message the
                # prospect never received must not appear as something they
                # have been told.
                already_sent=sent,
                replies=[r for r in replies if r],
                # Each signal carries its age and confidence. Given only the
                # conclusions the model writes a confident brief; given the
                # gaps it writes an honest one, and the gaps are what a rep
                # needs on a call.
                signals=ranked_signals,
                qualification=(
                    facts.qualification.model_dump(mode="json")
                    if facts.qualification
                    else {}
                ),
                proof=[p.model_dump(mode="json") for p in facts.proof],
                mode=facts.mode,
                targets=targets,
            )
    except ProviderError as exc:
        # A quota refusal is an answer, not an Internal Server Error.
        raise HTTPException(503, str(exc)) from exc
    except LlmUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc

    newest = max((s.observed_at for s in facts.signals if s.observed_at), default=None)
    row = SalesPrep(
        contact_id=contact_id,
        account_id=account.id,
        mode=facts.mode,
        payload=result.parsed.model_dump(mode="json"),
        research_completed_at=account.research_completed_at,
        newest_signal_on=newest,
        signal_count=len(facts.signals),
        touches_sent=facts.engagement.counts.get("sent", 0),
        replies_seen=facts.engagement.counts.get("replied", 0),
    )
    session.add(row)
    await session.commit()

    return GenerateOut(
        prep_id=row.id,
        mode=row.mode,
        brief=row.payload,
        generated_at=row.created_at,
    )


@router.post("/prep/{prep_id}/verdict", response_model=GenerateOut)
async def record_verdict(
    prep_id: uuid.UUID,
    payload: VerdictIn,
    session: AsyncSession = Depends(get_session),
):
    """What happened on the call.

    **The measure worth watching is the hypothesis verdict, not the outcome.**
    Briefs whose hypotheses prospects keep rejecting mean the signal
    interpretation or the account selection is wrong — not the writing — and
    without this the system can only learn how persuasive its own prose looks.
    """
    row = await session.get(SalesPrep, prep_id)
    if row is None:
        raise HTTPException(404, "No such brief.")
    if payload.hypothesis_verdict is not None:
        row.hypothesis_verdict = payload.hypothesis_verdict
    if payload.outcome is not None:
        row.outcome = payload.outcome
    if payload.rep_note is not None:
        row.rep_note = payload.rep_note
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        # The CHECK constraints name the vocabulary; a typo is a 400, not a 500.
        raise HTTPException(400, "Not a recognised verdict or outcome.") from exc
    return GenerateOut(
        prep_id=row.id, mode=row.mode, brief=row.payload, generated_at=row.created_at
    )


class SignalVerdictIn(BaseModel):
    verdict: str
    note: str | None = None


@router.post("/prep/signals/{signal_id}/verdict", response_model=SignalBriefOut)
async def record_signal_verdict(
    signal_id: uuid.UUID,
    payload: SignalVerdictIn,
    session: AsyncSession = Depends(get_session),
):
    """What a rep says about a signal, kept where evaluations are kept.

    **This is the loop closing.** Every other verdict in the system is the
    model's own — extraction decides a passage is a product launch, scoring
    decides what it is worth. A rep who reads the passage and says it is
    outdated knows something no evaluator does, and until now there was
    nowhere to put it.

    `outdated` and `inaccurate` are deliberately kept apart. The first says
    the refresh cadence is wrong, the second that the reading is, and they
    send you to different code.
    """
    signal = await session.get(Signal, signal_id)
    if signal is None:
        raise HTTPException(404, "No such signal.")
    verdict = REP_VERDICTS.get(payload.verdict)
    if verdict is None:
        raise HTTPException(
            400, f"Verdict must be one of: {', '.join(sorted(REP_VERDICTS))}."
        )

    session.add(
        Evaluation(
            subject_type="signal",
            subject_id=signal_id,
            method="rep",
            verdict=verdict,
            # The rep's own word, always, because the column's three values
            # cannot carry five and "outdated" is not "inaccurate".
            scores={"rep_verdict": payload.verdict},
            # Only the ones that are genuinely issues. The constraint requires
            # one for anything but a pass.
            issues=(
                None
                if verdict == "pass"
                else [{"kind": payload.verdict, "note": payload.note}]
            ),
            evaluator_version="rep",
        )
    )
    await session.commit()

    return SignalBriefOut(
        id=signal.id,
        signal_type=signal.signal_type,
        scope=signal.scope,
        summary=signal.summary,
        business_implication=signal.business_implication,
        strength=signal.strength,
        evidence_confidence=float(signal.confidence or 0),
        observed_at=signal.observed_at,
        expires_at=signal.expires_at,
        lifecycle_state=signal.lifecycle_state,
        is_hypothesis=signal.is_hypothesis,
        age_days=_days_since(signal.observed_at),
        evidence_count=0,
        rep_verdict=payload.verdict,
    )
