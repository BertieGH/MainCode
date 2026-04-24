from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class ProspectListCreate(BaseModel):
    name: str
    description: str = ""


class ProspectListOut(BaseModel):
    id: UUID
    name: str
    description: str
    company_count: int = 0
    enriched_count: int = 0
    jobs_crawled_count: int = 0
    total_jobs: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProspectOut(BaseModel):
    id: UUID
    list_id: UUID
    signal_id: UUID
    company_name: str
    industry: str
    funding_round: str
    amount: int
    location: str
    website: str | None
    linkedin_url: str | None
    careers_url: str | None
    enrichment_status: str
    enrichment_strategy: str | None = None
    enrichment_error: str | None = None
    job_crawl_status: str
    job_crawl_strategy: str | None = None
    job_crawl_raw_count: int = 0
    job_crawl_error: str | None = None
    job_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class AddSignalsRequest(BaseModel):
    signal_ids: list[UUID]


class SkippedSignal(BaseModel):
    signal_id: UUID
    company_name: str
    reason: Literal["dup_signal", "dup_company_in_list", "dup_company_in_batch"]


class AddSignalsResult(BaseModel):
    added: list[ProspectOut]
    skipped: list[SkippedSignal]
