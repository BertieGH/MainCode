from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.prospect_list import ProspectList
from app.models.prospect import Prospect
from app.models.job import Job
from app.models.signal import Signal
from app.schemas.prospect import (
    ProspectListCreate, ProspectListOut, ProspectOut, AddSignalsRequest,
    AddSignalsResult, SkippedSignal,
)

router = APIRouter()


async def _enrich_list(db: AsyncSession, pl: ProspectList) -> dict:
    """Build ProspectListOut with computed counts."""
    company_count = (await db.execute(
        select(func.count(Prospect.id)).where(Prospect.list_id == pl.id)
    )).scalar() or 0

    enriched_count = (await db.execute(
        select(func.count(Prospect.id)).where(
            Prospect.list_id == pl.id, Prospect.enrichment_status == "done"
        )
    )).scalar() or 0

    jobs_crawled_count = (await db.execute(
        select(func.count(Prospect.id)).where(
            Prospect.list_id == pl.id, Prospect.job_crawl_status == "done"
        )
    )).scalar() or 0

    total_jobs = (await db.execute(
        select(func.count(Job.id)).where(Job.list_id == pl.id)
    )).scalar() or 0

    return ProspectListOut(
        id=pl.id,
        name=pl.name,
        description=pl.description,
        company_count=company_count,
        enriched_count=enriched_count,
        jobs_crawled_count=jobs_crawled_count,
        total_jobs=total_jobs,
        created_at=pl.created_at,
        updated_at=pl.updated_at,
    )


@router.get("/prospect-lists", response_model=list[ProspectListOut])
async def list_prospect_lists(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ProspectList).order_by(ProspectList.updated_at.desc()))
    lists = result.scalars().all()
    return [await _enrich_list(db, pl) for pl in lists]


@router.post("/prospect-lists", response_model=ProspectListOut)
async def create_prospect_list(data: ProspectListCreate, db: AsyncSession = Depends(get_db)):
    pl = ProspectList(name=data.name, description=data.description)
    db.add(pl)
    await db.commit()
    await db.refresh(pl)
    return await _enrich_list(db, pl)


@router.get("/prospect-lists/{list_id}", response_model=ProspectListOut)
async def get_prospect_list(list_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ProspectList).where(ProspectList.id == list_id))
    pl = result.scalar_one_or_none()
    if not pl:
        raise HTTPException(status_code=404, detail="Prospect list not found")
    return await _enrich_list(db, pl)


@router.delete("/prospect-lists/{list_id}")
async def delete_prospect_list(list_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ProspectList).where(ProspectList.id == list_id))
    pl = result.scalar_one_or_none()
    if not pl:
        raise HTTPException(status_code=404, detail="Prospect list not found")
    await db.delete(pl)
    await db.commit()
    return {"status": "deleted"}


def _norm_company(name: str | None) -> str:
    """Normalize a company name for case-insensitive dedup."""
    return (name or "").strip().lower()


@router.post("/prospect-lists/{list_id}/add", response_model=AddSignalsResult)
async def add_signals_to_list(
    list_id: UUID, data: AddSignalsRequest, db: AsyncSession = Depends(get_db)
):
    """Add signals to a prospect list (copies signal data into prospects table).

    Dedups in three layers — same signal already in list, same company already
    in list, and same company appearing twice within the input batch — and
    reports each skip with a reason so the UI can surface "added X, skipped Y".
    """
    result = await db.execute(select(ProspectList).where(ProspectList.id == list_id))
    pl = result.scalar_one_or_none()
    if not pl:
        raise HTTPException(status_code=404, detail="Prospect list not found")

    result = await db.execute(select(Signal).where(Signal.id.in_(data.signal_ids)))
    signals = result.scalars().all()

    if not signals:
        raise HTTPException(status_code=400, detail="No valid signals found")

    # 1. Already-in-list by signal_id
    existing_signal_ids = {
        row[0] for row in (await db.execute(
            select(Prospect.signal_id).where(
                Prospect.list_id == list_id, Prospect.signal_id.in_(data.signal_ids)
            )
        )).fetchall()
    }
    # 2. Already-in-list by normalized company name
    existing_company_names = {
        _norm_company(row[0]) for row in (await db.execute(
            select(Prospect.company_name).where(Prospect.list_id == list_id)
        )).fetchall()
    }
    existing_company_names.discard("")

    created: list[Prospect] = []
    skipped: list[SkippedSignal] = []
    seen_in_batch: set[str] = set()  # 3. dedup within this batch

    for signal in signals:
        norm = _norm_company(signal.company_name)
        if signal.id in existing_signal_ids:
            skipped.append(SkippedSignal(
                signal_id=signal.id, company_name=signal.company_name, reason="dup_signal",
            ))
            continue
        if norm and norm in existing_company_names:
            skipped.append(SkippedSignal(
                signal_id=signal.id, company_name=signal.company_name, reason="dup_company_in_list",
            ))
            continue
        if norm and norm in seen_in_batch:
            skipped.append(SkippedSignal(
                signal_id=signal.id, company_name=signal.company_name, reason="dup_company_in_batch",
            ))
            continue
        if norm:
            seen_in_batch.add(norm)
        prospect = Prospect(
            list_id=list_id,
            signal_id=signal.id,
            company_name=signal.company_name,
            industry=signal.industry,
            funding_round=signal.funding_round,
            amount=signal.amount,
            location=signal.location,
        )
        db.add(prospect)
        created.append(prospect)

    await db.commit()
    for p in created:
        await db.refresh(p)

    added = [ProspectOut(
        id=p.id, list_id=p.list_id, signal_id=p.signal_id,
        company_name=p.company_name, industry=p.industry,
        funding_round=p.funding_round, amount=p.amount,
        location=p.location, website=p.website,
        linkedin_url=p.linkedin_url, careers_url=p.careers_url,
        enrichment_status=p.enrichment_status,
        enrichment_strategy=p.enrichment_strategy,
        enrichment_error=p.enrichment_error,
        job_crawl_status=p.job_crawl_status,
        job_crawl_strategy=p.job_crawl_strategy,
        job_crawl_raw_count=p.job_crawl_raw_count,
        job_crawl_error=p.job_crawl_error,
        job_count=0,
        created_at=p.created_at,
    ) for p in created]
    return AddSignalsResult(added=added, skipped=skipped)


@router.get("/prospect-lists/{list_id}/prospects", response_model=list[ProspectOut])
async def list_prospects(list_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Prospect).where(Prospect.list_id == list_id).order_by(Prospect.created_at.desc())
    )
    prospects = result.scalars().all()

    out = []
    for p in prospects:
        job_count = (await db.execute(
            select(func.count(Job.id)).where(Job.prospect_id == p.id)
        )).scalar() or 0
        out.append(ProspectOut(
            id=p.id, list_id=p.list_id, signal_id=p.signal_id,
            company_name=p.company_name, industry=p.industry,
            funding_round=p.funding_round, amount=p.amount,
            location=p.location, website=p.website,
            linkedin_url=p.linkedin_url, careers_url=p.careers_url,
            enrichment_status=p.enrichment_status,
            enrichment_strategy=p.enrichment_strategy,
            enrichment_error=p.enrichment_error,
            job_crawl_status=p.job_crawl_status,
            job_crawl_strategy=p.job_crawl_strategy,
            job_crawl_raw_count=p.job_crawl_raw_count,
            job_crawl_error=p.job_crawl_error,
            job_count=job_count,
            created_at=p.created_at,
        ))
    return out


@router.delete("/prospect-lists/{list_id}/prospects/{prospect_id}")
async def remove_prospect(list_id: UUID, prospect_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Prospect).where(Prospect.id == prospect_id, Prospect.list_id == list_id)
    )
    prospect = result.scalar_one_or_none()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")
    await db.delete(prospect)
    await db.commit()
    return {"status": "deleted"}
