"""Read surface for everything Phases 3–7 produce.

Read-only on purpose. Signals, qualifications and strategies are written by the
pipeline against evidence; a PATCH here would let the UI author a conclusion
that no evidence supports, which is the one thing the whole chain is built to
prevent. Editing means re-running a stage, not overwriting its output.
"""

from __future__ import annotations

import uuid

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.account import Account, Contact
from app.models.campaign import (
    CadenceShape,
    CampaignQueue,
    CampaignQueueMember,
    OutreachCampaign,
    OutreachSequence,
)
from app.models.context import AccountContext, Qualification
from app.models.research import ResearchCoverage
from app.models.signal import Evidence, Signal, signal_evidence
from app.services.cadence import check_enrolment

router = APIRouter(tags=["intelligence"])


# --------------------------------------------------------------------------
# response shapes
# --------------------------------------------------------------------------
class EvidenceOut(BaseModel):
    id: uuid.UUID
    source_type: str
    source_url: str | None
    source_name: str | None
    title: str | None
    excerpt: str
    observed_at: str | None
    raw_status: str
    reliability: float | None = None


def _evidence_out(e: Evidence) -> EvidenceOut:
    return EvidenceOut(
        id=e.id,
        source_type=e.source_type,
        source_url=e.source_url,
        source_name=e.source_name,
        title=e.title,
        excerpt=e.excerpt,
        observed_at=e.observed_at.isoformat() if e.observed_at else None,
        raw_status=e.raw_status,
        reliability=float(e.reliability) if e.reliability is not None else None,
    )


class SignalOut(BaseModel):
    id: uuid.UUID
    signal_type: str
    scope: str
    summary: str
    business_implication: str | None
    strength: str
    confidence: float
    observed_at: str
    expires_at: str | None
    lifecycle_state: str
    #: Set when a newer reading of an ongoing theme replaced this one. A
    #: superseded signal is as dead as an expired one — `drafting` refuses to
    #: cite either — so the screen needs it to group them the same way. Without
    #: it a replaced theme read as live.
    superseded_by: uuid.UUID | None
    is_hypothesis: bool
    contact_id: uuid.UUID | None
    contact_name: str | None
    evidence: list[EvidenceOut]


class CoverageOut(BaseModel):
    family: str
    status: str
    evidence_count: int
    detail: str | None
    #: What the family searched for and could not establish.
    not_found: list[str] = []
    #: Remarks about the shape of what came back, kept apart from misses: a
    #: sweep that found thirty entries and stored ten established plenty, and
    #: reporting that as "1 not established" said close to the opposite.
    notes: list[str] = []
    #: The passages this family found in this run — what `evidence_count`
    #: counts, openable so a rep can check them.
    evidence: list[EvidenceOut] = []
    #: When this family was last answered. Families can come from different
    #: runs once the reuse window skips the fresh ones.
    researched_at: str | None = None
    #: The person this row is about; null for the company.
    contact_id: uuid.UUID | None = None
    contact_name: str | None = None
    contact_title: str | None = None


class DimensionOut(BaseModel):
    dimension: str
    score: float
    reason: str
    basis: str
    evidence_ids: list[str]


class IcpScoreOut(BaseModel):
    icp_profile_id: uuid.UUID
    icp_name: str
    icp_version: int
    priority_score: float
    priority_band: str
    fit: float
    buyer: float


class OutreachPersonOut(BaseModel):
    contact_id: uuid.UUID
    full_name: str
    title: str | None = None
    sequence_id: uuid.UUID
    strategy: str
    problem_hypothesis: str | None = None
    drafts: str


class OutreachOut(BaseModel):
    """One campaign this company's people are in — where strategy and drafts live."""

    campaign_id: uuid.UUID
    label: str
    status: str
    service_code: str | None = None
    icp_name: str | None = None
    priority_score: float | None = None
    priority_band: str | None = None
    people: list[OutreachPersonOut] = []


class QualificationOut(BaseModel):
    id: uuid.UUID
    priority_score: float
    priority_band: str
    scoring_config_version: int
    dimensions: list[DimensionOut]
    man: dict | None = None
    #: The same assessment read for each ICP: fit and buyer recomputed, no model call.
    by_icp: list[IcpScoreOut] = []


class ThreadOut(BaseModel):
    id: uuid.UUID
    contact_id: uuid.UUID
    contact_name: str
    contact_title: str | None
    weight: float
    rank: int
    thread_status: str
    problem_hypothesis: str
    trigger_summary: str
    positioning: str
    cta: str
    channel_sequence: list
    start_offset_days: int
    confidence: float | None


class MatrixCellOut(BaseModel):
    contact_id: uuid.UUID
    contact_name: str
    service_code: str
    weight: float
    rationale: str | None


class StrategyOut(BaseModel):
    id: uuid.UUID
    version: int
    status: str
    threads: list[ThreadOut]
    #: The full matrix, activated or not. "Why didn't we contact the CEO?"
    matrix: list[MatrixCellOut]


class IntelligenceOut(BaseModel):
    """One account, end to end."""

    account_id: uuid.UUID
    account_name: str
    domain: str | None
    signals: list[SignalOut]
    coverage: list[CoverageOut]
    #: Passages from the coverage run stored before evidence recorded its
    #: family. Shown on their own rather than guessed into a family.
    unattributed_evidence: list[EvidenceOut] = []
    context_version: int | None
    #: The model's reading of the signals — themes, what changed, and what is
    #: still unknown. Absent when the overlay was never built or failed.
    context_narrative: dict | None = None
    qualification: QualificationOut | None
    #: Each campaign this company's people are in. Strategy and drafts live there.
    outreach: list[OutreachOut] = []


@router.get("/accounts/{account_id}/intelligence", response_model=IntelligenceOut)
async def account_intelligence(
    account_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """Everything the pipeline knows about one account, in pipeline order."""
    account = await session.get(Account, account_id)
    if account is None:
        raise HTTPException(404, "account not found")

    names = {
        c.id: c
        for c in (
            await session.execute(select(Contact).where(Contact.account_id == account_id))
        ).scalars()
    }

    # --- signals with their citations ---
    signals = list(
        (
            await session.execute(
                select(Signal)
                .where(
                    Signal.account_id == account_id,
                    # A superseded row is a repeat of a fact still shown under
                    # the row it points to. Kept, never deleted; not listed twice.
                    Signal.superseded_by.is_(None),
                )
                .order_by(Signal.observed_at.desc())
            )
        ).scalars()
    )
    cited = {}
    if signals:
        rows = await session.execute(
            select(signal_evidence.c.signal_id, Evidence)
            .join(Evidence, Evidence.id == signal_evidence.c.evidence_id)
            .where(signal_evidence.c.signal_id.in_([s.id for s in signals]))
        )
        for sid, ev in rows:
            cited.setdefault(sid, []).append(ev)

    signal_out = [
        SignalOut(
            id=s.id,
            signal_type=s.signal_type,
            scope=s.scope,
            summary=s.summary,
            business_implication=s.business_implication,
            strength=s.strength,
            confidence=float(s.confidence),
            observed_at=s.observed_at.isoformat(),
            expires_at=s.expires_at.isoformat() if s.expires_at else None,
            lifecycle_state=s.lifecycle_state,
            superseded_by=s.superseded_by,
            is_hypothesis=s.is_hypothesis,
            contact_id=s.contact_id,
            contact_name=names[s.contact_id].full_name if s.contact_id in names else None,
            evidence=[_evidence_out(e) for e in cited.get(s.id, [])],
        )
        for s in signals
    ]

    # --- coverage: the latest answer per family, across runs ---
    # Per family, not per run: inside the reuse window a run covers only the
    # families that were stale, so the newest run may hold two families while
    # the other two were answered by an earlier one. Both are the current answer.
    # Per person too: the contact pass records a row per family per person.
    latest: dict[tuple[str, uuid.UUID | None], ResearchCoverage] = {}
    for c in (
        await session.execute(
            select(ResearchCoverage)
            .where(ResearchCoverage.account_id == account_id)
            .order_by(ResearchCoverage.created_at.desc())
        )
    ).scalars():
        latest.setdefault((c.family, c.contact_id), c)

    coverage = []
    unattributed: list[EvidenceOut] = []
    if latest:
        found: dict[tuple[uuid.UUID, str | None, uuid.UUID | None], list[EvidenceOut]] = {}
        for e in (
            await session.execute(
                select(Evidence)
                .where(Evidence.run_id.in_({c.run_id for c in latest.values()}))
                .order_by(Evidence.observed_at.desc().nulls_last(), Evidence.retrieved_at)
            )
        ).scalars():
            found.setdefault((e.run_id, e.family, e.contact_id), []).append(_evidence_out(e))
        unattributed = [
            ev for (_, family, _), evs in found.items() if family is None for ev in evs
        ]

        def order(c: ResearchCoverage) -> tuple:
            person = names.get(c.contact_id) if c.contact_id else None
            # The company first, then each person, each by family.
            return (c.contact_id is not None, person.full_name if person else "", c.family)

        coverage = []
        for c in sorted(latest.values(), key=order):
            person = names.get(c.contact_id) if c.contact_id else None
            coverage.append(
                CoverageOut(
                    family=c.family,
                    status=c.status,
                    evidence_count=c.evidence_count,
                    detail=c.detail,
                    not_found=list(c.not_found or []),
                    notes=list(c.notes or []),
                    evidence=found.get((c.run_id, c.family, c.contact_id), []),
                    researched_at=c.created_at.isoformat() if c.created_at else None,
                    contact_id=c.contact_id,
                    contact_name=person.full_name if person else None,
                    contact_title=person.title if person else None,
                )
            )

    latest_context = (
        await session.execute(
            select(AccountContext)
            .where(AccountContext.account_id == account_id)
            .order_by(AccountContext.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    context_version = latest_context.version if latest_context else None
    context_narrative = (latest_context.payload or {}).get("narrative") if latest_context else None

    from app.services import icp_scores

    # --- latest qualification ---
    qual = (
        await session.execute(
            select(Qualification)
            .where(Qualification.account_id == account_id)
            .order_by(Qualification.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    qual_out = None
    if qual:
        qual_out = QualificationOut(
            id=qual.id,
            by_icp=[
                IcpScoreOut(
                    icp_profile_id=s.icp_profile_id, icp_name=s.icp_name, icp_version=s.icp_version,
                    priority_score=s.priority_score, priority_band=s.priority_band,
                    fit=next((d["score"] for d in s.dimensions if d["dimension"] == "fit"), 0.0),
                    buyer=next((d["score"] for d in s.dimensions if d["dimension"] == "buyer"), 0.0),
                )
                for s in await icp_scores.scores(session, account)
            ],
            priority_score=float(qual.priority_score),
            priority_band=qual.priority_band,
            scoring_config_version=qual.scoring_config_version,
            dimensions=[
                DimensionOut(
                    dimension=dim,
                    score=float(body["score"]),
                    reason=body.get("reason", ""),
                    basis=body.get("basis", "evidence"),
                    evidence_ids=body.get("evidence_ids", []),
                )
                for dim, body in sorted(qual.reasons.items())
                if not dim.startswith("_")
            ],
            man=(
                {"money": qual.man_money, "authority": qual.man_authority, "need": qual.man_need}
                if qual.man_money
                else None
            ),
        )

    # --- outreach: strategy and drafts live with each campaign ---
    from app.models.account import Contact as _Contact
    from app.models.campaign import OutreachCampaign, OutreachSequence
    from app.models.config import IcpProfile, ServiceCatalog
    from app.services import campaign_drafts
    from app.services.promotion import person_of

    enrolled = (
        await session.execute(
            select(OutreachSequence, OutreachCampaign, _Contact)
            .join(OutreachCampaign, OutreachCampaign.id == OutreachSequence.campaign_id)
            .join(_Contact, _Contact.id == OutreachSequence.contact_id)
            .where(_Contact.account_id == account_id)
            .order_by(OutreachCampaign.created_at.desc(), _Contact.full_name)
        )
    ).all()
    codes = dict((await session.execute(select(ServiceCatalog.id, ServiceCatalog.code))).all())
    icp_names = dict((await session.execute(select(IcpProfile.id, IcpProfile.name))).all())
    by_campaign: dict[uuid.UUID, OutreachOut] = {}
    for sequence, campaign, person in enrolled:
        entry = by_campaign.get(campaign.id)
        if entry is None:
            score = await icp_scores.score_for(session, account_id, campaign.icp_profile_id)
            entry = by_campaign[campaign.id] = OutreachOut(
                campaign_id=campaign.id, label=campaign.label, status=campaign.status,
                service_code=codes.get(campaign.service_id), icp_name=icp_names.get(campaign.icp_profile_id),
                priority_score=score.priority_score if score else None,
                priority_band=score.priority_band if score else None,
            )
        _, thread = await person_of(session, sequence)
        arc = await campaign_drafts.arc_of(session, sequence.id)
        state = campaign_drafts.state_of(sequence, thread is not None, arc)
        entry.people.append(OutreachPersonOut(
            contact_id=person.id, full_name=person.full_name, title=person.title,
            sequence_id=sequence.id, strategy="built" if thread else "not built",
            problem_hypothesis=thread.problem_hypothesis if thread else None,
            drafts=campaign_drafts.STATE_LABELS[state],
        ))
    outreach_out = list(by_campaign.values())

    return IntelligenceOut(
        account_id=account.id,
        account_name=account.name,
        domain=account.domain,
        signals=signal_out,
        coverage=coverage,
        unattributed_evidence=unattributed,
        context_version=context_version,
        context_narrative=context_narrative,
        qualification=qual_out,
        outreach=outreach_out,
    )


# --------------------------------------------------------------------------
# queues and campaigns
# --------------------------------------------------------------------------
class QueueOut(BaseModel):
    id: uuid.UUID
    label: str
    description: str | None
    status: str
    locked_at: str | None
    account_count: int
    #: People chosen for the queue by name.
    contact_count: int = 0
    promoted_to_campaign_id: uuid.UUID | None
    cloned_from_queue_id: uuid.UUID | None
    #: The service and ICP chosen with the queue; empty on older queues.
    service_id: uuid.UUID | None = None
    service_code: str | None = None
    icp_profile_id: uuid.UUID | None = None
    icp_name: str | None = None
    icp_version: int | None = None


@router.get("/queues", response_model=list[QueueOut])
async def get_queues(session: AsyncSession = Depends(get_session)):
    from app.models.campaign import CampaignQueueContact

    counts = (
        select(CampaignQueueMember.queue_id.label("qid"), func.count().label("n"))
        .group_by(CampaignQueueMember.queue_id)
        .subquery()
    )
    people = (
        select(CampaignQueueContact.queue_id.label("qid"), func.count().label("p"))
        .group_by(CampaignQueueContact.queue_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(CampaignQueue, func.coalesce(counts.c.n, 0), func.coalesce(people.c.p, 0))
            .outerjoin(counts, counts.c.qid == CampaignQueue.id)
            .outerjoin(people, people.c.qid == CampaignQueue.id)
            .order_by(CampaignQueue.created_at.desc())
        )
    ).all()
    from app.models.config import IcpProfile, ServiceCatalog

    codes = dict((await session.execute(select(ServiceCatalog.id, ServiceCatalog.code))).all())
    names = dict((await session.execute(select(IcpProfile.id, IcpProfile.name))).all())
    return [
        QueueOut(
            id=q.id,
            label=q.label,
            description=q.description,
            status=q.status,
            locked_at=q.locked_at.isoformat() if q.locked_at else None,
            account_count=n,
            contact_count=p,
            promoted_to_campaign_id=q.promoted_to_campaign_id,
            cloned_from_queue_id=q.cloned_from_queue_id,
            service_id=q.service_id,
            service_code=codes.get(q.service_id),
            icp_profile_id=q.icp_profile_id,
            icp_name=names.get(q.icp_profile_id),
            icp_version=q.icp_version,
        )
        for q, n, p in rows
    ]


class CampaignOut(BaseModel):
    id: uuid.UUID
    label: str
    status: str
    cadence_shape_key: str | None


@router.get("/campaigns", response_model=list[CampaignOut])
async def get_campaigns(session: AsyncSession = Depends(get_session)):
    shapes = {s.id: s for s in (await session.execute(select(CadenceShape))).scalars()}
    rows = (
        await session.execute(
            select(OutreachCampaign).order_by(OutreachCampaign.created_at.desc())
        )
    ).scalars()
    return [
        CampaignOut(
            id=c.id,
            label=c.label,
            status=c.status,
            cadence_shape_key=(
                shapes[c.cadence_shape_id].key if c.cadence_shape_id in shapes else None
            ),
        )
        for c in rows
    ]


class BlockOut(BaseModel):
    reason: str
    detail: str
    #: `block` stops an enrolment. `warn` does not — it states what happens
    #: next, such as a campaign that will hold its people until somebody
    #: launches it in LGM.
    severity: str = "block"


class CadenceShapeOut(BaseModel):
    id: uuid.UUID
    key: str
    label: str
    lgm_campaign_id: str
    touch_count: int
    span_days: int | None
    attributes_used: int
    lgm_status: str | None
    #: The audience this shape writes leads into — LGM's enrolment.
    lgm_audience_name: str | None = None
    verified_at: str | None
    verified_by: str | None
    lgm_updated_at: str | None
    durable_from_step: int | None
    active: bool
    #: Empty means it may enrol with nothing to say. Only entries with
    #: `severity == "block"` stop it.
    blocks: list[BlockOut]


class ShapeCheckOut(BaseModel):
    key: str
    #: Slots that moved since the last check, adopted by it. Separate from
    #: `findings`: these describe what was corrected, not what is wrong.
    changes: list[str] = Field(default_factory=list)
    #: The registration's own id. Returned so a caller that has just created
    #: one can use it immediately — promoting a queue straight onto a campaign
    #: it picked from LGM would otherwise have to re-list and match by key.
    shape_id: uuid.UUID | None = None
    #: True when the live campaign agrees with what is registered here.
    sound: bool
    checked: bool
    lgm_status: str | None = None
    audience_name: str | None = None
    steps: int = 0
    channels: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    detail: str = ""


class ShapeRegistrationIn(BaseModel):
    """What a rep can change about a registration. Never the steps themselves."""

    #: The LGM campaign whose sequence this shape describes.
    lgm_campaign_id: str | None = Field(default=None, max_length=200)
    #: The audience that campaign runs over — writing a lead into it is the enrolment.
    lgm_audience_name: str | None = Field(default=None, max_length=200)
    active: bool | None = None


@router.patch("/cadence-shapes/{key}", response_model=CadenceShapeOut)
async def update_cadence_shape(
    key: str, payload: ShapeRegistrationIn, session: AsyncSession = Depends(get_session)
):
    """Point a registered shape at the real LGM campaign and audience.

    Only the registration: touch count, timing and the attribute map come from
    LGM and are never authored here (invariant 6). Changing which campaign a
    shape points at **clears its verification** — the steps behind the new id
    are unknown until somebody checks them, and a stale `verified_at` would let
    copy enrol into a sequence nobody has looked at.
    """
    shape = (
        await session.execute(select(CadenceShape).where(CadenceShape.key == key))
    ).scalar_one_or_none()
    if shape is None:
        raise HTTPException(404, "cadence shape not found")

    if payload.lgm_campaign_id and payload.lgm_campaign_id != shape.lgm_campaign_id:
        shape.lgm_campaign_id = payload.lgm_campaign_id.strip()
        shape.verified_at = None
        shape.verified_by = None
        shape.lgm_status = None
        shape.lgm_updated_at = None
        shape.lgm_channels = None
        shape.lgm_audience_id = None
    if payload.lgm_audience_name is not None:
        shape.lgm_audience_name = payload.lgm_audience_name.strip() or None
    if payload.active is not None:
        shape.active = payload.active
    await session.commit()

    return CadenceShapeOut(
        id=shape.id, key=shape.key, label=shape.label,
        lgm_campaign_id=shape.lgm_campaign_id, touch_count=shape.touch_count,
        span_days=shape.span_days, attributes_used=shape.attributes_used,
        lgm_status=shape.lgm_status, lgm_audience_name=shape.lgm_audience_name,
        verified_at=shape.verified_at.isoformat() if shape.verified_at else None,
        verified_by=shape.verified_by,
        lgm_updated_at=shape.lgm_updated_at.isoformat() if shape.lgm_updated_at else None,
        durable_from_step=shape.durable_from_step, active=shape.active,
        blocks=[
            BlockOut(reason=b.reason, detail=b.detail, severity=b.severity)
            for b in check_enrolment(shape)
        ],
    )


class ShapeFromLgmIn(BaseModel):
    """Register an LGM campaign as a cadence shape.

    The steps are read from LGM, never typed: the touch count and which
    attribute each step sends come from the campaign's own templates, so a
    registration cannot disagree with the sequence it describes (invariant 6 —
    Gen360 never authors a cadence).
    """

    lgm_campaign_id: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=120)
    key: str | None = Field(default=None, max_length=60)
    #: Give the campaign an audience if it has none. On by default: a campaign
    #: with no audience cannot enrol anybody, because membership of the
    #: audience *is* the enrolment, and LGM only allows one to be set before
    #: the first launch — which is now. Set false to attach one by hand.
    attach_audience: bool = True

    # There is deliberately no `span_days`. It was asked for once, because
    # LGM's API exposes no step delay: `/campaigns/:id` carries none,
    # `/campaigns/:id/settings` is a 404, and `/campaigns/:id/messages` gives
    # order and channel and nothing about time. Asking a rep to supply it
    # produced a number that looked like a fact about the sequence and was
    # not — and drafting then measured the model's invented day offsets
    # against it. LGM schedules its own steps; this registration describes
    # them, it does not configure them.


@router.post("/cadence-shapes", response_model=ShapeCheckOut, status_code=201)
async def create_cadence_shape_from_lgm(
    payload: ShapeFromLgmIn, session: AsyncSession = Depends(get_session)
):
    """Read an LGM campaign's steps and register them as a shape."""
    import re as _re

    from app.services import lgm_client
    from app.services.lgm import LgmError

    adapter = await lgm_client.from_credentials(session)
    if adapter is None:
        raise HTTPException(
            409,
            "no La Growth Machine key is stored (or this is a demo installation), so its steps "
            "cannot be read",
        )

    key = (payload.key or _re.sub(r"[^a-z0-9]+", "_", payload.label.lower())).strip("_")[:60]
    if (
        await session.execute(select(CadenceShape).where(CadenceShape.key == key))
    ).scalar_one_or_none() is not None:
        raise HTTPException(409, f"a cadence shape called {key!r} is already registered")

    try:
        meta = await adapter.campaign_meta(payload.lgm_campaign_id)
        audience_id, audience_name = await adapter.campaign_audience(payload.lgm_campaign_id)
        templates = [
            t for t in await adapter.campaign_messages(payload.lgm_campaign_id)
            if t.get("active", True)
        ]
    except LgmError as exc:
        raise HTTPException(409, str(exc)) from exc

    if not templates:
        raise HTTPException(
            409,
            "that campaign has no active steps in LGM — build its sequence there first, and the "
            "registration will read it",
        )

    # The same reader `check_shape` uses, so a registration and a re-check can
    # never describe the campaign differently.
    read = lgm_client.read_templates(templates)
    attribute_map = {str(k): v for k, v in read.body_by_step.items()}
    subject_map = {str(k): v for k, v in read.subject_by_step.items()}
    step_channels = {str(k): v for k, v in read.channel_by_step.items()}
    findings = [
        f"step {step}'s template reads no lead attribute, so nothing we write would appear"
        for step in sorted(read.channel_by_step)
        if step not in read.body_by_step
    ]

    touch_count = read.steps
    shape = CadenceShape(
        key=key,
        label=payload.label.strip(),
        lgm_campaign_id=payload.lgm_campaign_id.strip(),
        touch_count=touch_count,
        attribute_map=attribute_map,
        subject_attribute_map=subject_map,
        step_channels=step_channels,
        step_meta={str(k): v for k, v in read.step_meta.items()},
        attributes_used=len(set(attribute_map.values())),
        lgm_audience_name=audience_name,
        lgm_audience_id=audience_id,
        lgm_status=lgm_client.CAMPAIGN_STATUS.get(meta.status.upper(), meta.status.lower()),
        lgm_updated_at=meta.updated_at,
        lgm_channels=list(meta.channels) or None,
        # Read from the live campaign a moment ago; that is what verification
        # means here, and `Check against LGM` re-reads it whenever it changes.
        verified_at=datetime.now(UTC) if not findings else None,
        verified_by="api" if not findings else None,
        active=True,
    )
    session.add(shape)
    await session.flush()

    # A campaign with no audience has nowhere for approved people to be
    # written, and this is the only window in which LGM lets one be set.
    if payload.attach_audience and not audience_id and shape.lgm_status == "ready":
        name = f"Gen360 · {shape.label}"
        try:
            existing = {a.get("name"): a for a in await adapter.audiences()}
            if name in existing:
                audience_id = str(existing[name].get("id"))
            else:
                audience_id = str(((await adapter.create_audience(name)).get("audience") or {}).get("id") or "")
            if audience_id:
                await adapter.set_campaign_audience(payload.lgm_campaign_id, audience_id)
                shape.lgm_audience_name, shape.lgm_audience_id = name, audience_id
                audience_name = name
        except LgmError as exc:
            # Registering still succeeded; the campaign simply cannot enrol
            # until somebody gives it an audience.
            findings.append(f"no audience could be attached automatically ({exc})")
            shape.verified_at, shape.verified_by = None, None

    await session.commit()

    return ShapeCheckOut(
        key=key,
        shape_id=shape.id,
        sound=not findings,
        checked=True,
        lgm_status=shape.lgm_status,
        audience_name=audience_name,
        steps=touch_count,
        channels=list(meta.channels),
        findings=findings,
        detail=(
            f"registered {touch_count} steps, scheduled by La Growth Machine"
            + (f", audience {audience_name!r}" if audience_name else ", no audience yet")
        ),
    )


class AudienceIn(BaseModel):
    #: What to call it. Defaults to the shape's own label, prefixed, so an
    #: audience in LGM is traceable to what created it.
    name: str | None = Field(default=None, max_length=120)


@router.post("/cadence-shapes/{key}/audience", response_model=ShapeCheckOut)
async def attach_audience(
    key: str, payload: AudienceIn, session: AsyncSession = Depends(get_session)
):
    """Give this shape's LGM campaign an audience to run over, creating it if needed.

    A campaign with no audience cannot enrol anybody: membership of the
    audience *is* the enrolment, so with none attached there is nowhere to
    write. LGM allows `audienceId` to be set only before a campaign's first
    launch, which is exactly when this is useful.

    Existing audiences are reused by name rather than duplicated — two
    audiences called the same thing is a trap, since leads are written by name.
    """
    from app.services import lgm_client
    from app.services.lgm import LgmError

    shape = (
        await session.execute(select(CadenceShape).where(CadenceShape.key == key))
    ).scalar_one_or_none()
    if shape is None:
        raise HTTPException(404, f"no cadence shape called {key!r}")

    adapter = await lgm_client.from_credentials(session)
    if adapter is None:
        raise HTTPException(409, "no La Growth Machine key is stored, so nothing can be attached")

    name = (payload.name or f"Gen360 · {shape.label}").strip()
    try:
        existing = {a.get("name"): a for a in await adapter.audiences()}
        if name in existing:
            audience_id = str(existing[name].get("id"))
        else:
            created = (await adapter.create_audience(name)).get("audience") or {}
            audience_id = str(created.get("id") or "")
            if not audience_id:
                raise HTTPException(409, "La Growth Machine created the audience but returned no id")
        await adapter.set_campaign_audience(shape.lgm_campaign_id, audience_id)
    except LgmError as exc:
        raise HTTPException(409, str(exc)) from exc

    shape.lgm_audience_name, shape.lgm_audience_id = name, audience_id
    await session.commit()

    check = await lgm_client.check_shape(adapter, shape)
    return ShapeCheckOut(
        key=key,
        shape_id=shape.id,
        changes=check.changes,
        sound=check.sound,
        checked=True,
        lgm_status=check.status,
        audience_name=name,
        steps=check.steps,
        channels=list(check.channels),
        findings=check.findings,
        detail=(
            f"{shape.label!r} now runs over audience {name!r} — approved people are written there, "
            "and that is what enrols them"
        ),
    )


@router.delete("/cadence-shapes/{key}", status_code=204)
async def delete_cadence_shape(key: str, session: AsyncSession = Depends(get_session)):
    """Remove a registration nothing has used.

    Refused the moment a campaign or a sequence points at it: the shape is how
    "which sequence did this person actually get?" is answered months later,
    and a campaign whose cadence has vanished cannot answer it. Deactivate
    those instead — `PATCH` with `active: false` keeps the history and takes it
    out of every picker.
    """
    from app.models.campaign import OutreachSequence

    shape = (
        await session.execute(select(CadenceShape).where(CadenceShape.key == key))
    ).scalar_one_or_none()
    if shape is None:
        raise HTTPException(404, "cadence shape not found")

    campaigns = await session.scalar(
        select(func.count()).select_from(OutreachCampaign).where(
            OutreachCampaign.cadence_shape_id == shape.id
        )
    )
    sequences = await session.scalar(
        select(func.count()).select_from(OutreachSequence).where(
            OutreachSequence.cadence_shape_id == shape.id
        )
    )
    if campaigns or sequences:
        raise HTTPException(
            409,
            f"{shape.label} is used by {campaigns} campaign(s) and {sequences} sequence(s) — "
            "deactivate it instead, so what they ran stays answerable",
        )

    await session.delete(shape)
    await session.commit()


@router.post("/cadence-shapes/{key}/verify", response_model=ShapeCheckOut)
async def verify_cadence_shape(key: str, session: AsyncSession = Depends(get_session)):
    """Check a registered shape against the live LGM campaign, and record it.

    `verified_at` used to mean "a person looked". This reads the campaign and
    its step templates: the steps say whether the touch count still matches,
    and the templates name the attributes each step actually sends — so a map
    pointing copy at an attribute nothing reads is caught here rather than by a
    prospect receiving an empty message.
    """
    from app.services import lgm_client
    from app.services.lgm import LgmError

    shape = (
        await session.execute(select(CadenceShape).where(CadenceShape.key == key))
    ).scalar_one_or_none()
    if shape is None:
        raise HTTPException(404, "cadence shape not found")

    adapter = await lgm_client.from_credentials(session)
    if adapter is None:
        return ShapeCheckOut(
            key=key, sound=False, checked=False,
            detail=(
                "no La Growth Machine key is stored (or this is a demo installation), so the "
                "registration could not be checked against the live campaign"
            ),
        )

    try:
        check = await lgm_client.check_shape(adapter, shape)
    except LgmError as exc:
        return ShapeCheckOut(key=key, sound=False, checked=False, detail=str(exc))

    shape.lgm_status = check.status
    shape.lgm_updated_at = check.updated_at
    shape.lgm_channels = list(check.channels) or None
    # Adopted, not merely reported. Re-reading the templates *is* the check, so
    # a shape whose campaign was edited in LGM is corrected here — before, the
    # mismatch was named and the stored map left wrong, and the only cure was
    # delete-and-re-register, which is refused once a campaign uses the shape.
    if check.body_by_step:
        shape.attribute_map = {str(k): v for k, v in check.body_by_step.items()}
        shape.subject_attribute_map = {str(k): v for k, v in check.subject_by_step.items()}
        shape.step_channels = {str(k): v for k, v in check.channel_by_step.items()}
        if check.step_meta:
            shape.step_meta = {str(k): v for k, v in check.step_meta.items()}
        shape.attributes_used = len(
            set(check.body_by_step.values()) | set(check.subject_by_step.values())
        )
        # `slot_labels` is not touched: it holds only what a rep typed, and
        # the name shown falls back to one derived from the live mapping. A
        # merge here would keep "linkedin 2 body" on a slot a template has
        # since moved to step 1's subject.
    # Touches carry a copy of the mapping taken when they were drafted, so a
    # moved slot leaves them addressed to the wrong attribute — step 1's email
    # body written where step 2's LinkedIn message reads. That copy is not a
    # decision anybody made, so it follows the shape rather than waiting for
    # somebody to notice. Anything already written to LGM is left alone: it
    # holds that copy in the old slot, and our row must keep describing it.
    #
    # Run on every check, not only when this one moved something: a shape
    # corrected before re-pointing existed still has touches addressed to the
    # old slots, and a reconciliation that only fires on change can never
    # catch up with itself. It is a no-op when everything already agrees.
    from app.services import campaign_drafts as _drafts

    await session.flush()
    repointed = await _drafts.repoint_to_shape(session, shape)
    if repointed["moved"]:
        check.changes.extend(repointed["moved"])
    if repointed["frozen"] and (check.changes or repointed["moved"]):
            check.findings.append(
                f"{repointed['frozen']} sequence(s) are already in La Growth Machine and keep the "
                "old attributes — their copy is frozen there. Stop and re-enrol to move them"
            )

    if check.audience_name and not shape.lgm_audience_name:
        # Adopted, not overwritten: a registration that names a different
        # audience is a finding, and silently retargeting it would hide that.
        shape.lgm_audience_name = check.audience_name
        shape.lgm_audience_id = check.audience_id
    if check.sound:
        shape.verified_at = datetime.now(UTC)
        shape.verified_by = "api"
    await session.commit()

    return ShapeCheckOut(
        key=key,
        shape_id=shape.id,
        changes=check.changes,
        sound=check.sound,
        checked=True,
        lgm_status=check.status,
        audience_name=shape.lgm_audience_name,
        steps=check.steps,
        channels=list(check.channels),
        findings=check.findings,
        detail=(
            f"verified against LGM — {check.steps} steps, audience {shape.lgm_audience_name!r}"
            if check.sound
            else "the live campaign does not match this registration"
        ),
    )


async def _refresh_against_lgm(session: AsyncSession, shapes: list[CadenceShape]) -> None:
    """Ask LGM which of these campaigns still exist, and record the answer.

    A registration is a copy of something somebody else owns. Deleting the
    campaign in LGM leaves a row here that looks healthy — verified, mapped,
    an audience named — and nothing stored can tell you otherwise. It happened:
    a campaign was registered, deleted in LGM, and pre-flight still reported
    the whole campaign ready to execute.

    One listing covers every shape, so this costs one call however many are
    registered. A failure to reach LGM changes nothing: a network problem is
    not evidence that a campaign was deleted.
    """
    from app.services import lgm_client
    from app.services.lgm import LgmError

    if not shapes:
        return
    adapter = await lgm_client.from_credentials(session)
    if adapter is None:
        return
    try:
        live = {str(c.get("id")) for c in await adapter.campaigns() if c.get("id")}
    except LgmError:
        return
    if not live:
        # An empty account and a failed read are indistinguishable here, and
        # marking every shape missing on the strength of it would be worse
        # than saying nothing.
        return

    changed = False
    for shape in shapes:
        gone = shape.lgm_campaign_id not in live
        if gone and shape.lgm_status != lgm_client.STATUS_MISSING:
            shape.lgm_status = lgm_client.STATUS_MISSING
            # The mapping cannot be trusted either: whatever replaces this
            # campaign has its own steps.
            shape.verified_at, shape.verified_by = None, None
            changed = True
        elif not gone and shape.lgm_status == lgm_client.STATUS_MISSING:
            # Back again — restored, or read during an outage. Re-verification
            # is still required; only the "it is gone" claim is withdrawn.
            shape.lgm_status = None
            changed = True
    if changed:
        await session.commit()


@router.get("/cadence-shapes", response_model=list[CadenceShapeOut])
async def get_cadence_shapes(
    live: bool = False, session: AsyncSession = Depends(get_session)
):
    """Registered shapes, each with the reasons it cannot currently enrol.

    `live=true` checks each registration against the LGM account first, so a
    campaign deleted there cannot be chosen here. The screens that pick a
    cadence ask for it; the ones that merely list shapes do not.
    """
    rows = list(
        (await session.execute(select(CadenceShape).order_by(CadenceShape.key))).scalars()
    )
    if live:
        await _refresh_against_lgm(session, rows)
    return [
        CadenceShapeOut(
            id=s.id,
            key=s.key,
            label=s.label,
            lgm_campaign_id=s.lgm_campaign_id,
            touch_count=s.touch_count,
            span_days=s.span_days,
            attributes_used=s.attributes_used,
            lgm_status=s.lgm_status,
            lgm_audience_name=s.lgm_audience_name,
            verified_at=s.verified_at.isoformat() if s.verified_at else None,
            verified_by=s.verified_by,
            lgm_updated_at=s.lgm_updated_at.isoformat() if s.lgm_updated_at else None,
            durable_from_step=s.durable_from_step,
            active=s.active,
            blocks=[
                BlockOut(reason=b.reason, detail=b.detail, severity=b.severity)
                for b in check_enrolment(s)
            ],
        )
        for s in rows
    ]
