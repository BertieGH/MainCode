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
from app.services.enrichment import enrich_all_in_list, enrich_prospect

logger = logging.getLogger(__name__)
router = APIRouter()


class EnrichListRequest(BaseModel):
    """Body for POST /prospect-lists/{id}/enrich.

    Both fields optional so empty body == "enrich the whole list, no force"
    (preserves the old query-param-only behavior).
    """
    force: bool = False
    prospect_ids: list[UUID] | None = None


async def _run_enrich_list_inproc(
    list_id: UUID, force: bool, prospect_ids: list[UUID] | None = None
) -> None:
    """Fallback: run list enrichment in-process when no arq worker is available."""
    async with async_session() as db:
        try:
            await enrich_all_in_list(db, list_id, force=force, only_ids=prospect_ids)
        except Exception as e:
            logger.error(f"In-process enrich_list failed for {list_id}: {e}")


@router.post("/prospect-lists/{list_id}/enrich")
async def enrich_list(
    list_id: UUID,
    payload: EnrichListRequest = Body(default_factory=EnrichListRequest),
    db: AsyncSession = Depends(get_db),
    pool=Depends(get_arq_pool),
):
    """Enqueue list enrichment. If the arq worker is unavailable, runs the work
    in-process via asyncio so local dev without Redis still works.

    Optional `prospect_ids` in the body restricts the run to a subset (used by
    the bulk-select UI on Prospect Detail). Empty body = enrich the whole list.
    """
    result = await db.execute(select(ProspectList).where(ProspectList.id == list_id))
    pl = result.scalar_one_or_none()
    if not pl:
        raise HTTPException(status_code=404, detail="Prospect list not found")

    force = payload.force
    prospect_ids = payload.prospect_ids or None

    # Eagerly mark matching prospects as pending so UI polling stays active
    # between enqueue and worker pickup. Restrict to the subset when provided.
    stmt = update(Prospect).where(Prospect.list_id == list_id)
    if prospect_ids:
        stmt = stmt.where(Prospect.id.in_(prospect_ids))
    if not force:
        stmt = stmt.where(Prospect.enrichment_status.in_(["not_started", "failed"]))
    await db.execute(stmt.values(enrichment_status="pending", enrichment_error=None))
    await db.commit()

    # Worker takes prospect_ids as a list of strings (arq serializes args).
    str_ids = [str(i) for i in prospect_ids] if prospect_ids else None

    if pool is not None:
        job = await pool.enqueue_job("task_enrich_list", str(list_id), force, str_ids)
        return {"status": "queued", "job_id": job.job_id if job else None, "mode": "worker"}

    # Fallback: in-process background task (dev without Redis/worker)
    fire_and_forget(
        _run_enrich_list_inproc(list_id, force, prospect_ids),
        name=f"enrich_list:{list_id}",
    )
    return {"status": "queued", "job_id": None, "mode": "inproc"}


@router.post("/prospect-lists/recover-stuck-enrichment")
async def recover_stuck_enrichment(db: AsyncSession = Depends(get_db)):
    """Reset prospects orphaned in `enrichment_status='pending'`.

    The /enrich endpoint eagerly marks rows pending before the worker picks
    them up. If the worker (in-process or arq) dies — e.g. API restart, no
    Redis available, or task crash — those rows stay pending forever and
    the UI's Enrich button stays disabled while the polling sees them.

    Call once after a restart to release them. Returns the count reset.
    """
    result = await db.execute(
        update(Prospect)
        .where(Prospect.enrichment_status == "pending")
        .values(enrichment_status="not_started", enrichment_error=None)
    )
    await db.commit()
    return {"recovered": result.rowcount or 0}


@router.post("/prospects/{prospect_id}/enrich")
async def enrich_single(prospect_id: UUID, db: AsyncSession = Depends(get_db)):
    """Trigger enrichment for a single prospect. Always re-runs (ignores current status)."""
    result = await db.execute(select(Prospect).where(Prospect.id == prospect_id))
    prospect = result.scalar_one_or_none()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    await enrich_prospect(db, prospect)
    return {
        "id": str(prospect.id),
        "company_name": prospect.company_name,
        "website": prospect.website,
        "linkedin_url": prospect.linkedin_url,
        "enrichment_status": prospect.enrichment_status,
        "enrichment_strategy": prospect.enrichment_strategy,
        "enrichment_error": prospect.enrichment_error,
    }
