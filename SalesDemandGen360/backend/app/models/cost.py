"""What a call costs, and what a search provider charged.

Kept apart from `llm_call` on purpose. That table records what happened; these
record what it was worth, and the two change for different reasons — a price
rise rewrites no history, and a re-priced month must still add up the way it
did at the time.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ModelPrice(Base):
    """One active sheet of prices, versioned like every other config.

    **Not hard-coded, deliberately.** A price in code is a number on a screen
    that goes quietly wrong when the vendor changes it, and nobody re-checks a
    figure that looks authoritative. Versioning the sheet is also what keeps
    "why was last month cheaper" answerable after a rise.
    """

    __tablename__ = "model_price"

    version: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    #: `{model: {input_per_m, output_per_m, grounded_per_call}}`.
    #:
    #: Grounding has its own figure because it is billed per request rather
    #: than per token, and it is the larger part of a research bill — the part
    #: that was invisible until the ledger started recording it.
    prices: Mapped[dict] = mapped_column(JSONB, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'USD'"))
    note: Mapped[str | None] = mapped_column(Text)


class SerpCall(Base):
    """One search bought from a SERP provider, and what it charged.

    The provider returns its credit cost on every response. It used to be read,
    written to a log line and dropped, which left the balance as the only
    signal — and a balance cannot say which run spent it, so a run costing ten
    times its neighbours stayed invisible until the credits ran out.
    """

    __tablename__ = "serp_call"
    __table_args__ = (
        Index("ix_serp_call_created", text("created_at DESC")),
        Index("ix_serp_call_run", "run_id"),
    )

    provider: Mapped[str] = mapped_column(Text, nullable=False)
    #: Both nullable: a trial run from the settings screen belongs to no run
    #: and no account, and refusing to record it would hide the searches a
    #: person makes while tuning a source — which are bought with the same
    #: credits.
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("run.id", ondelete="SET NULL")
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="SET NULL")
    )
    family: Mapped[str | None] = mapped_column(Text)
    queries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: What the provider said it charged, not what we think it should have.
    credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime]
