from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class IngestionRunOut(BaseModel):
    id: UUID
    started_at: datetime
    finished_at: datetime | None
    status: str
    total_new_signals: int
    total_skipped: int
    feed_results: list[dict] = []
    message: str | None = None
    trigger: str

    model_config = {"from_attributes": True}
