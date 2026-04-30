from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.job_prompt_profile import JobPromptProfile
from app.schemas.job_prompt_profile import (
    JobPromptProfileCreate, JobPromptProfileOut, JobPromptProfileUpdate,
)

router = APIRouter()


@router.get("/job-prompt-profiles", response_model=list[JobPromptProfileOut])
async def list_profiles(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(JobPromptProfile).order_by(JobPromptProfile.name))
    return result.scalars().all()


@router.post("/job-prompt-profiles", response_model=JobPromptProfileOut)
async def create_profile(data: JobPromptProfileCreate, db: AsyncSession = Depends(get_db)):
    if not data.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")

    existing = await db.execute(
        select(JobPromptProfile).where(JobPromptProfile.name == data.name.strip())
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f'A preset named "{data.name}" already exists')

    profile = JobPromptProfile(
        name=data.name.strip(),
        extract_prompt=data.extract_prompt,
        match_prompt=data.match_prompt,
        classify_prompt=data.classify_prompt,
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


@router.put("/job-prompt-profiles/{profile_id}", response_model=JobPromptProfileOut)
async def update_profile(
    profile_id: UUID, data: JobPromptProfileUpdate, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(JobPromptProfile).where(JobPromptProfile.id == profile_id))
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


@router.delete("/job-prompt-profiles/{profile_id}")
async def delete_profile(profile_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(JobPromptProfile).where(JobPromptProfile.id == profile_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Preset not found")
    await db.delete(profile)
    await db.commit()
    return {"status": "deleted", "id": str(profile_id)}
