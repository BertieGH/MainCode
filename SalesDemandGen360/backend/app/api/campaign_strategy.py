"""The campaign's people: qualification and strategy against its service and ICP.

`GET /campaigns/{id}/people` lists each person with their company's score for
this campaign, the sales rules' default decision and any strategy built.
`POST …/strategy` builds the strategy for the campaign's people at one company,
with the rep's overrides — one model call, run one company at a time. Scores are
the company's, read for the campaign's ICP; nothing is scored here.
`POST …/targets` chooses the service and ICP for a campaign whose queue was
created before queues carried them.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import current_user
from app.api.deps import requires
from app.database import get_session
from app.models.account import Account
from app.models.campaign import OutreachCampaign
from app.models.identity import User
from app.services import access, campaign_strategy
from app.services.strategy import DifferentiationError

log = logging.getLogger(__name__)

router = APIRouter(tags=["campaign strategy"])


class PersonOut(BaseModel):
    sequence_id: uuid.UUID
    contact_id: uuid.UUID
    full_name: str
    title: str | None = None
    account_id: uuid.UUID
    account_name: str
    reachable: bool
    weight: float
    #: `pursue`, `below_threshold`, `over_limit` or `not_reachable` — the rules' answer.
    default_decision: str
    decision_detail: str
    live_signals: int
    #: Found by research but past their shelf life — they no longer count.
    expired_signals: int = 0
    qualification_band: str | None = None
    qualification_score: float | None = None
    #: `pass`, `below` or `not_qualified` against the queue's minimum band.
    gate: str = "not_qualified"
    gate_detail: str = ""
    strategy_status: str | None = None
    chosen_by_rep: bool = False
    without_live_trigger: bool = False
    problem_hypothesis: str | None = None
    #: Where their cadence drafts stand: strategy_needed, not_drafted, drafted,
    #: saved, approved or enrolled.
    draft_state: str = "strategy_needed"
    draft_state_label: str = ""
    touch_count: int = 0
    edited: bool = False


class CampaignPeopleOut(BaseModel):
    ready: bool
    blocked: str | None = None
    service_code: str | None = None
    icp_name: str | None = None
    icp_version: int | None = None
    threshold: float | None = None
    cap: int | None = None
    people: list[PersonOut] = Field(default_factory=list)


async def _campaign(session: AsyncSession, campaign_id: uuid.UUID) -> OutreachCampaign:
    campaign = await session.get(OutreachCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "campaign not found")
    return campaign


async def _account(session: AsyncSession, account_id: uuid.UUID) -> Account:
    account = await session.get(Account, account_id)
    if account is None:
        raise HTTPException(404, "account not found")
    return account


def _refused(exc: Exception) -> HTTPException:
    return HTTPException(409, {"error": "not_ready", "message": str(exc)})


@router.get("/campaigns/{campaign_id}/people", response_model=CampaignPeopleOut)
async def campaign_people(campaign_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    campaign = await _campaign(session, campaign_id)
    try:
        view = await campaign_strategy.people_view(session, campaign)
    except campaign_strategy.NotReadyError as exc:
        return CampaignPeopleOut(ready=False, blocked=str(exc))
    return CampaignPeopleOut(ready=True, **view)


class TargetsIn(BaseModel):
    service_id: uuid.UUID
    icp_profile_id: uuid.UUID


@router.post("/campaigns/{campaign_id}/targets", response_model=CampaignPeopleOut)
async def set_targets(
    campaign_id: uuid.UUID, payload: TargetsIn, session: AsyncSession = Depends(get_session)
):
    """Choose the service and ICP for a campaign whose queue had none."""
    campaign = await _campaign(session, campaign_id)
    try:
        await campaign_strategy.set_targets(
            session, campaign, payload.service_id, payload.icp_profile_id
        )
        view = await campaign_strategy.people_view(session, campaign)
    except campaign_strategy.NotReadyError as exc:
        raise _refused(exc) from exc
    await session.commit()
    return CampaignPeopleOut(ready=True, **view)


class BuildIn(BaseModel):
    account_id: uuid.UUID
    #: People the rules leave out whom the rep chose to pursue.
    pursue_anyway: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    #: People who may be approached without a live signal about their company.
    allow_without_signal: list[uuid.UUID] = Field(default_factory=list, max_length=500)


class BuildOut(BaseModel):
    account_id: uuid.UUID
    name: str
    built: bool
    version: int | None = None
    pursued: list[str] = Field(default_factory=list)
    overridden: list[str] = Field(default_factory=list)
    without_trigger: list[str] = Field(default_factory=list)
    excluded: list[dict] = Field(default_factory=list)
    note: str = ""


@router.post(
    "/campaigns/{campaign_id}/strategy",
    response_model=BuildOut,
    dependencies=[Depends(requires("llm"))],
)
async def build_strategy(
    campaign_id: uuid.UUID, payload: BuildIn, session: AsyncSession = Depends(get_session)
):
    """Build this campaign's strategy for its people at one company."""
    from app.services import demo, llm

    campaign = await _campaign(session, campaign_id)
    account = await _account(session, payload.account_id)
    try:
        await llm.assert_may_call(session, "strategy_synthesis")
        outcome = await campaign_strategy.build(
            session, campaign, account,
            pursue_anyway=set(payload.pursue_anyway),
            allow_without_signal=set(payload.allow_without_signal),
        )
    except (campaign_strategy.NotReadyError, demo.EgressBlockedError) as exc:
        raise _refused(exc) from exc
    except DifferentiationError as exc:
        await session.rollback()
        raise HTTPException(422, {"error": "not_differentiated", "message": str(exc)}) from exc
    await session.commit()
    return BuildOut(**asdict(outcome))


class BuildManyIn(BaseModel):
    """Several companies in one request, run concurrently."""

    account_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    #: Per contact, as the single-company route takes them.
    pursue_anyway: list[uuid.UUID] = Field(default_factory=list)
    allow_without_signal: list[uuid.UUID] = Field(default_factory=list)


class BuildManyOut(BaseModel):
    built: int
    failed: int
    seconds: float
    results: list[BuildOut] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict)


#: How many model calls to have in flight at once.
#:
#: The browser ran these one at a time, so a hundred contacts across sixty
#: companies meant sixty calls end to end — ten minutes of strategy before
#: drafting even began. Bounded rather than unlimited because each call is a
#: paid request against a rate limit, and because a failure should cost a few
#: calls, not a hundred.
BUILD_CONCURRENCY = 5


@router.post(
    "/campaigns/{campaign_id}/strategy/batch",
    response_model=BuildManyOut,
    dependencies=[Depends(requires("llm"))],
)
async def build_strategy_many(
    campaign_id: uuid.UUID, payload: BuildManyIn, session: AsyncSession = Depends(get_session)
):
    """Build strategy for several companies at once.

    Each company gets its own session: they are independent units of work, and
    one that fails — a model that returned nothing, a company nobody in the
    campaign belongs to — must not roll back the ones that succeeded beside it.

    The single-company route stays, and is still what the drawer calls. This is
    for the screen that builds a campaign's worth in one go.
    """
    import asyncio
    import time

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.services import demo, llm

    await _campaign(session, campaign_id)
    await llm.assert_may_call(session, "strategy_synthesis")

    engine = session.get_bind()
    engine = getattr(engine, "_async_engine", None) or session.bind or engine
    maker = async_sessionmaker(engine, expire_on_commit=False)
    limit = asyncio.Semaphore(BUILD_CONCURRENCY)

    started = time.monotonic()
    results: list[BuildOut] = []
    errors: dict[str, str] = {}

    async def one(account_id: uuid.UUID) -> None:
        async with limit, maker() as own:
            try:
                campaign = await _campaign(own, campaign_id)
                account = await _account(own, account_id)
                outcome = await campaign_strategy.build(
                    own, campaign, account,
                    pursue_anyway=set(payload.pursue_anyway),
                    allow_without_signal=set(payload.allow_without_signal),
                )
                await own.commit()
                results.append(BuildOut(**asdict(outcome)))
            except (
                campaign_strategy.NotReadyError,
                demo.EgressBlockedError,
                DifferentiationError,
                HTTPException,
            ) as exc:
                await own.rollback()
                errors[str(account_id)] = getattr(exc, "detail", None) or str(exc)
            except Exception as exc:  # noqa: BLE001 - one company must not stop the rest
                await own.rollback()
                log.warning(
                    "campaign_strategy.batch_failed campaign=%s account=%s err=%s",
                    campaign_id, account_id, exc,
                )
                errors[str(account_id)] = str(exc)

    await asyncio.gather(*(one(a) for a in dict.fromkeys(payload.account_ids)))

    return BuildManyOut(
        built=sum(1 for r in results if r.built),
        failed=len(errors),
        seconds=round(time.monotonic() - started, 1),
        results=results,
        errors=errors,
    )


class PersonDetailOut(BaseModel):
    person: PersonOut
    service_code: str | None = None
    icp_name: str | None = None
    icp_version: int | None = None
    threshold: float | None = None
    cap: int | None = None
    #: The company's score read for this campaign's ICP; None when not qualified.
    score: dict | None = None
    strategy: dict | None = None
    trigger_signals: list[dict] = Field(default_factory=list)
    versions: list[dict] = Field(default_factory=list)
    #: Every angle for this person, best first; one is selected (`docs/18`).
    angles: list[dict] = Field(default_factory=list)
    #: The one-sentence read of the company the angles hang off.
    account_angle: str | None = None


@router.get("/campaigns/{campaign_id}/people/{contact_id}", response_model=PersonDetailOut)
async def person_detail(
    campaign_id: uuid.UUID, contact_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    campaign = await _campaign(session, campaign_id)
    try:
        return PersonDetailOut(**await campaign_strategy.person_detail(session, campaign, contact_id))
    except campaign_strategy.NotReadyError as exc:
        raise HTTPException(404, str(exc)) from exc


class AngleIn(BaseModel):
    angle_id: uuid.UUID


@router.post("/campaigns/{campaign_id}/people/{contact_id}/angle")
async def select_angle(
    campaign_id: uuid.UUID,
    contact_id: uuid.UUID,
    payload: AngleIn,
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(current_user),
):
    """Pitch a different one of this person's angles. Saved drafts reopen —
    they argued the previous angle — and the answer says whether to rewrite."""
    campaign = await _campaign(session, campaign_id)
    try:
        outcome = await campaign_strategy.select_angle(session, campaign, contact_id, payload.angle_id)
    except campaign_strategy.AngleRefused as exc:
        raise _refused(exc) from exc
    if outcome["changed"]:
        await access.record(
            session, user, "strategy.angle_selected", "outreach_sequence", str(contact_id),
            {"campaign_id": str(campaign_id), "angle_id": str(payload.angle_id)},
        )
    await session.commit()
    return outcome
