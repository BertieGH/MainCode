from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_settings
from app.database import get_db
from app.models.article import Article
from app.models.feed_source import FeedSource
from app.schemas.article import ArticleOut, VerdictCount
from app.services.llm_provider import LLMQuotaExceeded, LLMServiceUnavailable
from app.services.rss_ingestion import _count_keyword_hits
from app.services.signal_extraction import extract_for_article_row

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
    limit: int = Query(100, le=500),
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
    query = query.order_by(Article.created_at.desc())
    result = await db.execute(query)
    rows = list(result.scalars().all())

    if keyword:
        needles = [k.strip().lower() for k in keyword if k and k.strip()]

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


@router.post("/articles/extract")
async def extract_articles(req: ExtractRequest, db: AsyncSession = Depends(get_db)):
    """Run AI extraction on selected articles (or all pending)."""
    query = select(Article)
    if req.all_pending:
        query = query.where(Article.verdict == "pending")
    elif req.article_ids:
        query = query.where(Article.id.in_(req.article_ids))
    else:
        raise HTTPException(status_code=400, detail="Provide article_ids or set all_pending=true")

    result = await db.execute(query)
    articles = result.scalars().all()

    counts = {"funding": 0, "not_funding": 0, "parse_failed": 0, "validation_failed": 0, "error": 0}
    quota_hit = False
    service_unavailable = False
    stop_message: str | None = None

    for article in articles:
        if quota_hit or service_unavailable:
            break
        try:
            verdict, _resp, _signal = await extract_for_article_row(db, article, force=req.force)
        except LLMQuotaExceeded as e:
            quota_hit = True
            stop_message = str(e)
            article.verdict = "quota_exceeded"
            article.llm_response = stop_message
            await db.commit()
            break
        except LLMServiceUnavailable as e:
            service_unavailable = True
            stop_message = str(e)
            article.verdict = "service_unavailable"
            article.llm_response = stop_message
            await db.commit()
            break
        counts[verdict] = counts.get(verdict, 0) + 1

    if quota_hit:
        msg = f"Hit LLM quota after {sum(counts.values())} articles. {stop_message}"
    elif service_unavailable:
        msg = (
            f"LLM service returned 5xx after retries ({sum(counts.values())} articles processed first). "
            f"This is usually a brief demand spike — try again in a few minutes. {stop_message}"
        )
    else:
        msg = None

    return {
        "status": "warning" if (quota_hit or service_unavailable) else "ok",
        "processed": sum(counts.values()),
        "total_requested": len(articles),
        "counts": counts,
        "message": msg,
    }
