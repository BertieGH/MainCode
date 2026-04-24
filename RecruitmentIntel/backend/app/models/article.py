import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class Article(Base):
    """One row per article seen during ingestion + the LLM verdict on it.

    Lets the user diagnose why a feed produced 0 signals — was the article
    keyword-filtered, did the LLM say it wasn't funding, did it fail to parse, etc.
    """

    __tablename__ = "articles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ingestion_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingestion_runs.id", ondelete="CASCADE"), nullable=True
    )
    feed_source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("feed_sources.id", ondelete="SET NULL"), nullable=True
    )
    feed_name: Mapped[str] = mapped_column(String(255), default="")
    url: Mapped[str] = mapped_column(String(2048))
    title: Mapped[str] = mapped_column(String(1024), default="")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    published: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # funding | not_funding | keyword_filtered | parse_failed | validation_failed | quota_exceeded | error
    verdict: Mapped[str] = mapped_column(String(32), default="error")
    llm_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Dict[keyword, count] — case-insensitive substring hits in title+summary at scrape time.
    # Empty dict when the feed had no keywords configured, or when no keywords matched.
    keyword_hits: Mapped[dict] = mapped_column(JSON, default=dict)
    signal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("signal_log.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
