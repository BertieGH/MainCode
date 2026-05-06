from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class JobOut(BaseModel):
    id: UUID
    prospect_id: UUID
    list_id: UUID
    company_name: str
    title: str
    department: str
    seniority: str
    job_type: str
    location: str
    url: str
    skills: list[str]
    match_target: str | None = None
    discovered_at: datetime
    linkedin_url: str | None = None
    website: str | None = None

    model_config = {"from_attributes": True}


class OutreachSummary(BaseModel):
    department: str
    count: int
