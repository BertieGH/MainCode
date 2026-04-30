from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ArticleOut(BaseModel):
    id: UUID
    ingestion_run_id: UUID | None
    feed_source_id: UUID | None
    feed_name: str
    url: str
    title: str
    summary: str | None
    published: str | None
    verdict: str
    llm_response: str | None
    signal_id: UUID | None
    keyword_hits: dict[str, int] = {}
    country: str = ""
    created_at: datetime

    model_config = {"from_attributes": True}


class VerdictCount(BaseModel):
    verdict: str
    count: int
