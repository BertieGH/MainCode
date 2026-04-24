import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class IngestionRun(Base):
    """One row per ingestion invocation (button press, cron, or API call)."""

    __tablename__ = "ingestion_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # running | ok | warning | error
    status: Mapped[str] = mapped_column(String(20), default="running")
    total_new_signals: Mapped[int] = mapped_column(Integer, default=0)
    total_skipped: Mapped[int] = mapped_column(Integer, default=0)
    feed_results: Mapped[list] = mapped_column(JSON, default=list)
    message: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    # "manual" (UI/API) or "scheduled" (cron)
    trigger: Mapped[str] = mapped_column(String(20), default="manual")
