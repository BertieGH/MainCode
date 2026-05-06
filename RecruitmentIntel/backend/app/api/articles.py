import asyncio
import logging
from datetime import date, datetime, time, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.background import fire_and_forget
from app.config import settings as app_settings
from app.database import async_session, get_db
from app.models.article import Article
from app.models.backfill_run import BackfillRun
from app.models.extraction_run import ExtractionRun
from app.models.feed_source import FeedSource
from app.schemas.article import ArticleOut, VerdictCount
from app.schemas.feed import BackfillRunOut
from app.services.llm_provider import LLMQuotaExceeded, LLMServiceUnavailable
from app.services.rss_ingestion import _count_keyword_hits
from app.services.signal_extraction import extract_for_article_row
from app.services.url_normalize import normalize_url

logger = logging.getLogger(__name__)

router = APIRouter()


class ExtractRequest(BaseModel):
    """Either a list of article IDs to extract, or all_pending=True for everything pending.

    force=True wipes any existing Signal row for the same URL and re-runs the LLM,
    useful after improving the extraction prompt or switching LLM provider.
    """
    article_ids: list[UUID] | None = None
    all_pending: bool = False
    force: bool = False


class DeleteRequest(BaseModel):
    article_ids: list[UUID]


@router.get("/articles", response_model=list[ArticleOut])
async def list_articles(
    run_id: UUID | None = Query(None),
    feed_id: UUID | None = Query(None),
    verdict: str | None = Query(None),
    keyword: list[str] = Query(default_factory=list),
    keyword_mode: Literal["any", "all"] = Query("any"),
    q: str | None = Query(None, description="Case-insensitive search over title + summary"),
    date_from: date | None = Query(None, description="Inclusive lower bound on created_at (YYYY-MM-DD)"),
    date_to: date | None = Query(None, description="Inclusive upper bound on created_at (YYYY-MM-DD)"),
    country: str | None = Query(None, description="ISO-2 code (US/GB/IN/...) or '(empty)' for unset"),
    limit: int = Query(500, le=2000),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
):
    query = select(Article)
    if run_id:
        query = query.where(Article.ingestion_run_id == run_id)
    if feed_id:
        query = query.where(Article.feed_source_id == feed_id)
    if verdict:
        query = query.where(Article.verdict == verdict)
    if country:
        query = query.where(Article.country == ("" if country == "(empty)" else country))
    if q and q.strip():
        needle = f"%{q.strip().lower()}%"
        query = query.where(
            or_(func.lower(Article.title).like(needle), func.lower(Article.summary).like(needle))
        )
    if date_from:
        query = query.where(Article.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        query = query.where(Article.created_at <= datetime.combine(date_to, time.max))
    query = query.order_by(Article.created_at.desc())

    needles = (
        [k.strip().lower() for k in keyword if k and k.strip()]
        if keyword
        else []
    )

    # Postgres path: push the keyword filter into SQL via JSONB ?| (any) /
    # ?& (all) operators served by the GIN index on articles.keyword_hits
    # (alembic 017). Lets us also push offset/limit into the query rather
    # than materializing every match.
    if needles and db.bind.dialect.name == "postgresql":
        from sqlalchemy import text
        op = "?&" if keyword_mode == "all" else "?|"
        query = query.where(
            text(f"articles.keyword_hits {op} :needles").bindparams(needles=needles)
        )
        query = query.offset(offset).limit(limit)
        result = await db.execute(query)
        return list(result.scalars().all())

    # SQLite (dev) fallback: load matching rows then post-filter in Python.
    # Same semantics as before — kept verbatim for parity.
    result = await db.execute(query)
    rows = list(result.scalars().all())

    if needles:
        def _matches(a: Article) -> bool:
            hits = a.keyword_hits or {}
            lower = {str(k).lower(): int(v or 0) for k, v in hits.items()}
            counts = [lower.get(n, 0) for n in needles]
            if keyword_mode == "all":
                return all(c > 0 for c in counts)
            return any(c > 0 for c in counts)

        rows = [a for a in rows if _matches(a)]

    return rows[offset : offset + limit]


@router.get("/articles/verdict-summary", response_model=list[VerdictCount])
async def verdict_summary(
    run_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    query = select(Article.verdict, func.count(Article.id).label("count")).group_by(Article.verdict)
    if run_id:
        query = query.where(Article.ingestion_run_id == run_id)
    query = query.order_by(func.count(Article.id).desc())
    result = await db.execute(query)
    return [VerdictCount(verdict=row[0], count=row[1]) for row in result.fetchall()]


@router.delete("/articles/{article_id}")
async def delete_article(article_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Article).where(Article.id == article_id))
    article = result.scalar_one_or_none()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    await db.delete(article)
    await db.commit()
    return {"status": "deleted", "id": str(article_id)}


@router.post("/articles/delete-batch")
async def delete_articles_batch(req: DeleteRequest, db: AsyncSession = Depends(get_db)):
    if not req.article_ids:
        return {"status": "ok", "deleted": 0}
    result = await db.execute(select(Article).where(Article.id.in_(req.article_ids)))
    rows = result.scalars().all()
    for row in rows:
        await db.delete(row)
    await db.commit()
    return {"status": "ok", "deleted": len(rows)}


class BackfillCountryRequest(BaseModel):
    limit: int = 100
    # When provided, run only on these specific articles (ignores limit + the
    # "country == ''" gate so the user can re-tag rows the LLM got wrong).
    article_ids: list[UUID] | None = None


_BACKFILL_CHUNK = 5
_BACKFILL_LLM_CONCURRENCY = 4


async def _run_country_backfill_inproc(run_id: UUID, article_ids: list[UUID]) -> None:
    """Background worker for /articles/backfill-countries.

    Iterates the target articles in chunks. For each article, tries the free
    `detect_country_from_location` regex against the linked Signal first; only
    falls back to the LLM when that misses. Within each chunk the LLM calls
    are run concurrently (bounded by a small semaphore) and results are
    committed per chunk so partial progress survives a crash.
    """
    from app.models.signal import Signal
    from app.services.country_detection import detect_country_from_location
    from app.services.signal_extraction import _backfill_country_via_llm, get_primary_provider

    provider = get_primary_provider()
    if not provider:
        async with async_session() as db:
            run = (await db.execute(select(BackfillRun).where(BackfillRun.id == run_id))).scalar_one_or_none()
            if run:
                run.status = "error"
                run.message = "No LLM provider configured"
                run.finished_at = datetime.now(timezone.utc)
                await db.commit()
        return

    sem = asyncio.Semaphore(_BACKFILL_LLM_CONCURRENCY)

    async def _llm_one(company: str, location: str, article_text: str) -> str:
        async with sem:
            return await _backfill_country_via_llm(company, location, article_text, provider)

    async with async_session() as db:
        run = (await db.execute(select(BackfillRun).where(BackfillRun.id == run_id))).scalar_one_or_none()
        if not run:
            return

        quota_message: str | None = None
        fatal_error: str | None = None

        for start in range(0, len(article_ids), _BACKFILL_CHUNK):
            batch_ids = article_ids[start : start + _BACKFILL_CHUNK]
            arts = (
                await db.execute(select(Article).where(Article.id.in_(batch_ids)))
            ).scalars().all()
            if not arts:
                run.processed += len(batch_ids)
                await db.commit()
                continue

            sig_ids = [a.signal_id for a in arts if a.signal_id]
            sig_by_id: dict[UUID, Signal] = {}
            if sig_ids:
                sig_rows = (
                    await db.execute(select(Signal).where(Signal.id.in_(sig_ids)))
                ).scalars().all()
                sig_by_id = {s.id: s for s in sig_rows}

            llm_targets: list[tuple[Article, str, str, str]] = []
            for art in arts:
                sig = sig_by_id.get(art.signal_id) if art.signal_id else None
                location = (sig.location if sig else "") or ""
                if location:
                    code = detect_country_from_location(location)
                    if code:
                        art.country = code[:8]
                        run.updated += 1
                        run.via_location += 1
                        run.processed += 1
                        continue
                company = (sig.company_name if sig else "") or ""
                article_text = f"{art.title or ''}\n\n{art.summary or ''}"
                llm_targets.append((art, company, location, article_text))

            if llm_targets:
                try:
                    codes = await asyncio.gather(
                        *[_llm_one(c, l, t) for (_a, c, l, t) in llm_targets]
                    )
                except LLMQuotaExceeded as e:
                    quota_message = str(e)
                    # Whatever this chunk did before quota hit is already in
                    # `art.country` for shortcut hits, but the LLM batch is lost.
                    # Mark the chunk as processed and bail.
                    run.processed += len(llm_targets)
                    run.still_unknown += len(llm_targets)
                    await db.commit()
                    break
                except (LLMServiceUnavailable, Exception) as e:
                    fatal_error = f"{type(e).__name__}: {e}"
                    run.processed += len(llm_targets)
                    run.still_unknown += len(llm_targets)
                    await db.commit()
                    break

                for (art, _c, _l, _t), code in zip(llm_targets, codes):
                    if code:
                        art.country = code[:8]
                        run.updated += 1
                        run.via_llm += 1
                    else:
                        run.still_unknown += 1
                    run.processed += 1

            await db.commit()

        if quota_message:
            run.status = "warning"
            run.message = (
                f"LLM quota hit after {run.processed}/{run.total}. "
                f"{run.via_location} via location, {run.via_llm} via LLM. {quota_message}"
            )
        elif fatal_error:
            run.status = "error"
            run.message = (
                f"Stopped after {run.processed}/{run.total}. "
                f"{run.via_location} via location, {run.via_llm} via LLM. {fatal_error}"
            )
        else:
            run.status = "done"
            run.message = (
                f"{run.via_location} via location, {run.via_llm} via LLM"
            )
        run.finished_at = datetime.now(timezone.utc)
        await db.commit()


@router.post("/articles/backfill-countries")
async def backfill_article_countries(
    payload: BackfillCountryRequest, db: AsyncSession = Depends(get_db)
):
    """Kick off a background country-backfill job and return the run id.

    Two modes (unchanged):
      - Default (no `article_ids`): pick the most recent untagged articles, up
        to `limit`. Cost-bounded.
      - Selected (`article_ids` provided): run on exactly those rows regardless
        of current `country` value.

    Returns immediately with `{run_id, status, total}`. The frontend polls
    `GET /articles/backfill-runs/{run_id}` for progress.
    """
    from app.services.signal_extraction import get_primary_provider

    provider = get_primary_provider()
    if not provider:
        raise HTTPException(status_code=400, detail="No LLM provider configured")

    if payload.article_ids:
        rows = (
            await db.execute(
                select(Article.id).where(Article.id.in_(payload.article_ids))
            )
        ).all()
    else:
        n_take = max(1, min(payload.limit, 500))
        rows = (
            await db.execute(
                select(Article.id)
                .where(Article.country == "")
                .order_by(Article.created_at.desc())
                .limit(n_take)
            )
        ).all()

    target_ids: list[UUID] = [r[0] for r in rows]
    if not target_ids:
        return {"run_id": None, "status": "noop", "total": 0}

    run = BackfillRun(
        kind="country",
        status="running",
        total=len(target_ids),
        trigger="manual",
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    fire_and_forget(
        _run_country_backfill_inproc(run.id, target_ids),
        name=f"country_backfill:{run.id}",
    )
    return {"run_id": str(run.id), "status": "queued", "total": len(target_ids)}


@router.get("/articles/backfill-runs/{run_id}", response_model=BackfillRunOut)
async def get_backfill_run(run_id: UUID, db: AsyncSession = Depends(get_db)):
    run = (
        await db.execute(select(BackfillRun).where(BackfillRun.id == run_id))
    ).scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Backfill run not found")
    return run


@router.post("/articles/rescore-keywords")
async def rescore_article_keywords(db: AsyncSession = Depends(get_db)):
    """Recompute `keyword_hits` on every Article against the current global keyword set.

    Pure scan of stored title + summary — no LLM calls. Lets the user refresh
    historical articles after changing global scrape keywords in Settings.
    For articles whose feed still has per-feed keywords but no globals configured,
    falls back to the feed's keywords so the stats column isn't silently blanked.
    """
    globals_ = app_settings.global_scrape_keywords or []

    # Preload feed keyword lists so we don't issue one query per article.
    feed_rows = await db.execute(select(FeedSource.id, FeedSource.keywords))
    feed_keywords_by_id = {fid: (kws or []) for fid, kws in feed_rows.fetchall()}

    result = await db.execute(select(Article))
    articles = list(result.scalars().all())

    updated = 0
    for a in articles:
        kws = globals_ or feed_keywords_by_id.get(a.feed_source_id, [])
        new_hits = _count_keyword_hits(a.title or "", a.summary or "", kws)
        if (a.keyword_hits or {}) != new_hits:
            a.keyword_hits = new_hits
            updated += 1

    await db.commit()
    return {"status": "ok", "updated": updated, "total": len(articles)}


class DedupeRequest(BaseModel):
    dry_run: bool = False


@router.post("/articles/dedupe")
async def dedupe_articles(payload: DedupeRequest, db: AsyncSession = Depends(get_db)):
    """Collapse duplicate Article rows that share a normalized URL.

    For each group with >1 row, keeps one "winner": prefer a row already linked to a
    Signal (so we don't orphan extracted data), otherwise the oldest row. Other rows
    are deleted. `dry_run=true` reports counts without mutating.
    """
    rows = (
        await db.execute(
            select(Article.id, Article.url, Article.signal_id, Article.created_at)
            .order_by(Article.created_at.asc())
        )
    ).all()

    groups: dict[str, list[tuple]] = {}
    for r in rows:
        key = normalize_url(r.url or "")
        if not key:
            continue
        groups.setdefault(key, []).append(r)

    delete_ids: list[UUID] = []
    groups_with_dupes = 0
    for key, members in groups.items():
        if len(members) < 2:
            continue
        groups_with_dupes += 1
        keeper = next((m for m in members if m.signal_id is not None), members[0])
        for m in members:
            if m.id != keeper.id:
                delete_ids.append(m.id)

    if not payload.dry_run and delete_ids:
        await db.execute(Article.__table__.delete().where(Article.id.in_(delete_ids)))
        await db.commit()

    return {
        "groups_with_dupes": groups_with_dupes,
        "kept": groups_with_dupes,
        "deleted": len(delete_ids),
        "dry_run": payload.dry_run,
    }


# Batched extraction tuning. Per the analysis in the implementation plan:
#   - Chunk 25, concurrency 4 → ~110s for 100 articles, blast radius 25/100 on 503.
#   - 503 in one chunk no longer aborts the entire run.
_EXTRACT_CHUNK = 25
_EXTRACT_LLM_CONCURRENCY = 4


async def _extract_one_isolated(art_id: UUID, force: bool) -> tuple[UUID, str, Exception | None]:
    """Run extract_for_article_row in its OWN AsyncSession.

    Critical for safe concurrency: SQLAlchemy AsyncSession is single-threaded.
    extract_for_article_row does multiple SELECT/COMMIT calls; sharing one
    session across `asyncio.gather` coroutines deadlocks the connection pool
    and blocks every other request to the API.
    """
    async with async_session() as own_db:
        art = (
            await own_db.execute(select(Article).where(Article.id == art_id))
        ).scalar_one_or_none()
        if not art:
            return art_id, "missing", None
        try:
            verdict, _resp, _signal = await extract_for_article_row(own_db, art, force=force)
            return art_id, verdict, None
        except (LLMQuotaExceeded, LLMServiceUnavailable) as e:
            return art_id, "error", e
        except Exception as e:  # noqa: BLE001
            logger.exception("_extract_one_isolated unexpected failure for article %s", art_id)
            return art_id, "error", e


async def _run_extraction_inproc(run_id: UUID, article_ids: list[UUID], force: bool) -> None:
    """Background worker for /articles/extract.

    Iterates the target IDs in chunks of _EXTRACT_CHUNK. Inside each chunk,
    `_EXTRACT_LLM_CONCURRENCY` extractions run concurrently — each in its own
    AsyncSession (see `_extract_one_isolated`). The outer session is reserved
    for updating the ExtractionRun progress row only.

    A 5xx batch increments `service_unavailable` and the run continues to
    the next batch instead of aborting (key behavior change vs sequential).
    """
    sem = asyncio.Semaphore(_EXTRACT_LLM_CONCURRENCY)

    async def _extract_with_sem(art_id: UUID):
        async with sem:
            return await _extract_one_isolated(art_id, force)

    async with async_session() as db:
        run = (
            await db.execute(select(ExtractionRun).where(ExtractionRun.id == run_id))
        ).scalar_one_or_none()
        if not run:
            return

        quota_message: str | None = None

        for start in range(0, len(article_ids), _EXTRACT_CHUNK):
            batch_ids = article_ids[start : start + _EXTRACT_CHUNK]
            results = await asyncio.gather(
                *[_extract_with_sem(aid) for aid in batch_ids]
            )

            chunk_quota_hit = False
            for art_id, verdict, err in results:
                if err is None:
                    if verdict in ("funding", "not_funding", "parse_failed", "validation_failed"):
                        setattr(run, verdict, getattr(run, verdict) + 1)
                    elif verdict == "missing":
                        # Article ID not found (was deleted between selection and run start)
                        pass
                    else:
                        run.error += 1
                elif isinstance(err, LLMQuotaExceeded):
                    # Quota is global — bail the entire run after this chunk.
                    chunk_quota_hit = True
                    quota_message = str(err)
                    # Tag this article so the user can find which one tripped it.
                    await db.execute(
                        select(Article).where(Article.id == art_id)
                    )  # warm cache
                    art_row = (
                        await db.execute(select(Article).where(Article.id == art_id))
                    ).scalar_one_or_none()
                    if art_row:
                        art_row.verdict = "quota_exceeded"
                        art_row.llm_response = quota_message
                elif isinstance(err, LLMServiceUnavailable):
                    # 503 after retries on THIS article — record but keep going.
                    run.service_unavailable += 1
                    art_row = (
                        await db.execute(select(Article).where(Article.id == art_id))
                    ).scalar_one_or_none()
                    if art_row:
                        art_row.verdict = "service_unavailable"
                        art_row.llm_response = str(err)
                else:
                    run.error += 1

                run.processed += 1

            await db.commit()

            if chunk_quota_hit:
                run.status = "quota_exceeded"
                run.message = f"Hit LLM quota after {run.processed}/{run.total} articles. {quota_message}"
                run.finished_at = datetime.now(timezone.utc)
                await db.commit()
                return

        # Done — pick a status based on what happened.
        if run.service_unavailable > 0 or run.error > 0:
            run.status = "warning"
            run.message = (
                f"Completed with {run.service_unavailable} service-unavailable + "
                f"{run.error} error articles. The 503s are usually a brief Gemini demand spike — "
                f"re-run those rows individually in a few minutes."
            )
        else:
            run.status = "done"
            run.message = None
        run.finished_at = datetime.now(timezone.utc)
        await db.commit()


@router.post("/articles/extract")
async def extract_articles(req: ExtractRequest, db: AsyncSession = Depends(get_db)):
    """Run AI extraction on selected articles (or all pending) in batches.

    Returns immediately with `{run_id, status, total}`. The frontend polls
    `GET /articles/extract-runs/{run_id}` for progress.

    Per-batch DB commits + 503-tolerant batches mean a transient Gemini blip
    no longer wipes a 100-article run.
    """
    query = select(Article.id)
    if req.all_pending:
        query = query.where(Article.verdict == "pending")
    elif req.article_ids:
        query = query.where(Article.id.in_(req.article_ids))
    else:
        raise HTTPException(status_code=400, detail="Provide article_ids or set all_pending=true")

    rows = (await db.execute(query)).all()
    target_ids: list[UUID] = [r[0] for r in rows]
    if not target_ids:
        return {"run_id": None, "status": "noop", "total": 0}

    run = ExtractionRun(
        status="running",
        total=len(target_ids),
        trigger="manual",
        force=req.force,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    fire_and_forget(
        _run_extraction_inproc(run.id, target_ids, req.force),
        name=f"extract:{run.id}",
    )
    return {"run_id": str(run.id), "status": "queued", "total": len(target_ids)}


@router.get("/articles/extract-runs/{run_id}")
async def get_extraction_run(run_id: UUID, db: AsyncSession = Depends(get_db)):
    run = (
        await db.execute(select(ExtractionRun).where(ExtractionRun.id == run_id))
    ).scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Extraction run not found")
    return {
        "id": str(run.id),
        "status": run.status,
        "total": run.total,
        "processed": run.processed,
        "funding": run.funding,
        "not_funding": run.not_funding,
        "parse_failed": run.parse_failed,
        "validation_failed": run.validation_failed,
        "service_unavailable": run.service_unavailable,
        "error": run.error,
        "message": run.message,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "force": run.force,
    }
