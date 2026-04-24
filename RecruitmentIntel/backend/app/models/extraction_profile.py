import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class ExtractionProfile(Base):
    """A named, reusable pairing of extraction_prompt + scrape_keywords.

    Lets the user save domain-specific scraping setups ("Funding signals",
    "Product launches", "Hiring events") and load them into the active
    Extraction Intent settings from a dropdown.
    """

    __tablename__ = "extraction_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    extraction_prompt: Mapped[str] = mapped_column(Text, default="")
    scrape_keywords: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
