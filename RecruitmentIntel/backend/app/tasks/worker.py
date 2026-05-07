"""arq worker: periodic ingestion + on-demand enrichment / job crawl tasks.

Run with:  arq app.tasks.worker.WorkerSettings
"""
import logging
from uuid import UUID

from arq.connections import RedisSettings
from arq.cron import cron
from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.models.prospect import Prospect
from app.models.prospect_list import ProspectList
from app.services.rss_ingestion import ingest_all
from app.services.enrichment import enrich_all_in_list, enrich_prospect
from app.services.job_scraper import crawl_prospect_jobs

logger = logging.getLogger(__name__)


def _ingestion_hours() -> set[int]:
    """Build the set of hours (0-23) on which to run ingestion cron.

    An interval of 0 means "manual" — return an empty set so no cron
    job is registered; ingestion then only fires via the UI button or
    the /signals/ingest endpoint.
    """
    step = int(settings.fetch_interval_hours or 0)
    if step <= 0:
        return set()
    step = min(24, step)
    return set(range(0, 24, step))


async def task_ingest_all(ctx: dict) -> dict:
    """Scheduled: fetch all active feeds and extract signals."""
    async with async_session() as db:
        result = await ingest_all(db, trigger="scheduled")
    logger.info("Scheduled ingestion finished: %s", result)
    return result


async def task_enrich_list(
    ctx: dict,
    list_id: str,
    force: bool = False,
    prospect_ids: list[str] | None = None,
) -> dict:
    """On-demand: enrich prospects in a list. `prospect_ids` (optional)
    restricts the run to a subset; arq passes args by serialization so we
    receive strings and convert."""
    only_ids = [UUID(p) for p in prospect_ids] if prospect_ids else None
    async with async_session() as db:
        return await enrich_all_in_list(db, UUID(list_id), force=force, only_ids=only_ids)


async def task_enrich_prospect(ctx: dict, prospect_id: str) -> dict:
    """On-demand: enrich a single prospect."""
    async with async_session() as db:
        result = await db.execute(select(Prospect).where(Prospect.id == UUID(prospect_id)))
        prospect = result.scalar_one_or_none()
        if not prospect:
            return {"status": "error", "message": "prospect not found"}
        await enrich_prospect(db, prospect)
        return {
            "id": str(prospect.id),
            "status": prospect.enrichment_status,
            "website": prospect.website,
            "linkedin_url": prospect.linkedin_url,
        }


async def task_crawl_jobs_for_list(
    ctx: dict,
    list_id: str,
    force: bool = False,
    prospect_ids: list[str] | None = None,
) -> dict:
    """On-demand: crawl jobs for enriched prospects in a list.
    `prospect_ids` (optional) restricts to a subset of prospects."""
    only_ids = [UUID(p) for p in prospect_ids] if prospect_ids else None
    async with async_session() as db:
        result = await db.execute(select(ProspectList).where(ProspectList.id == UUID(list_id)))
        if not result.scalar_one_or_none():
            return {"status": "error", "message": "list not found"}

        query = select(Prospect).where(
            Prospect.list_id == UUID(list_id),
            Prospect.enrichment_status == "done",
        )
        if only_ids:
            query = query.where(Prospect.id.in_(only_ids))
        if not force:
            query = query.where(Prospect.job_crawl_status.in_(["not_started", "failed"]))

        result = await db.execute(query)
        prospects = result.scalars().all()
        totals = {"total": len(prospects), "done": 0, "empty": 0, "failed": 0, "total_jobs": 0}
        for p in prospects:
            count = await crawl_prospect_jobs(db, p, force=force)
            if p.job_crawl_status == "done":
                totals["done"] += 1
                totals["total_jobs"] += count
            elif p.job_crawl_status == "empty":
                totals["empty"] += 1
            else:
                totals["failed"] += 1
        return totals


async def task_crawl_jobs_for_prospect(ctx: dict, prospect_id: str) -> dict:
    """On-demand: crawl jobs for a single prospect."""
    async with async_session() as db:
        result = await db.execute(select(Prospect).where(Prospect.id == UUID(prospect_id)))
        prospect = result.scalar_one_or_none()
        if not prospect:
            return {"status": "error", "message": "prospect not found"}
        count = await crawl_prospect_jobs(db, prospect)
        return {
            "id": str(prospect.id),
            "status": prospect.job_crawl_status,
            "jobs_found": count,
        }


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    functions = [
        task_ingest_all,
        task_enrich_list,
        task_enrich_prospect,
        task_crawl_jobs_for_list,
        task_crawl_jobs_for_prospect,
    ]
    # Only register the cron if the user hasn't selected "Manual" (interval=0).
    cron_jobs = (
        [cron(task_ingest_all, hour=_ingestion_hours(), minute={0}, run_at_startup=False)]
        if _ingestion_hours() else []
    )
    # Keep Playwright-heavy crawls from piling up
    max_jobs = 5
    job_timeout = 60 * 30  # 30 min
