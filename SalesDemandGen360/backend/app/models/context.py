"""Domain 4 — Context and qualification.

`account_context` is the versioned handoff contract: immutable once written, a
new build makes a new version. `qualification` is what the six dimensions came
to, and — importantly — it stores the per-dimension assessments that produced
it, not just the arithmetic result.

That storage is what makes re-scoring free. A weight change re-runs the maths
over `reasons`; the assessments are evidence-grounded judgements that a new
weighting does not invalidate, so no model is asked anything.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

DIMENSIONS = ("fit", "opportunity", "buyer", "commercial", "intent", "engagement")
BANDS = ("low", "medium", "high")


class AccountContext(Base):
    """The compressed picture handed downstream. Never edited in place."""

    __tablename__ = "account_context"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("run.id")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    #: Which signals are in scope for this version. Stored rather than
    #: recomputed, so a context built last week can still explain itself after
    #: those signals expire.
    signal_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer)
    builder_version: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("account_id", "version", name="one_row_per_version"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(
            "parent_version IS NULL OR parent_version < version",
            name="parent_precedes_child",
        ),
        Index("ix_account_context_account", "account_id", "version"),
    )


class Qualification(Base):
    """Six dimensions and the roll-up computed from them.

    `scoring_config_version` is not decoration: it is the only way to explain
    why yesterday's 71 is today's 64 without having to guess which weights were
    in force.
    """

    __tablename__ = "qualification"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="CASCADE"), nullable=False
    )
    context_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account_context.id")
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("run.id")
    )

    fit_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    opportunity_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    buyer_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    commercial_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    intent_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    engagement_score: Mapped[float | None] = mapped_column(Numeric(5, 2))

    priority_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    priority_band: Mapped[str] = mapped_column(Text, nullable=False)

    #: Per dimension: {score, band, reason, evidence_ids[], basis}. The input to
    #: re-scoring, which is why it is required rather than a nicety.
    reasons: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # The legacy MAN view, kept for reps who still think in it. Derived, never
    # authored, and switched off by default.
    man_money: Mapped[str | None] = mapped_column(Text)
    man_authority: Mapped[str | None] = mapped_column(Text)
    man_need: Mapped[str | None] = mapped_column(Text)

    scoring_config_version: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("priority_band IN ('low','medium','high')", name="band_valid"),
        CheckConstraint(
            "priority_score >= 0 AND priority_score <= 100", name="priority_is_a_percentage"
        ),
        Index("ix_qualification_account", "account_id"),
        Index("ix_qualification_priority", "priority_band", "priority_score"),
    )
