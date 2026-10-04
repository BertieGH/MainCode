"""Domain 6 — Content.

The whole arc is written in one pass at sequence creation, approved once, and
then **frozen**. LGM reads copy from the lead's custom attributes, not from us,
so once written there is no edit path — changing the words means stopping the
sequence and re-enrolling, which creates a new sequence from touch 1.

`draft` is versioned: regeneration adds a version and flips `is_current`, it
never overwrites. "This isn't what I approved" has to be answerable.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

CHANNELS = (
    "linkedin_connect", "linkedin_message", "linkedin_engage", "inmail", "email",
)
TOUCH_STATUS = ("pending", "scheduled", "sent", "skipped", "failed")
#: All touches move pending → written in one batch at enrolment, never per
#: step. `failed` blocks enrolment rather than letting a campaign start
#: half-written — content in our database is not content on the LGM lead.
CONTENT_SYNC = ("pending", "written", "failed")
STOP_REASONS = ("signal_expired", "reply_received", "compliance", "manual")
SUBJECT_SOURCES = ("lgm_template", "custom_attribute")
GENERATED_AS = ("arc", "regeneration")


class Touch(Base):
    __tablename__ = "touch"

    sequence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outreach_sequence.id", ondelete="CASCADE"), nullable=False
    )
    step_no: Mapped[int] = mapped_column(Integer, nullable=False)
    #: NULL means LGM decides when this step sends — which it always does.
    #: Kept for the rows written when the model was asked to propose a day.
    day_offset: Mapped[int | None] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending'")
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lgm_step_id: Mapped[str | None] = mapped_column(Text)

    #: Which `custom_attribute_N` this touch's body is written into.
    lgm_attribute: Mapped[str | None] = mapped_column(Text)
    content_sync_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending'")
    )
    #: The same timestamp across every touch in a sequence — they are written
    #: together or not at all.
    content_written_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stop_reason: Mapped[str | None] = mapped_column(Text)
    #: Subjects default to LGM-native to save attribute budget.
    subject_source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'lgm_template'")
    )

    __table_args__ = (
        CheckConstraint(
            "channel IN ('linkedin_connect','linkedin_message','linkedin_engage','inmail','email')",
            name="channel_valid",
        ),
        CheckConstraint(
            "status IN ('pending','scheduled','sent','skipped','failed')", name="status_valid"
        ),
        CheckConstraint(
            "content_sync_status IN ('pending','written','failed')", name="sync_status_valid"
        ),
        CheckConstraint(
            "subject_source IN ('lgm_template','custom_attribute')", name="subject_source_valid"
        ),
        CheckConstraint(
            "stop_reason IS NULL OR stop_reason IN "
            "('signal_expired','reply_received','compliance','manual')",
            name="stop_reason_valid",
        ),
        CheckConstraint("step_no > 0", name="step_positive"),
        CheckConstraint("day_offset IS NULL OR day_offset >= 0", name="day_offset_non_negative"),
        # A touch marked written must say where it was written, or a failed
        # attribute write is indistinguishable from a successful one.
        CheckConstraint(
            "content_sync_status <> 'written' OR lgm_attribute IS NOT NULL",
            name="written_names_its_attribute",
        ),
        CheckConstraint(
            "sent_at IS NULL OR status = 'sent'", name="only_sent_touches_have_a_sent_at"
        ),
        UniqueConstraint("sequence_id", "step_no", name="one_touch_per_step"),
        Index("ix_touch_sequence", "sequence_id", "step_no"),
    )


class Draft(Base):
    """Versioned message content. Regeneration adds a version, never overwrites."""

    __tablename__ = "draft"

    touch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("touch.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    subject: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    #: Every id here must be an approved proof point. Blocked at generation,
    #: not caught at review.
    cited_proof_point_ids: Mapped[list | None] = mapped_column(JSONB)
    #: Which signals this copy leans on, so the pre-send freshness check knows
    #: what to re-validate.
    cited_signal_ids: Mapped[list | None] = mapped_column(JSONB)
    #: dated | implied | durable — graded by the model, enforced by evaluation.
    signal_dependence: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'durable'")
    )
    model: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    generated_as: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'arc'")
    )
    #: signal_stale, proof_point_unapproved, rep_guidance, … so "this isn't
    #: what I approved" is answerable.
    regenerated_reason: Mapped[str | None] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    __table_args__ = (
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(
            "generated_as IN ('arc','regeneration','rep_edit')", name="generated_as_valid"
        ),
        CheckConstraint(
            "signal_dependence IN ('dated','implied','durable')", name="dependence_valid"
        ),
        # A regeneration without a reason loses the only record of why the
        # approved words changed.
        CheckConstraint(
            "generated_as <> 'regeneration' OR regenerated_reason IS NOT NULL",
            name="regeneration_needs_a_reason",
        ),
        UniqueConstraint("touch_id", "version", name="one_draft_per_version"),
        # Exactly one live draft per touch, enforced rather than assumed: two
        # current drafts means the copy sent is whichever the query happened to
        # return first.
        Index(
            "one_current_draft_per_touch",
            "touch_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )
