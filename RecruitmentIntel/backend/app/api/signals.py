import logging
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete as sql_delete, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.signal import Signal
from app.schemas.signal import SignalOut
from app.services.rss_ingestion import ingest_all

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
    limit: int = Query(100, le=500),
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
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Signal not found")
    return signal


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
