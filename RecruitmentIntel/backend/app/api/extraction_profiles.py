from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.extraction_profile import ExtractionProfile
from app.schemas.extraction_profile import (
    ExtractionProfileCreate, ExtractionProfileOut, ExtractionProfileUpdate,
)

router = APIRouter()


@router.get("/extraction-profiles", response_model=list[ExtractionProfileOut])
async def list_profiles(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ExtractionProfile).order_by(ExtractionProfile.name))
    return result.scalars().all()


@router.post("/extraction-profiles", response_model=ExtractionProfileOut)
async def create_profile(data: ExtractionProfileCreate, db: AsyncSession = Depends(get_db)):
    if not data.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")

    existing = await db.execute(
        select(ExtractionProfile).where(ExtractionProfile.name == data.name.strip())
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f'A preset named "{data.name}" already exists')

    profile = ExtractionProfile(
        name=data.name.strip(),
        extraction_prompt=data.extraction_prompt,
        scrape_keywords=data.scrape_keywords,
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


@router.put("/extraction-profiles/{profile_id}", response_model=ExtractionProfileOut)
async def update_profile(
    profile_id: UUID, data: ExtractionProfileUpdate, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(ExtractionProfile).where(ExtractionProfile.id == profile_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Preset not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        setattr(profile, field, value)

    await db.commit()
    await db.refresh(profile)
    return profile


@router.delete("/extraction-profiles/{profile_id}")
async def delete_profile(profile_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ExtractionProfile).where(ExtractionProfile.id == profile_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Preset not found")
    await db.delete(profile)
    await db.commit()
    return {"status": "deleted", "id": str(profile_id)}
