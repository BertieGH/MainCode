from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.ingestion_run import IngestionRun
from app.schemas.ingestion import IngestionRunOut

router = APIRouter()


@router.get("/ingestion-runs", response_model=list[IngestionRunOut])
async def list_ingestion_runs(
    limit: int = Query(20, le=200),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(limit)
    )
    return result.scalars().all()


@router.get("/ingestion-runs/{run_id}", response_model=IngestionRunOut)
async def get_ingestion_run(run_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(IngestionRun).where(IngestionRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Ingestion run not found")
    return run
