"""Domains 5b and 5c — selection layers, cadence registration, and the lock.

Three labelled layers sit between an import and a send, and **each boundary is a
copy, not a link**:

    account_list ──copy──► campaign_queue ──copy + lock──► outreach_campaign

That is why there is no sync machinery here. `source_list_id` on a queue member
is a provenance stamp with no behaviour — a dead reference kept so "where did
this come from" has an answer, deliberately nullable so it survives the source
list being deleted.

`cadence_shape` is a **mirror of LGM, not a source of truth**. Gen360 never
authors a cadence; it records which pre-built LGM campaign a shape maps to and
which `custom_attribute_N` each step consumes.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
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

QUEUE_STATUS = ("draft", "locked")
CAMPAIGN_STATUS = (
    "draft", "pending_approval", "executing", "paused", "completed", "cancelled",
)
#: `paused` deliberately holds the enrolment lock: a paused sequence still has
#: unsent touches whose copy sits in the lead's attributes, and releasing on
#: pause would let a second campaign overwrite them.
SEQUENCE_NON_TERMINAL = ("pending_approval", "approved", "executing", "paused")
SEQUENCE_STATUS = (
    "draft", "pending_eval", *SEQUENCE_NON_TERMINAL,
    "completed", "stopped", "cancelled",
)
RESOLUTION_STATE = ("resolved", "conflict")


class CampaignQueue(Base):
    """A mutable draft selection. Locked forever the moment it is promoted."""

    __tablename__ = "campaign_queue"

    label: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'draft'")
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promoted_to_campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outreach_campaign.id")
    )
    #: Set when this queue was made by cloning a locked one. Cloning is the only
    #: way to make a variant — re-opening a locked queue would leave "which
    #: version did campaign 2 use?" unanswerable.
    cloned_from_queue_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaign_queue.id")
    )

    #: The service everyone in it is approached about, and the ICP it is built
    #: for — chosen when the queue is created, copied into the campaign.
    service_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_catalog.id", ondelete="SET NULL")
    )
    icp_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("icp_profile.id", ondelete="SET NULL")
    )
    #: The ICP version in force when it was chosen.
    icp_version: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        CheckConstraint("status IN ('draft','locked')", name="status_valid"),
        # Locked and locked_at move together, or "is this editable" and "when
        # did it stop being editable" can disagree.
        CheckConstraint(
            "(status = 'locked') = (locked_at IS NOT NULL)", name="locked_at_consistent"
        ),
    )


class CampaignQueueMember(Base):
    """An account copied into a queue, with the scores as they stood."""

    __tablename__ = "campaign_queue_member"

    queue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaign_queue.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id"), nullable=False
    )
    #: Provenance stamp only — no behaviour. Nullable so it survives the source
    #: list being deleted, because the fact that it came from somewhere is
    #: worth keeping even when the somewhere is gone.
    source_list_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account_list.id", ondelete="SET NULL")
    )
    qualification_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("qualification.id")
    )
    added_by: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        # Dedups a queue built from overlapping lists.
        UniqueConstraint("queue_id", "account_id", name="one_membership_per_queue"),
        Index("ix_campaign_queue_member_account", "account_id"),
    )


class CampaignQueueContact(Base):
    """A person chosen for a queue.

    Enrichment and research are company-wide, but a campaign reaches people:
    a rep chooses who. The company comes with them — it must pass the same
    queue rule — and `source_list_id` is a provenance stamp, as for members.
    """

    __tablename__ = "campaign_queue_contact"

    queue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaign_queue.id", ondelete="CASCADE"), nullable=False
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contact.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="CASCADE"), nullable=False
    )
    source_list_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account_list.id", ondelete="SET NULL")
    )
    added_by: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("queue_id", "contact_id", name="uq_campaign_queue_contact_queue_contact"),
        Index("ix_campaign_queue_contact_queue", "queue_id"),
        Index("ix_campaign_queue_contact_account", "account_id"),
    )


class OutreachCampaign(Base):
    __tablename__ = "outreach_campaign"

    label: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    cadence_shape_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cadence_shape.id")
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'draft'")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: What promotion could not copy in, and why — one line per skipped
    #: account or contact. Stored rather than returned once, because "why is
    #: this campaign smaller than the queue that fed it?" is asked later, not
    #: at the moment of promotion.
    promotion_notes: Mapped[list | None] = mapped_column(JSONB)

    #: The service everyone in it is approached about, and the ICP it is built
    #: for — chosen when the queue is created, copied into the campaign.
    service_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_catalog.id", ondelete="SET NULL")
    )
    icp_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("icp_profile.id", ondelete="SET NULL")
    )
    #: The ICP version in force when it was chosen.
    icp_version: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','pending_approval','executing','paused','completed','cancelled')",
            name="status_valid",
        ),
    )


class OutreachCampaignSource(Base):
    """Which queues fed this campaign. Recorded at promotion, never re-read."""

    __tablename__ = "outreach_campaign_source"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outreach_campaign.id", ondelete="CASCADE"), nullable=False
    )
    queue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaign_queue.id"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("campaign_id", "queue_id", name="one_source_per_pair"),
    )


class CadenceShape(Base):
    """A registration of a cadence that exists in LGM. Not a definition of one.

    `verified_at` is load bearing. Enrolment is refused when LGM reports the
    campaign changed after it, because a stale mapping writes copy into the
    wrong step and nothing downstream detects that — the message sends, to the
    right person, saying the wrong thing at the wrong point in the sequence.
    """

    __tablename__ = "cadence_shape"

    key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    lgm_campaign_id: Mapped[str] = mapped_column(Text, nullable=False)
    touch_count: Mapped[int] = mapped_column(Integer, nullable=False)
    #: NULL, for everything registered since timing became LGM's. Their API
    #: exposes no step delay anywhere, so a span here could only ever have been
    #: typed by a rep — see migration a7e4d2c9b5f3.
    span_days: Mapped[int | None] = mapped_column(Integer)
    #: {"1": "custom_attribute_1", ...} — which attribute each step's **body**
    #: consumes.
    attribute_map: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    #: The same for each step's **subject**, where its template reads one at
    #: all. Empty for a step whose subject is fixed in LGM, and for every
    #: LinkedIn step, which has no subject. A custom subject cannot be sent to
    #: a step that is not listed here: there would be nowhere for it to appear.
    subject_attribute_map: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    #: {"1": "email", "2": "linkedin"} — the channel LGM runs each step on.
    #: Distinct from `lgm_channels`, which is the campaign's whole set and
    #: cannot say which step is which. A step with no subject line is a fact
    #: about its channel, and this is where that fact lives.
    step_channels: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    #: {"1": {"position": 4, "type": "GOOGLE_SEND_EMAIL", "name": "Not Accepted - Email"}}
    #: — where each step sits in the whole LGM campaign and what it is called
    #: there. `/messages` gives an order among *templates*; a campaign's own
    #: steps include visits, connection requests and waits that carry nothing
    #: of ours, so "step 1" here is rarely step 1 over there. The name is the
    #: only place a branch says it is one.
    step_meta: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    #: {"custom_attribute_3": "what a rep chose to call it"} — **overrides
    #: only**, usually empty. The name shown is derived from the live mapping
    #: (`lgm_client.derive_labels`) unless a slot appears here, so a template
    #: that moves a slot to another step renames it automatically. LGM lets a
    #: slot be named in its own interface and publishes those names on no
    #: route: templates read `{{customAttribute3}}` and leads key on
    #: `customAttribute1..20`. Presentation, never the binding itself.
    slot_labels: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    attributes_used: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    selection_rule: Mapped[dict | None] = mapped_column(JSONB)

    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by: Mapped[str | None] = mapped_column(Text)
    #: From LGM campaign metadata, polled hourly.
    #: The audience this campaign runs over. LGM has no per-lead enrol call:
    #: writing a lead into this audience *is* enrolling them.
    lgm_audience_name: Mapped[str | None] = mapped_column(Text)
    lgm_audience_id: Mapped[str | None] = mapped_column(Text)
    lgm_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lgm_channels: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    lgm_status: Mapped[str | None] = mapped_column(Text)
    #: Was computed from span_days — the step at and after which a touch may
    #: not cite a dated signal. NULL without a span, and the rule it fed is a
    #: fallback only: a signal live on the day of drafting is the gate.
    durable_from_step: Mapped[int | None] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    __table_args__ = (
        CheckConstraint("touch_count > 0", name="touch_count_positive"),
        CheckConstraint("span_days IS NULL OR span_days > 0", name="span_positive"),
        # 20 per lead, global across campaigns. Verified against a live
        # account: 11, 15 and 20 all store and read back, and a 21st is
        # refused. The documentation said 10, and said the overflow was
        # dropped in silence; neither held (migration b1c7f4a9d6e2).
        CheckConstraint(
            "attributes_used BETWEEN 0 AND 20", name="within_the_attribute_budget"
        ),
        CheckConstraint(
            "verified_at IS NULL OR verified_by IS NOT NULL",
            name="verification_is_attributed",
        ),
    )


class LgmIdentity(Base):
    """How LGM would cluster our contacts into one lead.

    Keyed on LGM's identifiers rather than ours, because an index on
    `contact_id` has a hole: if LGM collapses two of our contact rows into one
    lead, both pass that index and still overwrite each other's attributes.

    Three columns rather than one computed key, because LGM's dedup is a
    priority cascade and a single coalesce cannot express it. Contact A with
    LinkedIn X and email E, and contact B with only email E, resolve to
    different coalesced keys — but LGM merges them.
    """

    __tablename__ = "lgm_identity"

    #: Normalised: host, casing and trailing slash stripped.
    linkedin_slug: Mapped[str | None] = mapped_column(Text, unique=True)
    #: Lower-cased, trimmed.
    email: Mapped[str | None] = mapped_column(Text, unique=True)
    #: lower(first || last || company). The fallback only.
    name_company_key: Mapped[str | None] = mapped_column(Text, unique=True)
    resolution_state: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'resolved'")
    )
    #: Why it conflicts, for the pre-flight screen.
    conflict_detail: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "resolution_state IN ('resolved','conflict')", name="resolution_state_valid"
        ),
        # An identity with no identifier at all would match everything and
        # nothing, and would silently collect unrelated contacts.
        CheckConstraint(
            "linkedin_slug IS NOT NULL OR email IS NOT NULL OR name_company_key IS NOT NULL",
            name="at_least_one_identifier",
        ),
        CheckConstraint(
            "resolution_state <> 'conflict' OR conflict_detail IS NOT NULL",
            name="conflict_needs_a_reason",
        ),
    )


class OutreachSequence(Base):
    """One sequence per person in a campaign. At most one live per LGM identity.

    `contact_id` is who it is for. `thread_id` is the strategy for them —
    optional, because a person promoted before a strategy exists gets their
    sequence now; pre-flight refuses to execute until one is linked.
    """

    __tablename__ = "outreach_sequence"

    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategy_thread.id", ondelete="CASCADE")
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contact.id")
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outreach_campaign.id")
    )
    cadence_shape_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cadence_shape.id")
    )
    lgm_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lgm_identity.id")
    )
    start_offset_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'draft'")
    )
    lgm_campaign_id: Mapped[str | None] = mapped_column(Text)
    lgm_lead_id: Mapped[str | None] = mapped_column(Text)
    #: Which deterministic rule chose the shape, and on what fact. "Why did
    #: this account get the enterprise cadence?" is answerable from the row.
    selection_log: Mapped[dict | None] = mapped_column(JSONB)

    #: When this person first replied, and when anything last happened to
    #: them. Kept on the row so a list does not aggregate every event to say
    #: "replied" — see `outreach_event` for what actually happened.
    first_reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: Taken out of this campaign before anything was sent, and why. The row
    #: stays `cancelled` rather than being deleted: it is the record that this
    #: person was chosen, drafted, perhaps approved, and then pulled.
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdraw_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "status <> 'cancelled' OR withdraw_reason IS NOT NULL",
            name="withdrawal_carries_a_reason",
        ),
        CheckConstraint(
            "status IN ('draft','pending_eval','pending_approval','approved',"
            "'executing','paused','completed','stopped','cancelled')",
            name="status_valid",
        ),
        CheckConstraint("start_offset_days >= 0", name="offset_non_negative"),
        # THE LOCK. A partial unique index makes two live sequences for one LGM
        # lead unrepresentable, so a race between two concurrent promotions
        # cannot slip through and no future code path can bypass it by
        # forgetting a check. Application logic here would pass a sequential
        # test and fail under real concurrency.
        Index(
            "one_active_sequence_per_lgm_identity",
            "lgm_identity_id",
            unique=True,
            postgresql_where=text(
                "status IN ('pending_approval','approved','executing','paused')"
            ),
        ),
        Index("ix_outreach_sequence_campaign", "campaign_id"),
        Index("ix_outreach_sequence_contact", "contact_id"),
        CheckConstraint("thread_id IS NOT NULL OR contact_id IS NOT NULL", name="names_a_person"),
    )


class DeferredEnrolment(Base):
    """A contact the lock excluded, recorded rather than dropped.

    When the blocking sequence goes terminal a worker enrols them — subject to
    the same approval gate as anything else. Nothing sends unreviewed just
    because it was queued.
    """

    __tablename__ = "deferred_enrolment"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outreach_campaign.id", ondelete="CASCADE"), nullable=False
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contact.id"), nullable=False
    )
    blocked_by_sequence_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outreach_sequence.id")
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'waiting'")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('waiting','enrolled','abandoned')", name="status_valid"
        ),
        UniqueConstraint("campaign_id", "contact_id", name="one_deferral_per_pair"),
    )
