"""What the pipeline spent, and what it got stuck on.

**It exists because a spend cap arrived as a surprise.** Tokens were recorded
and cheap; grounding is billed per request, is the larger part of a research
bill, and was recorded nowhere — so nothing on any screen could have shown a
number climbing toward a limit. This is the screen that could have.

Three rules it is built on.

**Nothing is estimated.** A cost is computed from a stored price and a counted
call, or it is reported as unpriced. A screen that guesses the expensive half
is how the gap went unnoticed in the first place, and a figure that looks
authoritative is the one nobody re-checks.

**History starts where measurement starts.** `llm_call.grounded` was added on
10 October; rows before it are `false` because nobody can truthfully say
otherwise. The response says so rather than letting a chart imply three quiet
weeks.

**A stuck run is the headline, not a footnote.** The deadlock that cost a
fifty-account run its eighteenth account produced no error, no timeout and no
log line — only a run that never finished. It is the first thing here.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.models.account import Account, Run
from app.models.config import LlmCall
from app.models.cost import ModelPrice, SerpCall
from app.models.research import ResearchCoverage

router = APIRouter(tags=["monitoring"])

#: A run open longer than this with nothing to show is reported as stuck.
#:
#: Four minutes because a healthy account takes about forty seconds and the
#: slowest observed was sixty-nine; the deadlock sat for thirty minutes before
#: anybody noticed. The point is to notice in one.
STUCK_AFTER_SECONDS = 240


class StageCost(BaseModel):
    scenario: str
    model: str
    calls: int
    failed: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    grounded_calls: int
    avg_seconds: float
    #: None when no price is stored for this model. Not zero — a missing price
    #: is not a free call, and showing it as one would understate the bill.
    cost: float | None


class FailureGroup(BaseModel):
    reason: str
    rows: int


class StuckRun(BaseModel):
    run_id: uuid.UUID
    account_id: uuid.UUID
    account_name: str
    stage: str
    status: str
    started_at: datetime
    open_seconds: int


class MonitoringOut(BaseModel):
    window_days: int
    since: datetime

    #: Runs open past `STUCK_AFTER_SECONDS`. The thing that has no other signal.
    stuck: list[StuckRun]
    runs_finished: int
    runs_failed: int

    stages: list[StageCost]
    calls: int
    failed_calls: int
    token_cost: float | None
    grounding_cost: float | None
    #: Models seen in the window with no row in the price sheet. Named, because
    #: the total is wrong by exactly these and silence would hide it.
    unpriced_models: list[str]
    currency: str
    price_version: int | None

    serp_credits: int
    serp_calls: int

    failures: list[FailureGroup]
    #: When the grounded flag began being recorded. Anything before it reads
    #: `false` because it was never measured, not because it was not grounded.
    grounded_since: datetime | None


def _cost(row, prices: dict) -> float | None:
    price = prices.get(row.model)
    if not price:
        return None
    tokens = (
        (row.input_tokens or 0) / 1_000_000 * float(price.get("input_per_m", 0))
        + (row.output_tokens or 0) / 1_000_000 * float(price.get("output_per_m", 0))
    )
    grounded = (row.grounded_calls or 0) * float(price.get("grounded_per_call", 0))
    return round(tokens + grounded, 4)


@router.get("/monitoring", response_model=MonitoringOut)
async def monitoring(
    days: int = Query(7, ge=1, le=90),
    session: AsyncSession = Depends(get_session),
):
    since = datetime.now(UTC) - timedelta(days=days)

    sheet = (
        await session.execute(select(ModelPrice).where(ModelPrice.is_active.is_(True)))
    ).scalar_one_or_none()
    prices: dict = (sheet.prices if sheet else {}) or {}

    # --- what the model cost, per stage ---
    rows = (
        await session.execute(
            select(
                LlmCall.scenario,
                LlmCall.model,
                func.count().label("calls"),
                func.count().filter(LlmCall.ok.is_(False)).label("failed"),
                func.coalesce(func.sum(LlmCall.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(LlmCall.output_tokens), 0).label("output_tokens"),
                func.coalesce(func.sum(LlmCall.cache_read_tokens), 0).label(
                    "cache_read_tokens"
                ),
                func.count().filter(LlmCall.grounded.is_(True)).label("grounded_calls"),
                func.coalesce(func.avg(LlmCall.duration_ms), 0).label("avg_ms"),
            )
            .where(LlmCall.created_at >= since)
            .group_by(LlmCall.scenario, LlmCall.model)
            .order_by(func.count().desc())
        )
    ).all()

    stages: list[StageCost] = []
    token_cost = 0.0
    grounding_cost = 0.0
    unpriced: list[str] = []
    for row in rows:
        cost = _cost(row, prices)
        if cost is None and row.model not in unpriced:
            unpriced.append(row.model)
        else:
            price = prices.get(row.model, {})
            token_cost += (
                (row.input_tokens or 0) / 1_000_000 * float(price.get("input_per_m", 0))
                + (row.output_tokens or 0)
                / 1_000_000
                * float(price.get("output_per_m", 0))
            )
            grounding_cost += (row.grounded_calls or 0) * float(
                price.get("grounded_per_call", 0)
            )
        stages.append(
            StageCost(
                scenario=row.scenario,
                model=row.model,
                calls=row.calls,
                failed=row.failed,
                input_tokens=int(row.input_tokens),
                output_tokens=int(row.output_tokens),
                cache_read_tokens=int(row.cache_read_tokens),
                grounded_calls=int(row.grounded_calls),
                avg_seconds=round(float(row.avg_ms) / 1000, 1),
                cost=cost,
            )
        )

    # --- runs that never finished ---
    open_runs = (
        await session.execute(
            select(Run, Account.name)
            .join(Account, Account.id == Run.account_id)
            .where(Run.finished_at.is_(None))
            .order_by(Run.started_at)
        )
    ).all()
    now = datetime.now(UTC)
    stuck = []
    for run, name in open_runs:
        started = run.started_at
        if started is None:
            continue
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        age = int((now - started).total_seconds())
        if age < STUCK_AFTER_SECONDS:
            continue
        stuck.append(
            StuckRun(
                run_id=run.id,
                account_id=run.account_id,
                account_name=name,
                stage=run.stage or "?",
                status=run.status or "?",
                started_at=started,
                open_seconds=age,
            )
        )

    finished = (
        await session.execute(
            select(
                func.count().filter(Run.status == "succeeded"),
                func.count().filter(Run.status == "failed"),
            ).where(Run.started_at >= since)
        )
    ).one()

    # --- families that failed, grouped by reason ---
    #
    # Grouped, not listed: thirty-nine rows of one refusal is one problem, and
    # a list of thirty-nine is a page nobody reads.
    failed_rows = (
        await session.execute(
            select(ResearchCoverage.detail, func.count())
            .join(Run, Run.id == ResearchCoverage.run_id)
            .where(ResearchCoverage.status == "failed", Run.started_at >= since)
            .group_by(ResearchCoverage.detail)
            .order_by(func.count().desc())
            .limit(12)
        )
    ).all()

    serp = (
        await session.execute(
            select(
                func.coalesce(func.sum(SerpCall.credits), 0),
                func.count(),
            ).where(SerpCall.created_at >= since)
        )
    ).one()

    grounded_since = (
        await session.execute(
            select(func.min(LlmCall.created_at)).where(LlmCall.grounded.is_(True))
        )
    ).scalar_one_or_none()

    return MonitoringOut(
        window_days=days,
        since=since,
        stuck=stuck,
        runs_finished=int(finished[0] or 0),
        runs_failed=int(finished[1] or 0),
        stages=stages,
        calls=sum(s.calls for s in stages),
        failed_calls=sum(s.failed for s in stages),
        token_cost=(round(token_cost, 2) if prices else None),
        grounding_cost=(round(grounding_cost, 2) if prices else None),
        unpriced_models=unpriced,
        currency=(sheet.currency if sheet else "USD"),
        price_version=(sheet.version if sheet else None),
        serp_credits=int(serp[0] or 0),
        serp_calls=int(serp[1] or 0),
        failures=[
            FailureGroup(reason=(detail or "no reason recorded")[:160], rows=count)
            for detail, count in failed_rows
        ],
        grounded_since=grounded_since,
    )
