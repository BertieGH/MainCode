import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class Signal(Base):
    __tablename__ = "signal_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_name: Mapped[str] = mapped_column(String(255))
    industry: Mapped[str] = mapped_column(String(100))
    funding_round: Mapped[str] = mapped_column(String(50))
    amount: Mapped[int] = mapped_column(BigInteger, default=0)
    location: Mapped[str] = mapped_column(String(255), default="")
    date: Mapped[date] = mapped_column(Date)
    source_url: Mapped[str] = mapped_column(String(2048), unique=True)
    source_title: Mapped[str] = mapped_column(String(512), default="")
    raw_text: Mapped[str] = mapped_column(Text, default="")
    extraction_status: Mapped[str] = mapped_column(String(20), default="complete")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
