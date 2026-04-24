from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ExtractionProfileCreate(BaseModel):
    name: str
    extraction_prompt: str = ""
    scrape_keywords: list[str] = []


class ExtractionProfileUpdate(BaseModel):
    name: str | None = None
    extraction_prompt: str | None = None
    scrape_keywords: list[str] | None = None


class ExtractionProfileOut(BaseModel):
    id: UUID
    name: str
    extraction_prompt: str
    scrape_keywords: list[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
