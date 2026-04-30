import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class BackfillRun(Base):
    """One row per long-running backfill job (currently country tagging).

    Persisted so the UI can poll progress while the worker runs in the
    background and so the user can see what happened after navigating away.
    """

    __tablename__ = "backfill_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # "country" — leaves room to add other backfills under the same model.
    kind: Mapped[str] = mapped_column(String(20), default="country")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # running | done | warning | error
    status: Mapped[str] = mapped_column(String(20), default="running")
    total: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    still_unknown: Mapped[int] = mapped_column(Integer, default=0)
    # Hits resolved without an LLM call (e.g. via Signal.location regex).
    via_location: Mapped[int] = mapped_column(Integer, default=0)
    via_llm: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    trigger: Mapped[str] = mapped_column(String(20), default="manual")
