import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class Prospect(Base):
    __tablename__ = "prospects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    list_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prospect_lists.id", ondelete="CASCADE"))
    signal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("signal_log.id"))
    company_name: Mapped[str] = mapped_column(String(255))
    industry: Mapped[str] = mapped_column(String(100))
    funding_round: Mapped[str] = mapped_column(String(50))
    amount: Mapped[int] = mapped_column(BigInteger, default=0)
    location: Mapped[str] = mapped_column(String(255), default="")
    website: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    careers_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    # enrichment_status values: not_started | pending | done | failed
    enrichment_status: Mapped[str] = mapped_column(String(20), default="not_started")
    # Which strategy found the website/linkedin, e.g. "domain_guess", "google_search",
    # "llm_inference", "url_pattern"; "none" if nothing worked.
    enrichment_strategy: Mapped[str | None] = mapped_column(String(50), nullable=True)
    enrichment_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # job_crawl_status values: not_started | pending | done | empty | failed
    #   empty = careers page found but 0 jobs scraped
    job_crawl_status: Mapped[str] = mapped_column(String(20), default="not_started")
    # Which strategy found the careers_url: "url_patterns" | "homepage_links" |
    # "ats_detection" | "google_search" | "linkedin_jobs" | "none"
    job_crawl_strategy: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Raw jobs scraped before LLM classification (0 doesn't mean failure — could be
    # a JS-rendered page Playwright didn't handle).
    job_crawl_raw_count: Mapped[int] = mapped_column(Integer, default=0)
    job_crawl_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    list = relationship("ProspectList", back_populates="prospects")
    jobs = relationship("Job", back_populates="prospect", cascade="all, delete-orphan")
