import asyncio
import logging
from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete as sql_delete, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.background import fire_and_forget
from app.database import async_session, get_db
from app.models.backfill_run import BackfillRun
from app.models.signal import Signal
from app.schemas.feed import BackfillRunOut
from app.schemas.signal import SignalOut
from app.models.article import Article
from app.services.llm_provider import LLMQuotaExceeded, LLMServiceUnavailable
from app.services.rss_ingestion import ingest_all
from app.services.signal_extraction import (
    _backfill_location_via_llm,
    get_primary_provider,
    playwright_stats,
    resolve_article_content,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/signals", response_model=list[SignalOut])
async def list_signals(
    industry: str | None = Query(None),
    funding_round: str | None = Query(None),
    amount_min: int | None = Query(None),
    amount_max: int | None = Query(None),
    location: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    limit: int = Query(500, le=2000),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
):
    query = select(Signal)

    if industry:
        query = query.where(Signal.industry == industry)
    if funding_round:
        query = query.where(Signal.funding_round == funding_round)
    if amount_min is not None:
        query = query.where(Signal.amount >= amount_min)
    if amount_max is not None:
        query = query.where(Signal.amount <= amount_max)
    if location:
        query = query.where(Signal.location.ilike(f"%{location}%"))
    if date_from:
        query = query.where(Signal.date >= date_from)
    if date_to:
        query = query.where(Signal.date <= date_to)

    query = query.order_by(Signal.date.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/signals/{signal_id}", response_model=SignalOut)
async def get_signal(signal_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Signal).where(Signal.id == signal_id))
    signal = result.scalar_one_or_none()
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    return signal


@router.get("/signals/stats/playwright")
async def get_playwright_stats():
    """Process-lifetime Playwright health counters.

    Useful for spotting silent fetch degradation in a long-running API:
    rising `empty_results` or `failures` while `successes` plateaus is the
    signature of the kind of browser-pool problem we hit while debugging
    Magrathea's missing location.
    """
    return playwright_stats.snapshot()


@router.post("/signals/ingest")
async def ingest_signals(db: AsyncSession = Depends(get_db)):
    """Trigger ingestion: fetch all active feeds, extract signals via LLM."""
    return await ingest_all(db)


class BulkDeleteRequest(BaseModel):
    ids: list[UUID]


@router.delete("/signals/{signal_id}")
async def delete_signal(signal_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Signal).where(Signal.id == signal_id))
    signal = result.scalar_one_or_none()
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    await db.delete(signal)
    await db.commit()
    return {"status": "deleted", "id": str(signal_id)}


@router.post("/signals/bulk-delete")
async def bulk_delete_signals(payload: BulkDeleteRequest, db: AsyncSession = Depends(get_db)):
    if not payload.ids:
        return {"deleted": 0}
    result = await db.execute(sql_delete(Signal).where(Signal.id.in_(payload.ids)))
    await db.commit()
    return {"deleted": result.rowcount or 0}


@router.get("/signals/stats/summary")
async def signal_stats(db: AsyncSession = Depends(get_db)):
    """Get aggregate stats for signal log."""
    total = await db.execute(select(func.count(Signal.id)))
    total_amount = await db.execute(select(func.sum(Signal.amount)))
    industries = await db.execute(select(func.count(func.distinct(Signal.industry))))

    return {
        "total_signals": total.scalar() or 0,
        "total_funding": total_amount.scalar() or 0,
        "unique_industries": industries.scalar() or 0,
    }


# ---------- Location backfill ----------
# Mirrors the country-backfill pattern in articles.py: chunked async work
# with bounded LLM concurrency, isolated AsyncSessions per coroutine (so
# the worker doesn't deadlock the DB pool), and BackfillRun row tracking.

_LOC_BACKFILL_CHUNK = 5
_LOC_BACKFILL_LLM_CONCURRENCY = 4


class BackfillLocationRequest(BaseModel):
    """Either a list of signal_ids to backfill, or a `limit` to auto-pick the
    most recent rows with empty location.

    `force=True` reprocesses signals even if they already have a location
    (useful after tightening the prompt to fix earlier hallucinations).
    Combined with `limit`, this picks the most-recent rows regardless of
    current location value.
    """
    signal_ids: list[UUID] | None = None
    limit: int = 100
    force: bool = False


async def _run_location_backfill_inproc(run_id: UUID, signal_ids: list[UUID]) -> None:
    """Background worker for /signals/backfill-locations.

    For each target Signal, runs `_backfill_location_via_llm` against the
    cached `Signal.raw_text` (populated at extraction time) plus the company
    name. No HTTP fetches — pure LLM calls.

    Each coroutine opens its OWN AsyncSession; sharing the worker session
    across `asyncio.gather` deadlocks SQLAlchemy (same fix we made for
    /articles/extract).
    """
    sem = asyncio.Semaphore(_LOC_BACKFILL_LLM_CONCURRENCY)
    provider = get_primary_provider()
    if not provider:
        async with async_session() as db:
            run = (
                await db.execute(select(BackfillRun).where(BackfillRun.id == run_id))
            ).scalar_one_or_none()
            if run:
                run.status = "error"
                run.message = "No LLM provider configured"
                run.finished_at = datetime.now(timezone.utc)
                await db.commit()
        return

    async def _backfill_one(sig_id: UUID) -> tuple[UUID, str, Exception | None]:
        async with sem:
            async with async_session() as own_db:
                sig = (
                    await own_db.execute(select(Signal).where(Signal.id == sig_id))
                ).scalar_one_or_none()
                if not sig:
                    return sig_id, "", None

                text = sig.raw_text or ""

                # If raw_text is too short to plausibly contain HQ info,
                # re-fetch the article body fresh. This handles older
                # ingestion runs where the body fetcher silently failed
                # (e.g. Google News RSS that needs Playwright to resolve).
                # Anything < 500 chars is almost certainly just the RSS
                # title-only summary HTML.
                if len(text) < 500 and sig.source_url:
                    art = (
                        await own_db.execute(
                            select(Article).where(Article.signal_id == sig_id)
                        )
                    ).scalars().first()
                    summary = (art.summary if art else "") or ""
                    try:
                        fresh = await resolve_article_content(sig.source_url, summary)
                        if fresh and len(fresh) > len(text):
                            text = fresh
                            # Cache the fresh body so future backfills /
                            # country tagging don't pay the fetch cost again.
                            sig.raw_text = text[:5000]
                            await own_db.commit()
                    except Exception as e:  # noqa: BLE001
                        # Best-effort — fall through to LLM with whatever we have.
                        logger.warning("body refetch failed for signal %s: %r", sig_id, e)
                    else:
                        logger.info(
                            "body refetch for signal %s: was=%d, fresh=%d",
                            sig_id, len(sig.raw_text or ""), len(text)
                        )

                try:
                    location = await _backfill_location_via_llm(
                        sig.company_name or "",
                        text,
                        provider,
                    )
                    if location:
                        sig.location = location[:255]
                        await own_db.commit()
                        return sig_id, location, None
                    return sig_id, "", None
                except (LLMQuotaExceeded, LLMServiceUnavailable) as e:
                    return sig_id, "", e
                except Exception as e:  # noqa: BLE001
                    logger.exception("location_backfill failed for signal %s", sig_id)
                    return sig_id, "", e

    async with async_session() as db:
        run = (
            await db.execute(select(BackfillRun).where(BackfillRun.id == run_id))
        ).scalar_one_or_none()
        if not run:
            return

        for start in range(0, len(signal_ids), _LOC_BACKFILL_CHUNK):
            batch = signal_ids[start : start + _LOC_BACKFILL_CHUNK]
            results = await asyncio.gather(*[_backfill_one(sid) for sid in batch])

            chunk_quota_hit = False
            quota_msg: str | None = None
            for _sig_id, loc, err in results:
                if err is None:
                    if loc:
                        run.updated += 1
                        run.via_llm += 1
                    else:
                        run.still_unknown += 1
                elif isinstance(err, LLMQuotaExceeded):
                    chunk_quota_hit = True
                    quota_msg = str(err)
                else:
                    # 5xx after retries OR unexpected: count as still-unknown
                    # but keep going — same tolerance as the country backfill.
                    run.still_unknown += 1
                run.processed += 1

            await db.commit()

            if chunk_quota_hit:
                run.status = "warning"
                run.message = (
                    f"Hit LLM quota after {run.processed}/{run.total} signals. {quota_msg}"
                )
                run.finished_at = datetime.now(timezone.utc)
                await db.commit()
                return

        # Done — pick a status
        if run.still_unknown > 0 and run.updated == 0:
            run.status = "warning"
            run.message = (
                f"No locations recovered ({run.still_unknown} unknown). "
                "Check the LLM provider config or article content quality."
            )
        else:
            run.status = "done"
            if run.still_unknown > 0:
                run.message = (
                    f"Recovered {run.updated}/{run.total} locations; "
                    f"{run.still_unknown} still unknown."
                )
        run.finished_at = datetime.now(timezone.utc)
        await db.commit()


@router.post("/signals/backfill-locations")
async def backfill_signal_locations(
    payload: BackfillLocationRequest, db: AsyncSession = Depends(get_db)
):
    """Kick off a background location-backfill job and return the run id.

    Two modes:
      - Default (no `signal_ids`): pick the most recent rows with empty
        location, up to `limit` (capped at 500).
      - Selected (`signal_ids` provided): run on exactly those rows
        regardless of current location value.

    Returns immediately with `{run_id, status, total}`. Frontend polls
    GET /signals/backfill-runs/{run_id} for progress.
    """
    if not get_primary_provider():
        raise HTTPException(status_code=400, detail="No LLM provider configured")

    if payload.signal_ids:
        rows = (
            await db.execute(
                select(Signal.id).where(Signal.id.in_(payload.signal_ids))
            )
        ).all()
    else:
        n_take = max(1, min(payload.limit, 500))
        query = select(Signal.id)
        if not payload.force:
            query = query.where((Signal.location == "") | (Signal.location.is_(None)))
        query = query.order_by(Signal.created_at.desc()).limit(n_take)
        rows = (await db.execute(query)).all()

    target_ids: list[UUID] = [r[0] for r in rows]
    if not target_ids:
        return {"run_id": None, "status": "noop", "total": 0}

    run = BackfillRun(
        kind="location",
        status="running",
        total=len(target_ids),
        trigger="manual",
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    fire_and_forget(
        _run_location_backfill_inproc(run.id, target_ids),
        name=f"location_backfill:{run.id}",
    )
    return {"run_id": str(run.id), "status": "queued", "total": len(target_ids)}


@router.get("/signals/backfill-runs/{run_id}", response_model=BackfillRunOut)
async def get_signal_backfill_run(run_id: UUID, db: AsyncSession = Depends(get_db)):
    run = (
        await db.execute(select(BackfillRun).where(BackfillRun.id == run_id))
    ).scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Backfill run not found")
    return run
