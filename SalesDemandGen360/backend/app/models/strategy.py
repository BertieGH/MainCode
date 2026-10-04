"""Domain 5 — Strategy.

Three tables and one idea: the full persona × service matrix is retained, not
just the winners. "Why didn't we contact the CEO?" is a real question a rep
asks, and it has no answer if only the activated combinations were stored.

`strategy_thread` is one row per persona actually being pursued. Everything on
it — the problem hypothesis, the positioning, the CTA — is a claim about a
specific person, which is why threads are ranked and capped rather than being
created for everyone who happens to have an email address.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

STRATEGY_STATUS = ("draft", "evaluated", "approved", "rejected", "superseded")
#: `queued` is above the activation threshold but beyond the concurrent cap —
#: a thread we would run if we had room. `not_activated` fell below the
#: threshold on merit. Collapsing the two would lose the distinction between
#: "not yet" and "no".
THREAD_STATUS = ("active_primary", "active_secondary", "queued", "not_activated")


class Strategy(Base):
    __tablename__ = "strategy"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="CASCADE"), nullable=False
    )
    qualification_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("qualification.id")
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("run.id")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'draft'")
    )

    #: The campaign this strategy argues for. Null on company-wide strategies
    #: written before strategies belonged to campaigns.
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outreach_campaign.id", ondelete="CASCADE")
    )
    service_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_catalog.id", ondelete="SET NULL")
    )
    icp_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("icp_profile.id", ondelete="SET NULL")
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','evaluated','approved','rejected','superseded')",
            name="status_valid",
        ),
        CheckConstraint("version > 0", name="version_positive"),
        UniqueConstraint("account_id", "version", name="one_strategy_version_per_account"),
        Index("ix_strategy_account", "account_id", "version"),
    )


class PersonaServiceScore(Base):
    """Every mapped persona against every catalog service.

    Kept in full, including the combinations that scored nothing. The matrix is
    the audit trail for a decision not to act, and a decision not to act is
    invisible unless it was written down.
    """

    __tablename__ = "persona_service_score"

    strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategy.id", ondelete="CASCADE"), nullable=False
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contact.id"), nullable=False
    )
    service_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_catalog.id"), nullable=False
    )
    weight: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    evidence_ids: Mapped[list | None] = mapped_column(JSONB)

    __table_args__ = (
        CheckConstraint("weight >= 0", name="weight_non_negative"),
        UniqueConstraint(
            "strategy_id", "contact_id", "service_id", name="one_cell_per_pair"
        ),
        Index("ix_persona_service_score_strategy", "strategy_id"),
    )


class StrategyThread(Base):
    """One persona actually being pursued, or waiting for room."""

    __tablename__ = "strategy_thread"

    strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategy.id", ondelete="CASCADE"), nullable=False
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contact.id"), nullable=False
    )
    service_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_catalog.id"), nullable=False
    )
    weight: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    thread_status: Mapped[str] = mapped_column(Text, nullable=False)

    #: Always a hypothesis in spirit, and labelled as one in the UI. It is the
    #: system's guess at what hurts, not something the prospect has said.
    problem_hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_summary: Mapped[str] = mapped_column(Text, nullable=False)
    #: Must reference non-stale signals — enforced in the service layer, where
    #: staleness is knowable.
    trigger_signal_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    positioning: Mapped[str] = mapped_column(Text, nullable=False)
    channel_sequence: Mapped[list] = mapped_column(JSONB, nullable=False)
    cta: Mapped[str] = mapped_column(Text, nullable=False)
    avoid_list: Mapped[list | None] = mapped_column(JSONB)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    #: Days after the first thread this one may start. Two contacts at the same
    #: company touched on the same day reads as a blast, not as research.
    start_offset_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )

    #: Pursued although the sales rules left this person out — a rep's choice.
    chosen_by_rep: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    #: Built with no live signal to cite, because a rep allowed it. Both
    #: overrides send the sequence to be read in approval, never sampled.
    without_live_trigger: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    __table_args__ = (
        CheckConstraint(
            "thread_status IN ('active_primary','active_secondary','queued','not_activated')",
            name="thread_status_valid",
        ),
        CheckConstraint("rank > 0", name="rank_positive"),
        # Exactly one primary per strategy, and it is the top-ranked thread.
        CheckConstraint(
            "thread_status <> 'active_primary' OR rank = 1", name="primary_is_rank_one"
        ),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1",
            name="confidence_is_a_proportion",
        ),
        CheckConstraint("start_offset_days >= 0", name="offset_non_negative"),
        CheckConstraint(
            "without_live_trigger OR jsonb_array_length(trigger_signal_ids) > 0",
            name="threads_cite_a_trigger",
        ),
        # One live thread per contact per strategy: a person approached twice
        # about the same account is the failure this whole layer prevents.
        UniqueConstraint("strategy_id", "contact_id", name="one_thread_per_contact"),
        Index("ix_strategy_thread_strategy", "strategy_id", "rank"),
    )
