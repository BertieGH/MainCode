import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class JobPromptProfile(Base):
    """A named, reusable bundle of the three job-crawl LLM prompts.

    Lets the user save/load tuned prompt sets ("Strict IC engineer",
    "Generous match", etc.) into the live Settings without retyping.
    """

    __tablename__ = "job_prompt_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    extract_prompt: Mapped[str] = mapped_column(Text, default="")
    match_prompt: Mapped[str] = mapped_column(Text, default="")
    classify_prompt: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
