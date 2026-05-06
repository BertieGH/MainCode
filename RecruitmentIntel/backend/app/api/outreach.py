import csv
import io
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.job import Job
from app.models.prospect_list import ProspectList
from app.schemas.job import JobOut, OutreachSummary

router = APIRouter()


def _build_job_query(list_id: UUID, department: str | None, seniority: str | None,
                     job_type: str | None, location: str | None, skills: str | None):
    """Build filtered query for jobs in a prospect list."""
    query = select(Job).where(Job.list_id == list_id)

    if department:
        query = query.where(Job.department == department)
    if seniority:
        query = query.where(Job.seniority == seniority)
    if job_type:
        query = query.where(Job.job_type == job_type)
    if location:
        query = query.where(Job.location.ilike(f"%{location}%"))
    if skills:
        # Filter jobs that have any of the requested skills (JSON array search)
        for skill in skills.split(","):
            query = query.where(Job.skills.cast(str).ilike(f"%{skill.strip()}%"))

    return query.order_by(Job.discovered_at.desc())


@router.get("/outreach/{list_id}", response_model=list[JobOut])
async def get_outreach(
    list_id: UUID,
    department: str | None = None,
    seniority: str | None = None,
    job_type: str | None = None,
    location: str | None = None,
    skills: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Get all jobs for a prospect list with optional filters."""
    result = await db.execute(select(ProspectList).where(ProspectList.id == list_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Prospect list not found")

    query = _build_job_query(list_id, department, seniority, job_type, location, skills).options(
        selectinload(Job.prospect)
    )
    result = await db.execute(query)
    jobs = result.scalars().all()
    return [
        JobOut(
            **{c.name: getattr(j, c.name) for c in Job.__table__.columns},
            linkedin_url=j.prospect.linkedin_url if j.prospect else None,
            website=j.prospect.website if j.prospect else None,
        )
        for j in jobs
    ]


@router.get("/outreach/{list_id}/summary", response_model=list[OutreachSummary])
async def get_outreach_summary(list_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get department-level job counts for a prospect list."""
    result = await db.execute(select(ProspectList).where(ProspectList.id == list_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Prospect list not found")

    result = await db.execute(
        select(Job.department, func.count(Job.id).label("count"))
        .where(Job.list_id == list_id)
        .group_by(Job.department)
        .order_by(func.count(Job.id).desc())
    )
    return [OutreachSummary(department=row[0], count=row[1]) for row in result.fetchall()]


@router.get("/outreach/{list_id}/export")
async def export_outreach_csv(
    list_id: UUID,
    department: str | None = None,
    seniority: str | None = None,
    job_type: str | None = None,
    location: str | None = None,
    skills: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Export filtered jobs as CSV."""
    result = await db.execute(select(ProspectList).where(ProspectList.id == list_id))
    pl = result.scalar_one_or_none()
    if not pl:
        raise HTTPException(status_code=404, detail="Prospect list not found")

    query = _build_job_query(list_id, department, seniority, job_type, location, skills)
    result = await db.execute(query)
    jobs = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Company", "Job Title", "Department", "Seniority", "Job Type",
        "Location", "URL", "Skills", "Discovered At",
    ])
    for job in jobs:
        skills_str = ", ".join(job.skills) if isinstance(job.skills, list) else str(job.skills)
        writer.writerow([
            job.company_name, job.title, job.department, job.seniority,
            job.job_type, job.location, job.url, skills_str,
            job.discovered_at.strftime("%Y-%m-%d %H:%M") if job.discovered_at else "",
        ])

    output.seek(0)
    filename = f"outreach_{pl.name.replace(' ', '_')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
