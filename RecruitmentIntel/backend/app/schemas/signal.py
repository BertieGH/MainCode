from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel


class SignalOut(BaseModel):
    id: UUID
    company_name: str
    industry: str
    funding_round: str
    amount: int
    location: str
    date: date
    source_url: str
    source_title: str
    extraction_status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SignalFilter(BaseModel):
    industry: str | None = None
    funding_round: str | None = None
    amount_min: int | None = None
    amount_max: int | None = None
    location: str | None = None
    date_from: date | None = None
    date_to: date | None = None
