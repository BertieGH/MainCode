"""Domain 3 — Evidence and signals.

The audit trail, bottom to top: a document becomes `evidence`, evidence is
interpreted into a `signal`, and `signal_evidence` records which excerpts
support which conclusion.

Translated from `docs/schema/signals.sql`, which stays the reference. Two
deliberate deviations from that file, both forced by decisions already made:

* The DDL keys `signal_type` on `key`. Our registry carries a surrogate UUID
  with `key` unique, so the composite FK below needs an explicit
  UNIQUE (key, scope) to point at.
* `signal_evidence` is a Core table rather than an ORM class. Its primary key
  is (signal_id, evidence_id) — that composite *is* the guarantee that one
  signal cannot cite the same excerpt twice — and `Base` mandates a surrogate
  UUID id, which would silently allow the duplicate back in.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

SOURCE_TYPES = (
    "web", "news", "jobs", "linkedin", "crm", "provider", "filing", "manual",
)
CAPTURE_METHODS = ("conversation", "email", "event", "inbound", "other")
RAW_STATUS = ("stored", "unavailable", "purged")
STRENGTHS = ("low", "medium", "high")
LIFECYCLE_STATES = ("discovered", "validated", "active", "stale", "expired")
EVIDENCE_ROLES = ("primary", "supporting")


def _in(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    joined = ",".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({joined})", name=name)


class Evidence(Base):
    """Stored, never interpreted. The bottom of every audit trail.

    Immutable by policy: retention purges the object-storage snapshot by
    setting `raw_status='purged'`, and never deletes the row. A signal must
    never lose its citation.
    """

    __tablename__ = "evidence"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("run.id")
    )
    #: The research family that found it. Null for manual and CRM evidence, and
    #: for rows stored before families were recorded — never backfilled, since
    #: a guess here would put a passage under a search that did not find it.
    family: Mapped[str | None] = mapped_column(Text)
    #: The person a passage is about. Null for company evidence. Set null, not
    #: cascaded, if the contact goes — evidence is never deleted.
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contact.id", ondelete="SET NULL")
    )

    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_name: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    #: The passage a claim rests on.
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)

    #: When the fact was TRUE — not when we found it. A funding round from
    #: three years ago is not a trigger, however recently it was retrieved.
    observed_at: Mapped[date | None] = mapped_column(Date)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # manual capture only
    author_id: Mapped[str | None] = mapped_column(Text)
    capture_method: Mapped[str | None] = mapped_column(Text)

    #: Hash of the document. Deliberately NOT unique — see the dedup index.
    source_hash: Mapped[str] = mapped_column(Text, nullable=False)
    #: Hash of source_url + excerpt. This is the dedup key.
    excerpt_hash: Mapped[str] = mapped_column(Text, nullable=False)
    raw_ref: Mapped[str | None] = mapped_column(Text)
    raw_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'stored'")
    )
    reliability: Mapped[float | None] = mapped_column(Numeric(4, 3))

    __table_args__ = (
        _in("source_type", SOURCE_TYPES, "source_type_valid"),
        _in("raw_status", RAW_STATUS, "raw_status_valid"),
        CheckConstraint(
            "capture_method IS NULL OR capture_method IN "
            "('conversation','email','event','inbound','other')",
            name="capture_method_valid",
        ),
        CheckConstraint(
            "reliability IS NULL OR reliability BETWEEN 0 AND 1",
            name="reliability_is_a_proportion",
        ),
        # A manual observation must say who logged it and how, or it is an
        # unattributable claim wearing the same clothes as a sourced one.
        CheckConstraint(
            "source_type <> 'manual' "
            "OR (author_id IS NOT NULL AND capture_method IS NOT NULL)",
            name="manual_capture_is_attributed",
        ),
        # A stored snapshot must have somewhere to point.
        CheckConstraint(
            "raw_status <> 'stored' OR raw_ref IS NOT NULL", name="stored_has_a_ref"
        ),
        # One document yields MANY excerpts, so the dedup key is the excerpt,
        # not the document. Deduping on the document would admit only the first
        # excerpt; signals citing the rejected ones would then be dropped by the
        # missing-evidence guard, looking exactly like hallucinated citations.
        UniqueConstraint("account_id", "excerpt_hash", name="evidence_dedup"),
        Index("evidence_by_source", "account_id", "source_hash"),
        Index("evidence_by_type", "account_id", "source_type"),
        # The coverage tab opens one family of one run.
        Index("evidence_by_run_family", "run_id", "family"),
        Index(
            "evidence_by_contact", "contact_id",
            postgresql_where=text("contact_id IS NOT NULL"),
        ),
    )


class Signal(Base):
    """A typed, dated interpretation of evidence.

    Never written without at least one `signal_evidence` row — enforced by a
    deferred constraint trigger, because the invariant spans two tables and the
    join rows arrive after the signal.
    """

    __tablename__ = "signal"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="CASCADE"), nullable=False
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contact.id", ondelete="CASCADE")
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("run.id")
    )

    signal_type: Mapped[str] = mapped_column(Text, nullable=False)
    #: Denormalised from the registry so the contact-id rule below can be a
    #: CHECK rather than application code. The composite FK keeps them in step.
    scope: Mapped[str] = mapped_column(Text, nullable=False)

    summary: Mapped[str] = mapped_column(Text, nullable=False)
    business_implication: Mapped[str | None] = mapped_column(Text)
    strength: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)

    observed_at: Mapped[date] = mapped_column(Date, nullable=False)
    #: observed_at + the type's default_ttl_days.
    expires_at: Mapped[date | None] = mapped_column(Date)
    lifecycle_state: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'discovered'")
    )

    is_hypothesis: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("false")
    )
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("signal.id")
    )

    evidence: Mapped[list[Evidence]] = relationship(
        secondary=lambda: signal_evidence, lazy="selectin"
    )

    __table_args__ = (
        # Stops a contact-scoped type being written as a company signal: the
        # mismatch cannot be represented rather than merely being checked for.
        ForeignKeyConstraint(
            ["signal_type", "scope"],
            ["signal_type.key", "signal_type.scope"],
            name="signal_type_scope_fk",
        ),
        _in("scope", ("company", "contact"), "scope_valid"),
        _in("strength", STRENGTHS, "strength_valid"),
        _in("lifecycle_state", LIFECYCLE_STATES, "lifecycle_state_valid"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_is_a_proportion"),
        # A contact signal must name a contact; a company signal must not.
        CheckConstraint(
            "(scope = 'contact' AND contact_id IS NOT NULL) "
            "OR (scope = 'company' AND contact_id IS NULL)",
            name="contact_id_matches_scope",
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at >= observed_at", name="expiry_after_observation"
        ),
        Index("signal_by_account", "account_id", "lifecycle_state"),
        Index("signal_by_contact", "contact_id", postgresql_where=text("contact_id IS NOT NULL")),
        Index(
            "signal_live",
            "account_id",
            "expires_at",
            postgresql_where=text("lifecycle_state IN ('validated','active')"),
        ),
    )


#: Which evidence supports which signal.
#:
#: A Core table, not an ORM class: the primary key is the (signal_id,
#: evidence_id) pair, and that composite is what stops one signal citing the
#: same excerpt twice. `Base` would impose a surrogate UUID id and let the
#: duplicate back in.
#:
#: ON DELETE RESTRICT on evidence_id is deliberate — evidence cited by a signal
#: cannot be deleted. Retention purges the snapshot, never the row.
signal_evidence = Table(
    "signal_evidence",
    Base.metadata,
    Column(
        "signal_id",
        UUID(as_uuid=True),
        ForeignKey("signal.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "evidence_id",
        UUID(as_uuid=True),
        ForeignKey("evidence.id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    Column("role", Text, nullable=False, server_default=text("'supporting'")),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    CheckConstraint("role IN ('primary','supporting')", name="role_valid"),
    Index("signal_evidence_by_evidence", "evidence_id"),
)
