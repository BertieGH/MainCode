"""Cadence drafts on the outreach screen: write, edit, version, save for approval.

`GET /campaigns/{id}/drafts` lists each person with their cadence and where
their drafts stand. `POST /sequences/{id}/drafts/write` writes (or rewrites)
every touch in one model call. `PUT /sequences/{id}/touches/{step}` saves the
rep's wording as a new version; `POST /sequences/{id}/save` saves the person's
drafts for approval. Every change returns the arc as the rep now sees it.
"""

from __future__ import annotations

import logging

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.campaigns import ArcOut, get_arc
from app.api.deps import requires
from app.database import get_session
from app.models.campaign import OutreachCampaign, OutreachSequence
from app.services import campaign_drafts
from app.services.campaign_drafts import DraftingRefusedError
from app.services.drafting import ArcRejectedError

log = logging.getLogger(__name__)

router = APIRouter(tags=["campaign drafts"])


class WithdrawIn(BaseModel):
    #: Required. "why did this person come out?" is asked later, by somebody
    #: who was not there.
    reason: str = Field(min_length=1, max_length=300)


@router.post("/sequences/{sequence_id}/withdraw", response_model=dict)
async def withdraw_from_campaign(
    sequence_id: uuid.UUID, payload: WithdrawIn, session: AsyncSession = Depends(get_session)
):
    """Take one person out of a campaign before anything is sent.

    Not a delete: the sequence stays with its reason and its drafts, and the
    strategy stays where it is. Once enrolled this is refused — the lever there
    is stopping the sequence, because LGM already holds the lead.
    """
    from app.services import promotion

    sequence = await session.get(OutreachSequence, sequence_id)
    if sequence is None:
        raise HTTPException(404, "sequence not found")
    try:
        await promotion.withdraw(session, sequence, reason=payload.reason)
    except promotion.NotWithdrawableError as exc:
        raise HTTPException(409, str(exc)) from exc
    await session.commit()
    return {"withdrawn": True, "reason": sequence.withdraw_reason}


@router.post("/sequences/{sequence_id}/reinstate", response_model=dict)
async def reinstate_into_campaign(
    sequence_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """Put a withdrawn person back. Their drafts survived; their approval did not."""
    from app.services import promotion

    sequence = await session.get(OutreachSequence, sequence_id)
    if sequence is None:
        raise HTTPException(404, "sequence not found")
    try:
        await promotion.reinstate(session, sequence)
    except promotion.NotWithdrawableError as exc:
        raise HTTPException(409, str(exc)) from exc
    await session.commit()
    return {"withdrawn": False}


class DraftRowOut(BaseModel):
    sequence_id: uuid.UUID
    contact_id: uuid.UUID
    full_name: str
    title: str | None = None
    account_id: uuid.UUID
    account_name: str
    cadence_key: str | None = None
    cadence_label: str | None = None
    cadence_touches: int | None = None
    cadence_days: int | None = None
    has_strategy: bool
    touch_count: int
    edited: bool
    #: strategy_needed, not_drafted, drafted, saved, approved or enrolled.
    state: str
    state_label: str
    status: str
    #: Set when they were taken out of this campaign.
    withdraw_reason: str | None = None
    #: The company's score for the campaign's ICP, and the qualify gate.
    qualification_score: float | None = None
    qualification_band: str | None = None
    gate: str = "not_qualified"
    gate_detail: str = ""


@router.get("/campaigns/{campaign_id}/drafts", response_model=list[DraftRowOut])
async def campaign_drafts_list(campaign_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    campaign = await session.get(OutreachCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "campaign not found")
    return [DraftRowOut(**r) for r in await campaign_drafts.rows(session, campaign)]


async def _sequence(session: AsyncSession, sequence_id: uuid.UUID) -> OutreachSequence:
    sequence = await session.get(OutreachSequence, sequence_id)
    if sequence is None:
        raise HTTPException(404, "sequence not found")
    return sequence


def _refused(exc: Exception) -> HTTPException:
    return HTTPException(409, {"error": "refused", "message": str(exc)})


def _rejected(exc: ArcRejectedError) -> HTTPException:
    return HTTPException(422, {
        "error": "arc_rejected",
        "message": "; ".join(p.detail for p in exc.problems),
        "problems": [p.model_dump() for p in exc.problems],
    })


@router.post(
    "/sequences/{sequence_id}/drafts/write",
    response_model=ArcOut,
    dependencies=[Depends(requires("llm"))],
)
async def write_drafts(sequence_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    """Write every touch for this person from their strategy — one model call."""
    from app.services import demo, llm

    sequence = await _sequence(session, sequence_id)
    try:
        await llm.assert_may_call(session, "outreach_drafting")
        await campaign_drafts.write(session, sequence)
    except (DraftingRefusedError, demo.EgressBlockedError) as exc:
        raise _refused(exc) from exc
    except ArcRejectedError as exc:
        await session.rollback()
        raise _rejected(exc) from exc
    await session.commit()
    return await get_arc(sequence_id, session)


class WriteManyIn(BaseModel):
    """Several people in one request, run concurrently."""

    sequence_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class WriteManyOut(BaseModel):
    drafted: int
    failed: int
    seconds: float
    #: sequence id → why it could not be drafted.
    errors: dict[str, str] = Field(default_factory=dict)


#: Model calls in flight at once. Drafting is the dearest stage by wall clock
#: — one call per person at roughly half a minute each — so a hundred people
#: took the better part of an hour in order. Bounded because each call is a
#: paid request against a rate limit.
DRAFT_CONCURRENCY = 5


@router.post(
    "/campaigns/{campaign_id}/drafts/write-many",
    response_model=WriteManyOut,
    dependencies=[Depends(requires("llm"))],
)
async def write_drafts_many(
    campaign_id: uuid.UUID, payload: WriteManyIn, session: AsyncSession = Depends(get_session)
):
    """Draft several people at once.

    Each person gets their own session: a refusal for one — no strategy yet,
    an arc that will not fit the cadence — must not roll back the drafts
    written beside it.
    """
    import asyncio
    import time

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.services import demo, llm

    await llm.assert_may_call(session, "outreach_drafting")

    engine = session.get_bind()
    engine = getattr(engine, "_async_engine", None) or session.bind or engine
    maker = async_sessionmaker(engine, expire_on_commit=False)
    limit = asyncio.Semaphore(DRAFT_CONCURRENCY)

    started = time.monotonic()
    drafted = 0
    errors: dict[str, str] = {}

    async def one(sequence_id: uuid.UUID) -> None:
        nonlocal drafted
        async with limit, maker() as own:
            try:
                sequence = await _sequence(own, sequence_id)
                await campaign_drafts.write(own, sequence)
                await own.commit()
                drafted += 1
            except (DraftingRefusedError, demo.EgressBlockedError, ArcRejectedError) as exc:
                await own.rollback()
                errors[str(sequence_id)] = str(exc)
            except Exception as exc:  # noqa: BLE001 - one person must not stop the rest
                await own.rollback()
                log.warning(
                    "campaign_drafts.batch_failed campaign=%s sequence=%s err=%s",
                    campaign_id, sequence_id, exc,
                )
                errors[str(sequence_id)] = str(exc)

    await asyncio.gather(*(one(s) for s in dict.fromkeys(payload.sequence_ids)))

    return WriteManyOut(
        drafted=drafted,
        failed=len(errors),
        seconds=round(time.monotonic() - started, 1),
        errors=errors,
    )


class TouchEditIn(BaseModel):
    subject: str | None = Field(default=None, max_length=300)
    body: str = Field(min_length=1, max_length=8000)


@router.put("/sequences/{sequence_id}/touches/{step_no}", response_model=ArcOut)
async def edit_touch(
    sequence_id: uuid.UUID, step_no: int, payload: TouchEditIn,
    session: AsyncSession = Depends(get_session),
):
    """Save the rep's wording for one touch as a new version."""
    sequence = await _sequence(session, sequence_id)
    try:
        await campaign_drafts.edit_touch(
            session, sequence, step_no, subject=payload.subject, body=payload.body
        )
    except DraftingRefusedError as exc:
        raise _refused(exc) from exc
    except ArcRejectedError as exc:
        await session.rollback()
        raise _rejected(exc) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(422, {"error": "invalid", "message": str(exc)}) from exc
    await session.commit()
    return await get_arc(sequence_id, session)


@router.post("/sequences/{sequence_id}/save", response_model=ArcOut)
async def save_for_approval(sequence_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    """Save this person's drafts for approval."""
    sequence = await _sequence(session, sequence_id)
    try:
        await campaign_drafts.save(session, sequence)
        await session.commit()
    except DraftingRefusedError as exc:
        raise _refused(exc) from exc
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, {
            "error": "live_elsewhere",
            "message": "this person already has a live sequence in another campaign — one person, "
            "one live sequence. Finish or stop that one first",
        }) from exc
    # Checked now, against the words being approved (`docs/18`). A failure to
    # evaluate never blocks the save — it leaves the thread unevaluated, and
    # approval reads that as a reason to read it individually.
    from app.services import draft_evaluation

    try:
        await draft_evaluation.evaluate(session, sequence)
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        log.warning("save_for_approval.evaluation_failed sequence=%s err=%s", sequence_id, exc)
    return await get_arc(sequence_id, session)


class VersionOut(BaseModel):
    version: int
    subject: str | None
    body: str
    #: arc (first write), regeneration (AI rewrite) or rep_edit.
    generated_as: str
    regenerated_reason: str | None
    model: str | None
    is_current: bool
    created_at: str | None


@router.get("/sequences/{sequence_id}/touches/{step_no}/versions", response_model=list[VersionOut])
async def touch_versions(
    sequence_id: uuid.UUID, step_no: int, session: AsyncSession = Depends(get_session)
):
    return [
        VersionOut(
            version=d.version, subject=d.subject, body=d.body, generated_as=d.generated_as,
            regenerated_reason=d.regenerated_reason, model=d.model, is_current=d.is_current,
            created_at=d.created_at.isoformat() if d.created_at else None,
        )
        for d in await campaign_drafts.versions(session, sequence_id, step_no)
    ]
