"""Domain 7 — Execution.

One row per attempted send. This is the far end of the whole system: every
guard upstream exists so that what lands here has been through evidence,
scoring, strategy, drafting, evaluation and a human.

`execution_record` insert **requires a matching approval**. That is enforced by
a trigger rather than by application code, because it is the single interlock
the entire outbound path hangs on: if it can be bypassed by a code path that
forgets to check, nothing else in the system matters.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

EXECUTION_STATUS = ("queued", "sent", "failed", "skipped")
#: Why a touch was skipped at send time. These are the send-time interlock —
#: the one deliberate exception to "nothing flows backward", because a company
#: that lands on the no-go list today would otherwise keep receiving touches
#: from a campaign decoupled from its queue.
SKIP_REASONS = (
    "account_disqualified",
    "no_go_list",
    "unsubscribed",
    "contact_unverified",
    "sequence_stopped",
)


class ExecutionRecord(Base):
    __tablename__ = "execution_record"

    sequence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outreach_sequence.id"), nullable=False
    )
    touch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("touch.id")
    )
    provider: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'lgm'")
    )
    #: The provider's own id for whatever this created — a lead, an enrolment.
    provider_ref: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    skip_reason: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    #: What the interlock saw at send time, kept so a skip can be explained
    #: months later without re-deriving the state that caused it.
    interlock_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','sent','failed','skipped')", name="status_valid"
        ),
        CheckConstraint(
            "skip_reason IS NULL OR skip_reason IN ('account_disqualified','no_go_list',"
            "'unsubscribed','contact_unverified','sequence_stopped')",
            name="skip_reason_valid",
        ),
        # A skip nobody can explain is indistinguishable from a bug, and the
        # rep never sees the touch at all.
        CheckConstraint(
            "status <> 'skipped' OR skip_reason IS NOT NULL", name="a_skip_says_why"
        ),
        CheckConstraint(
            "status <> 'failed' OR error IS NOT NULL", name="a_failure_says_why"
        ),
        CheckConstraint(
            "status <> 'sent' OR sent_at IS NOT NULL", name="a_send_has_a_timestamp"
        ),
        # One record per touch per attempt surface. Two 'sent' rows for one
        # touch would mean a recipient got the same message twice and the
        # metrics would report it as one.
        UniqueConstraint("touch_id", "status", name="one_record_per_touch_outcome"),
        Index("ix_execution_record_sequence", "sequence_id"),
    )


#: What LGM tells us happened, in our words. `status_change` covers a lead
#: moving through the campaign; the rest are messages.
EVENT_TYPES = (
    "message_sent",
    "message_received",
    "status_change",
    "unsubscribed",
    "other",
)


class OutreachEvent(Base):
    """One thing that happened after enrolment, as reported by the provider.

    Written by both routes — the inbox webhook and the poller — and identical
    whichever arrived first: `external_id` is unique per source, so the same
    message pushed and then polled is one row.

    `payload` is kept verbatim. It is provider data, read as data and never as
    instruction (invariant 10), and the first question about a surprising event
    is always what they actually sent us.
    """

    __tablename__ = "outreach_event"

    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'lgm'"))
    #: `webhook` or `poll`. A gap in one of them is invisible without this.
    received_via: Mapped[str] = mapped_column(Text, nullable=False)
    #: The provider's id for this message or event, where it gives one.
    external_id: Mapped[str | None] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str | None] = mapped_column(Text)
    direction: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    lgm_lead_id: Mapped[str | None] = mapped_column(Text)
    lgm_campaign_id: Mapped[str | None] = mapped_column(Text)
    conversation_id: Mapped[str | None] = mapped_column(Text)
    #: A short line for a list. The body lives in `payload`.
    preview: Mapped[str | None] = mapped_column(Text)

    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contact.id", ondelete="SET NULL")
    )
    sequence_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outreach_sequence.id", ondelete="SET NULL")
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outreach_campaign.id", ondelete="CASCADE")
    )
    payload: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        CheckConstraint("received_via IN ('webhook','poll')", name="received_via_valid"),
        CheckConstraint(
            "direction IS NULL OR direction IN ('sent','received')", name="direction_valid"
        ),
        Index(
            "uq_outreach_event_external", "source", "external_id",
            unique=True, postgresql_where=text("external_id IS NOT NULL"),
        ),
        Index("ix_outreach_event_campaign", "campaign_id", "occurred_at"),
        Index("ix_outreach_event_contact", "contact_id", "occurred_at"),
    )
