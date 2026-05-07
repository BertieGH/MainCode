import logging
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.background import fire_and_forget
from app.database import async_session, get_db
from app.deps import get_arq_pool
from app.models.prospect import Prospect
from app.models.prospect_list import ProspectList
from app.services.job_scraper import crawl_prospect_jobs, crawl_prospect_jobs_with_timeout

logger = logging.getLogger(__name__)
router = APIRouter()


class CrawlListRequest(BaseModel):
    """Body for POST /prospect-lists/{id}/crawl-jobs.

    `prospect_ids` (optional) restricts to a subset (used by bulk-select UI
    on Prospect Detail). Empty body == "crawl the whole list, no force".
    """
    force: bool = False
    prospect_ids: list[UUID] | None = None


async def _run_crawl_list_inproc(
    list_id: UUID, force: bool, prospect_ids: list[UUID] | None = None
) -> None:
    """Fallback: run list job crawl in-process when no arq worker is available."""
    async with async_session() as db:
        try:
            query = select(Prospect).where(
                Prospect.list_id == list_id,
                Prospect.enrichment_status == "done",
            )
            if prospect_ids:
                query = query.where(Prospect.id.in_(prospect_ids))
            if not force:
                query = query.where(Prospect.job_crawl_status.in_(["pending", "not_started", "failed"]))
            res = await db.execute(query)
            for p in res.scalars().all():
                # Timeout wrapper so a stuck prospect doesn't block the batch.
                await crawl_prospect_jobs_with_timeout(db, p, force=force)
        except Exception as e:
            logger.error(f"In-process crawl_list failed for {list_id}: {e}")


@router.post("/prospect-lists/{list_id}/crawl-jobs")
async def crawl_jobs_for_list(
    list_id: UUID,
    payload: CrawlListRequest = Body(default_factory=CrawlListRequest),
    db: AsyncSession = Depends(get_db),
    pool=Depends(get_arq_pool),
):
    """Enqueue job crawl. If the arq worker is unavailable, runs the work
    in-process via asyncio so local dev without Redis still works.

    Optional `prospect_ids` in the body restricts the run to a subset.
    Empty body = crawl every enriched prospect in the list.
    """
    result = await db.execute(select(ProspectList).where(ProspectList.id == list_id))
    pl = result.scalar_one_or_none()
    if not pl:
        raise HTTPException(status_code=404, detail="Prospect list not found")

    force = payload.force
    prospect_ids = payload.prospect_ids or None

    # Eagerly mark matching prospects as pending so UI polling stays active
    # between enqueue and worker pickup. Restrict to subset when provided.
    stmt = update(Prospect).where(
        Prospect.list_id == list_id,
        Prospect.enrichment_status == "done",
    )
    if prospect_ids:
        stmt = stmt.where(Prospect.id.in_(prospect_ids))
    if not force:
        stmt = stmt.where(Prospect.job_crawl_status.in_(["not_started", "failed"]))
    await db.execute(stmt.values(job_crawl_status="pending", job_crawl_error=None))
    await db.commit()

    str_ids = [str(i) for i in prospect_ids] if prospect_ids else None

    if pool is not None:
        job = await pool.enqueue_job("task_crawl_jobs_for_list", str(list_id), force, str_ids)
        return {"status": "queued", "job_id": job.job_id if job else None, "mode": "worker"}

    fire_and_forget(
        _run_crawl_list_inproc(list_id, force, prospect_ids),
        name=f"crawl_list:{list_id}",
    )
    return {"status": "queued", "job_id": None, "mode": "inproc"}


@router.post("/prospects/{prospect_id}/crawl-jobs")
async def crawl_jobs_for_prospect(
    prospect_id: UUID,
    force: bool = Query(False, description="Clear cached careers_url + jobs and re-crawl"),
    db: AsyncSession = Depends(get_db),
):
    """Trigger job crawl for a single prospect. Always re-runs (ignores current status).
    Pass force=true to also clear the cached careers_url and prior Job rows."""
    result = await db.execute(select(Prospect).where(Prospect.id == prospect_id))
    prospect = result.scalar_one_or_none()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    # Synchronous per-row endpoint also uses the timeout wrapper so the HTTP
    # request can't hang the browser indefinitely on a slow careers page.
    job_count = await crawl_prospect_jobs_with_timeout(db, prospect, force=force)
    return {
        "id": str(prospect.id),
        "company_name": prospect.company_name,
        "careers_url": prospect.careers_url,
        "job_crawl_status": prospect.job_crawl_status,
        "job_crawl_strategy": prospect.job_crawl_strategy,
        "job_crawl_raw_count": prospect.job_crawl_raw_count,
        "job_crawl_error": prospect.job_crawl_error,
        "jobs_found": job_count,
    }
