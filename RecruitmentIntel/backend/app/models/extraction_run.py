import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class ExtractionRun(Base):
    """One row per long-running article-extraction job.

    Mirrors `BackfillRun` so the UI can poll progress while the worker iterates
    selected articles in chunks with bounded LLM concurrency. Per-chunk DB
    commits mean partial progress survives a server restart or browser close.
    """

    __tablename__ = "extraction_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # running | done | warning | quota_exceeded | error
    status: Mapped[str] = mapped_column(String(20), default="running")
    total: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    # Verdict bucket counts (mirrors `extract_articles` legacy response shape)
    funding: Mapped[int] = mapped_column(Integer, default=0)
    not_funding: Mapped[int] = mapped_column(Integer, default=0)
    parse_failed: Mapped[int] = mapped_column(Integer, default=0)
    validation_failed: Mapped[int] = mapped_column(Integer, default=0)
    # Articles whose batch hit a 5xx after retries — recorded as failed but
    # the run continues to the next batch (key behavior change from sequential).
    service_unavailable: Mapped[int] = mapped_column(Integer, default=0)
    # Misc / unexpected errors during extraction.
    error: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    trigger: Mapped[str] = mapped_column(String(20), default="manual")
    # Whether the request asked to overwrite existing Signal rows.
    force: Mapped[bool] = mapped_column(default=False)
