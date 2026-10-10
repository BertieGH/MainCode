"""A generated prep brief, kept as written.

**This stores a generation, not the current truth.** A brief is what somebody
walked into a call holding; when its hypothesis turns out wrong, the useful
question is what it claimed *at the time*, and that answer does not survive
rebuilding the text from today's signals. So the row carries the context it was
written from — research age, signal count, what had been sent — alongside the
payload, and superseded rows stay.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SalesPrep(Base):
    __tablename__ = "sales_prep"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('pre_engagement', 'engagement_aware')",
            name="ck_sales_prep_mode_valid",
        ),
        CheckConstraint(
            "hypothesis_verdict IS NULL OR hypothesis_verdict IN "
            "('confirmed', 'rejected', 'partly', 'not_discussed')",
            name="ck_sales_prep_verdict_valid",
        ),
        CheckConstraint(
            "outcome IS NULL OR outcome IN "
            "('meeting_booked', 'follow_up', 'no_need_now', 'not_interested')",
            name="ck_sales_prep_outcome_valid",
        ),
        Index("ix_sales_prep_contact_newest", "contact_id", "created_at"),
    )

    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contact.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="CASCADE"), nullable=False
    )
    #: Decided from the engagement ladder at generation time, so a brief
    #: written before a reply reads as such afterwards rather than looking as
    #: though it ignored one.
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    #: What it was written from. Lets a later review tell a wrongly reasoned
    #: brief from a merely under-informed one.
    research_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    newest_signal_on: Mapped[date | None] = mapped_column(Date)
    signal_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    touches_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    replies_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: The rep's verdict after the call.
    #:
    #: **The measure worth watching.** Sophisticated hypotheses that prospects
    #: keep rejecting mean the signal interpretation or the account selection
    #: is wrong — not the writing. Null until a rep comes back, which is itself
    #: a finding: a brief nobody rated is a brief nobody used.
    hypothesis_verdict: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str | None] = mapped_column(Text)
    rep_note: Mapped[str | None] = mapped_column(Text)
