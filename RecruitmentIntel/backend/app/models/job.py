import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prospect_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prospects.id", ondelete="CASCADE"))
    list_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prospect_lists.id", ondelete="CASCADE"))
    company_name: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(512))
    department: Mapped[str] = mapped_column(String(100), default="Other")
    seniority: Mapped[str] = mapped_column(String(50), default="Unknown")
    job_type: Mapped[str] = mapped_column(String(50), default="Full-time")
    location: Mapped[str] = mapped_column(String(255), default="")
    url: Mapped[str] = mapped_column(String(2048))
    skills: Mapped[dict | list] = mapped_column(JSON, default=list)
    # Which configured target title (from settings.job_target_titles) this job
    # semantically matched. Null when no targets are configured (everything saved).
    match_target: Mapped[str | None] = mapped_column(String(255), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    prospect = relationship("Prospect", back_populates="jobs")
