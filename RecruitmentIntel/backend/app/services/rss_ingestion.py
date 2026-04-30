import logging
from datetime import datetime, timezone

import feedparser
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import Article
from app.models.feed_source import FeedSource
from app.models.ingestion_run import IngestionRun
from app.models.signal import Signal
from app.services.url_normalize import normalize_url

logger = logging.getLogger(__name__)

__all__ = [
    "fetch_feed",
    "get_existing_urls",
    "filter_new_articles",
    "update_feed_status",
    "ingest_all",
]

MAX_RETRIES = 3
RETRY_DELAYS = [5, 15, 30]


async def fetch_feed(feed: FeedSource) -> list[dict]:
    """Fetch and parse an RSS feed. Returns list of raw article dicts."""
    for attempt in range(MAX_RETRIES):
        try:
            parsed = feedparser.parse(feed.url)
            if parsed.bozo and not parsed.entries:
                # feedparser couldn't parse — try raw HTTP fallback
                return await _http_fallback(feed.url)
            articles = []
            for entry in parsed.entries:
                articles.append({
                    "title": entry.get("title", ""),
                    "url": entry.get("link", ""),
                    "summary": entry.get("summary", entry.get("description", "")),
                    "published": entry.get("published", ""),
                })
            return articles
        except Exception as e:
            logger.warning(f"Feed fetch attempt {attempt + 1} failed for {feed.name}: {e}")
            if attempt < MAX_RETRIES - 1:
                import asyncio
                await asyncio.sleep(RETRY_DELAYS[attempt])
    return []


async def _http_fallback(url: str) -> list[dict]:
    """Fallback: fetch raw XML via httpx and parse manually."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "xml")
        articles = []
        for item in soup.find_all("item"):
            articles.append({
                "title": item.find("title").text if item.find("title") else "",
                "url": item.find("link").text if item.find("link") else "",
                "summary": item.find("description").text if item.find("description") else "",
                "published": item.find("pubDate").text if item.find("pubDate") else "",
            })
        return articles
    except Exception as e:
        logger.error(f"HTTP fallback failed for {url}: {e}")
        return []


async def get_existing_urls(db: AsyncSession) -> set[str]:
    """Normalized URLs already seen — both extracted Signals and raw Articles.

    Including Article.url is what stops duplicate rows from accumulating in the
    News Log when the same RSS item gets re-fetched after verdicting as
    not_funding / keyword_filtered (no Signal was created, so the Signal-only
    set used to miss it).
    """
    sig_urls = (await db.execute(select(Signal.source_url))).scalars().all()
    art_urls = (await db.execute(select(Article.url))).scalars().all()
    return {normalize_url(u) for u in [*sig_urls, *art_urls] if u}


async def filter_new_articles(articles: list[dict], existing_urls: set[str]) -> list[dict]:
    """Remove already-ingested articles (compared on normalized URL)."""
    return [a for a in articles if a.get("url") and normalize_url(a["url"]) not in existing_urls]


async def update_feed_status(db: AsyncSession, feed: FeedSource, success: bool):
    """Update feed health tracking."""
    if success:
        feed.last_fetched = datetime.now(timezone.utc)
        feed.consecutive_failures = 0
    else:
        feed.consecutive_failures += 1
    await db.commit()


def _count_keyword_hits(title: str, summary: str, keywords: list[str]) -> dict[str, int]:
    """Case-insensitive substring count of each keyword in title+summary.

    Mirrors the same matching semantics the ingestion keyword filter uses,
    so a keyword with count 0 = this article would have been filtered out
    if this was the only keyword configured.
    """
    if not keywords:
        return {}
    haystack = f"{title}\n{summary}".lower()
    hits: dict[str, int] = {}
    for kw in keywords:
        needle = kw.strip().lower()
        if not needle:
            continue
        hits[kw] = haystack.count(needle)
    return hits


async def _record_article(
    db: AsyncSession,
    run_id,
    feed: FeedSource,
    article: dict,
    verdict: str,
    llm_response: str | None,
    signal_id,
    keyword_hits: dict | None = None,
    country: str = "",
) -> None:
    """Persist an Article row capturing what we did with this article during a run."""
    db.add(Article(
        ingestion_run_id=run_id,
        feed_source_id=feed.id,
        feed_name=feed.name[:255],
        url=(article.get("url") or "")[:2048],
        title=(article.get("title") or "")[:1024],
        summary=(article.get("summary") or None),
        published=(article.get("published") or None),
        verdict=verdict,
        llm_response=(llm_response[:8000] if llm_response else None),
        signal_id=signal_id,
        keyword_hits=keyword_hits or {},
        country=(country or "")[:8],
    ))
    await db.commit()


async def ingest_all(db: AsyncSession, trigger: str = "manual") -> dict:
    """Fetch all active feeds, extract signals via LLM, and persist new ones.

    Also records an IngestionRun row so the UI can show history + outcomes.
    Shared between the POST /signals/ingest endpoint and the scheduled worker task.
    """
    # Imported here to avoid a circular import (signal_extraction -> rss_ingestion pulls).
    from app.services.signal_extraction import (
        get_primary_provider, get_secondary_provider,
        extract_signal_from_article, save_signal,
    )
    from app.services.llm_provider import LLMQuotaExceeded, LLMServiceUnavailable
    from app.config import settings as app_settings

    per_feed_limit = max(0, int(app_settings.articles_per_feed_limit or 0))
    auto_extract = bool(app_settings.auto_extract_on_ingest)

    run = IngestionRun(trigger=trigger, status="running")
    db.add(run)
    await db.commit()
    await db.refresh(run)

    async def _finish(status: str, message: str | None, feed_results: list, total_new: int, total_skipped: int) -> dict:
        run.status = status
        run.message = message
        run.feed_results = feed_results
        run.total_new_signals = total_new
        run.total_skipped = total_skipped
        run.finished_at = datetime.now(timezone.utc)
        await db.commit()
        return {
            "status": status,
            "run_id": str(run.id),
            "message": message,
            "total_new_signals": total_new,
            "total_skipped": total_skipped,
            "feeds": feed_results,
        }

    try:
        provider = get_primary_provider() if auto_extract else None
        fallback = get_secondary_provider() if auto_extract else None

        if auto_extract and not provider:
            return await _finish("error", "No LLM provider configured. Set API key in settings.", [], 0, 0)

        result = await db.execute(select(FeedSource).where(FeedSource.is_active == True))
        feeds = result.scalars().all()

        if not feeds:
            return await _finish("warning", "No active feeds configured.", [], 0, 0)

        existing_urls = await get_existing_urls(db)
        total_new = 0
        total_skipped = 0
        feed_results: list[dict] = []
        quota_error: LLMQuotaExceeded | None = None
        service_error: LLMServiceUnavailable | None = None

        for feed in feeds:
            if quota_error is not None or service_error is not None:
                break

            articles = await fetch_feed(feed)
            success = len(articles) > 0
            await update_feed_status(db, feed, success)

            if not articles:
                feed_results.append({"feed": feed.name, "articles": 0, "new_articles": 0, "new_signals": 0})
                continue

            new_articles = await filter_new_articles(articles, existing_urls)
            if per_feed_limit:
                new_articles = new_articles[:per_feed_limit]
            signals_created = 0

            # Gate: which keyword set decides whether this article enters the log.
            # Unchanged — per-feed keywords win, fall back to globals.
            gate_keywords = feed.keywords or app_settings.global_scrape_keywords or []
            # Stats: ALWAYS scored against the global set so the News Log shows
            # the full extraction-intent picture regardless of narrower per-feed gating.
            stats_keywords = app_settings.global_scrape_keywords or feed.keywords or []

            from app.services.country_detection import detect_country_from_text, detect_country_from_location

            for article in new_articles:
                article_url = article.get("url", "")
                title = article.get("title", "")
                summary = article.get("summary", "") or ""

                gate_hits = _count_keyword_hits(title, summary, gate_keywords)
                stats_hits = _count_keyword_hits(title, summary, stats_keywords)
                # Cheap country tag from title + summary (no LLM call). Empty when
                # no preset matched — backfillable later via the LLM endpoint.
                country = detect_country_from_text(title, summary)

                # Per-feed/global gate: only applies when there are keywords configured.
                # If the gate set has entries but none matched, filter the article out.
                if gate_keywords and sum(gate_hits.values()) == 0:
                    await _record_article(
                        db, run.id, feed, article, verdict="keyword_filtered",
                        llm_response=None, signal_id=None, keyword_hits=stats_hits,
                        country=country,
                    )
                    total_skipped += 1
                    continue

                if not auto_extract:
                    # Scrape-only mode: persist as pending, defer LLM to manual trigger.
                    await _record_article(
                        db, run.id, feed, article, verdict="pending",
                        llm_response=None, signal_id=None, keyword_hits=stats_hits,
                        country=country,
                    )
                    continue

                try:
                    data, verdict, raw = await extract_signal_from_article(article, provider, fallback)
                except LLMQuotaExceeded as e:
                    await _record_article(
                        db, run.id, feed, article, verdict="quota_exceeded",
                        llm_response=str(e), signal_id=None, keyword_hits=stats_hits,
                        country=country,
                    )
                    quota_error = e
                    break
                except LLMServiceUnavailable as e:
                    await _record_article(
                        db, run.id, feed, article, verdict="service_unavailable",
                        llm_response=str(e), signal_id=None, keyword_hits=stats_hits,
                        country=country,
                    )
                    service_error = e
                    break

                signal_id = None
                if data and data["source_url"] not in existing_urls:
                    saved = await save_signal(db, data)
                    existing_urls.add(data["source_url"])
                    signals_created += 1
                    signal_id = saved.id
                    # Upgrade: if the LLM extracted a precise HQ location, prefer
                    # the country derived from THAT (more accurate than article body).
                    loc_country = detect_country_from_location(data.get("location") or "")
                    if loc_country:
                        country = loc_country
                else:
                    total_skipped += 1

                await _record_article(
                    db, run.id, feed, article, verdict=verdict,
                    llm_response=raw, signal_id=signal_id, keyword_hits=stats_hits,
                    country=country,
                )

            total_new += signals_created
            feed_results.append({
                "feed": feed.name,
                "articles": len(articles),
                "new_articles": len(new_articles),
                "new_signals": signals_created,
            })

        if quota_error is not None:
            retry_hint = (
                f" Retry in {quota_error.retry_after_seconds}s."
                if quota_error.retry_after_seconds else ""
            )
            msg = f"LLM quota exceeded — stopped early to avoid burning more requests.{retry_hint}"
            return await _finish("warning", msg, feed_results, total_new, total_skipped)

        if service_error is not None:
            msg = (
                f"LLM service unavailable ({service_error.status_code or '5xx'}) after retries — "
                "stopped early. Usually a brief demand spike; try again in a few minutes."
            )
            return await _finish("warning", msg, feed_results, total_new, total_skipped)

        return await _finish("ok", None, feed_results, total_new, total_skipped)

    except Exception as e:
        logger.exception("Ingestion run %s crashed", run.id)
        return await _finish("error", f"{type(e).__name__}: {e}", [], 0, 0)
