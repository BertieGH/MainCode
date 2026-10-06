"""Domain 2 — Accounts and people, plus the list selection layer.

`account_list` is an **import set**: a labelled bag of accounts that only grows
by import or manual add. It never syncs outward, and everything downstream is a
deliberate copy out of it rather than a live link into it.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Column,
    Table,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sqlalchemy.dialects.postgresql import JSONB as _RunJSONB

from app.database import Base

ACCOUNT_STATUS = ("new", "researching", "qualified", "disqualified", "active", "closed")
#: Tier 0 outcomes. `needs_review` is not a failure — it is the honest answer
#: when two companies are plausible, and forcing it into a guess is what
#: produces confident research about the wrong one.
RESOLUTION_STATUS = ("unresolved", "resolved", "needs_review", "rejected")
PIPELINE_STATUS = ("not_started", "running", "complete", "partial", "failed")
SENIORITY = ("c_level", "vp", "director", "manager", "ic", "unknown")


def _in(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    joined = ",".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({joined})", name=name)


class Account(Base):
    __tablename__ = "account"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str | None] = mapped_column(Text)
    linkedin_url: Mapped[str | None] = mapped_column(Text)
    industry: Mapped[str | None] = mapped_column(Text)
    #: `industry`, normalised for joining to `scoring_config.industry_multipliers`.
    #: Stored rather than computed on read so the join is indexable and so a
    #: mismatch is visible in the row rather than only at scoring time.
    industry_key: Mapped[str | None] = mapped_column(Text)

    #: Tier 0. `unresolved` → `resolved` / `needs_review` / `rejected`.
    #:
    #: Researching the wrong company fails silently — every artefact downstream
    #: comes out well-formed and about a different business. So the expensive
    #: stages refuse anything not `resolved`, and `needs_review` exists because
    #: "two plausible companies" is a real answer that must not be forced into
    #: a guess.
    resolution_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'unresolved'")
    )
    resolution_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    #: Which source answered. A wrong domain accepted weeks ago has to be
    #: traceable to whoever supplied it, not merely corrected.
    resolved_by: Mapped[str | None] = mapped_column(Text)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Runners-up, when the answer was not clear. What a rep needs in order to
    #: pick, rather than being told to go and search again themselves.
    resolution_candidates: Mapped[list | None] = mapped_column(JSONB)

    employee_count: Mapped[int | None] = mapped_column(Integer)
    #: When the count above was observed — **ours, not theirs**. A directory
    #: page carries no date, so the only honest timestamp is when we looked.
    employee_count_as_of: Mapped[date | None] = mapped_column(Date)
    #: The last *different* count, and when it was seen. Re-observing the same
    #: number refreshes `employee_count_as_of` alone, so this pair always spans
    #: a real change rather than the last two runs — which is what makes
    #: "grew from 30 to 33 since March" sayable.
    employee_count_before: Mapped[int | None] = mapped_column(Integer)
    employee_count_before_as_of: Mapped[date | None] = mapped_column(Date)
    revenue_band: Mapped[str | None] = mapped_column(Text)
    funding_stage: Mapped[str | None] = mapped_column(Text)
    hq_country: Mapped[str | None] = mapped_column(Text)
    hq_region: Mapped[str | None] = mapped_column(Text)
    #: The last company check: what the website and Apollo's organisation
    #: record said about country and LinkedIn page, and the disagreements left
    #: for a rep. Kept so a conflict survives a reload and Apollo is not paid
    #: twice for an answer already held. See `services/company_check.py`.
    company_check: Mapped[dict | None] = mapped_column(JSONB)
    #: When the account lost its last list and campaign queue with work behind
    #: it, and why. Dormant accounts are hidden, never deleted; joining a list
    #: again clears this. See `services/anchoring.py`.
    dormant_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dormant_reason: Mapped[str | None] = mapped_column(Text)

    crm_record_id: Mapped[str | None] = mapped_column(Text)
    icp_match_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    icp_match_reasons: Mapped[dict | None] = mapped_column(JSONB)
    #: Firmographics: what the company does, who it serves, how big it is,
    #: where it operates, what it is currently pushing. Metadata for the
    #: context builder, **not** a signal — nothing about a company's size or
    #: description says *now*, and giving it a TTL would mean expiring a fact
    #: that does not expire. Proposed during curation as a
    #: `firmographic_baseline` signal type; it is this instead.
    profile: Mapped[dict | None] = mapped_column(JSONB)

    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'new'"))
    research_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'not_started'")
    )
    research_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enrichment_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'not_started'")
    )
    enrichment_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    pipeline_note: Mapped[str | None] = mapped_column(Text)
    disqualified_reason: Mapped[str | None] = mapped_column(Text)

    contacts: Mapped[list[Contact]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )

    __table_args__ = (
        _in("resolution_status", RESOLUTION_STATUS, "resolution_status_valid"),
        _in("status", ACCOUNT_STATUS, "status_valid"),
        _in("research_status", PIPELINE_STATUS, "research_status_valid"),
        _in("enrichment_status", (*PIPELINE_STATUS, "skipped"), "enrichment_status_valid"),
        # Domain is the primary dedup key, but it is nullable — a manually added
        # account may not have one yet. A plain UNIQUE would collapse every such
        # row into one; a partial index leaves them alone.
        Index(
            "uq_account_domain",
            func.lower(text("domain")),
            unique=True,
            postgresql_where=text("domain IS NOT NULL"),
        ),
        Index("ix_account_status", "status"),
        Index("ix_account_dormant", "dormant_at", postgresql_where=text("dormant_at IS NOT NULL")),
        CheckConstraint(
            "status <> 'disqualified' OR disqualified_reason IS NOT NULL",
            name="disqualified_needs_a_reason",
        ),
    )


class AccountAlias(Base):
    """Alternative names and domains, so a re-import matches rather than duplicates."""

    __tablename__ = "account_alias"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    alias_type: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("alias", "alias_type", name="uq_account_alias"),
        _in("alias_type", ("name", "domain", "crm_id"), "alias_type_valid"),
    )


class Contact(Base):
    __tablename__ = "contact"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="CASCADE"), nullable=False
    )
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    seniority: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'unknown'")
    )
    persona_role: Mapped[str | None] = mapped_column(Text)
    buying_role: Mapped[str | None] = mapped_column(Text)
    linkedin_url: Mapped[str | None] = mapped_column(Text)
    #: Who this person is, as standing description — what they own, how long
    #: they have been there, what they talk about. Undated and never aged: a
    #: profile page carries no publication time, and a role is not untrue for
    #: being long-held. The dated event is `contact_role_change`.
    #: See `schemas/profile.ContactProfile`.
    profile: Mapped[dict | None] = mapped_column(JSONB)
    #: Which LGM lead this person resolves to. Set before enrolment; the
    #: enrolment lock is keyed on it rather than on contact_id.
    lgm_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lgm_identity.id")
    )

    email: Mapped[str | None] = mapped_column(Text)
    email_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'unverified'")
    )
    email_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    email_provider: Mapped[str | None] = mapped_column(Text)
    email_provider_record_id: Mapped[str | None] = mapped_column(Text)

    phone: Mapped[str | None] = mapped_column(Text)
    phone_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'unverified'")
    )
    phone_provider: Mapped[str | None] = mapped_column(Text)
    phone_provider_record_id: Mapped[str | None] = mapped_column(Text)

    is_hypothesis: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    #: Where the provider places this person. Set by a reveal; a CSV rarely
    #: carries it.
    city: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    #: Which Apollo person this is, so a later search recognises them rather
    #: than suggesting them again.
    apollo_person_id: Mapped[str | None] = mapped_column(Text)
    #: When the address was last graded `verified`. One verified long ago is
    #: flagged for re-checking — see `verification.needs_recheck`.
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: The contact this person is saved as in the Apollo account, and when.
    #: Apollo charges again for a person looked up but never saved.
    apollo_contact_id: Mapped[str | None] = mapped_column(Text)
    apollo_saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    account: Mapped[Account] = relationship(back_populates="contacts")

    #: Off limits: never enriched, queued, researched or written to again.
    #: Their evidence and history stay — this closes doors, it does not delete.
    do_not_contact: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    #: Required when the flag is set — asked months later by somebody who was
    #: not there, and enforced by `dnc_carries_a_reason`.
    do_not_contact_reason: Mapped[str | None] = mapped_column(Text)
    do_not_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "NOT do_not_contact OR do_not_contact_reason IS NOT NULL",
            name="dnc_carries_a_reason",
        ),
        _in("seniority", SENIORITY, "seniority_valid"),
        _in("email_status", ("verified", "risky", "invalid", "unverified"), "email_status_valid"),
        _in("phone_status", ("verified", "unverified", "invalid"), "phone_status_valid"),
        _in("email_provider", ("apollo", "contactout", "manual"), "email_provider_valid"),
        _in("phone_provider", ("apollo", "contactout", "manual"), "phone_provider_valid"),
        _in(
            "buying_role",
            ("economic_buyer", "technical_buyer", "champion", "influencer", "blocker"),
            "buying_role_valid",
        ),
        Index("ix_contact_account", "account_id"),
        # One row per person per account. Re-running enrichment updates rather
        # than duplicating.
        Index(
            "uq_contact_email_per_account",
            "account_id",
            func.lower(text("email")),
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
        ),
    )


#: What a suggestion can be. See `ContactSuggestion.status`.
SUGGESTION_STATUS = ("proposed", "accepted", "rejected", "revealed", "known", "not_found")


class ContactSuggestion(Base):
    """Somebody Apollo's free search proposed, waiting for a rep's decision.

    The search reveals nothing: a first name, an obfuscated surname, a title,
    and whether Apollo holds an email and a location. Enough to choose, not
    enough to contact — which is the point. Only an accepted suggestion is
    revealed, and the reveal is what costs a credit.

    `contact_id` is the contact this person already is (matched by Apollo id,
    or by first name and the visible letters of the surname), or the one the
    reveal created.
    """

    __tablename__ = "contact_suggestion"

    #: The list it was found while working. Null once that list is deleted: a
    #: rejected or revealed suggestion outlives it, so a rejected person is not
    #: suggested again.
    list_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account_list.id", ondelete="SET NULL")
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="CASCADE"), nullable=False
    )
    apollo_person_id: Mapped[str] = mapped_column(Text, nullable=False)
    first_name: Mapped[str | None] = mapped_column(Text)
    #: Apollo's obfuscated surname, e.g. `Pe***d`. Never a real surname.
    last_name_hint: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    #: Which ICP persona the search was for — its buying role, else its first title.
    persona: Mapped[str | None] = mapped_column(Text)
    buying_role: Mapped[str | None] = mapped_column(Text)
    has_email: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    has_location: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    has_direct_phone: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contact.id", ondelete="SET NULL")
    )
    #: `proposed` → `accepted` / `rejected`; `accepted` → `revealed` or
    #: `not_found`. `known` is a person already on the list with everything a
    #: reveal would add — nothing to buy.
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'proposed'"))
    note: Mapped[str | None] = mapped_column(Text)
    revealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        _in("status", SUGGESTION_STATUS, "status_valid"),
        CheckConstraint(
            "buying_role IS NULL OR buying_role IN "
            "('economic_buyer', 'technical_buyer', 'champion', 'influencer', 'blocker')",
            name="buying_role_valid",
        ),
        UniqueConstraint(
            "account_id", "apollo_person_id", name="uq_contact_suggestion_account_person"
        ),
        Index("ix_contact_suggestion_list", "list_id", "status"),
    )


class AccountList(Base):
    """An import set. Static — grows only by import or manual add."""

    __tablename__ = "account_list"

    label: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)

    members: Mapped[list[AccountListMember]] = relationship(
        back_populates="list", cascade="all, delete-orphan"
    )

    __table_args__ = (_in("source", ("csv", "manual", "crm"), "source_valid"),)



#: Which services an account list was imported for. Many-to-many: one list can
#: serve two offerings, and choosing the services is what narrows the ICP
#: picker to something small enough to read.
account_list_service = Table(
    "account_list_service",
    Base.metadata,
    Column(
        "list_id",
        UUID(as_uuid=True),
        ForeignKey("account_list.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "service_id",
        UUID(as_uuid=True),
        ForeignKey("service_catalog.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

#: Which buyer profiles this list is being worked for. Read at enrichment time
#: to decide who is worth a metered call — see `verification.resolve_targeting`.
#: The link is to the *profile*, not a version: a run resolves the active
#: version and records which one it used, so a later edit cannot rewrite what
#: an earlier run says it did.
account_list_icp = Table(
    "account_list_icp",
    Base.metadata,
    Column(
        "list_id",
        UUID(as_uuid=True),
        ForeignKey("account_list.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "icp_profile_id",
        UUID(as_uuid=True),
        ForeignKey("icp_profile.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

class AccountListMember(Base):
    __tablename__ = "account_list_member"

    list_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account_list.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="CASCADE"), nullable=False
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    added_by: Mapped[str | None] = mapped_column(Text)
    import_row_reason: Mapped[str | None] = mapped_column(Text)

    list: Mapped[AccountList] = relationship(back_populates="members")

    __table_args__ = (
        UniqueConstraint("list_id", "account_id", name="uq_list_member"),
        Index("ix_list_member_list", "list_id"),
    )


class Run(Base):
    """One pipeline execution against one account."""

    __tablename__ = "run"

    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="CASCADE")
    )
    list_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account_list.id", ondelete="SET NULL")
    )
    objective: Mapped[str | None] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'resolution'"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    triggered_by: Mapped[str | None] = mapped_column(Text)
    #: Which installation mode produced this run's artefacts. Stamped here
    #: because evidence, signals, context, qualification and strategy all carry
    #: `run_id` — so one column makes every downstream row's provenance
    #: answerable without touching six tables.
    mode: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'production'")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger)
    cache_read_tokens: Mapped[int | None] = mapped_column(BigInteger)
    error: Mapped[str | None] = mapped_column(Text)
    #: The ICP versions that decided what this run looked for and who it looked
    #: into. "Why was this person researched?" has to survive an ICP edit.
    icp_version_ids: Mapped[list | None] = mapped_column(_RunJSONB)

    __table_args__ = (
        _in(
            "stage",
            (
                "resolution", "research", "signals", "context", "qualification",
                "strategy", "content", "evaluation", "awaiting_approval", "done",
            ),
            "stage_valid",
        ),
        _in("status", ("queued", "running", "succeeded", "failed", "cancelled"), "status_valid"),
        _in("mode", ("production", "demo"), "mode_valid"),
        Index("ix_run_account", "account_id"),
        CheckConstraint(
            "status <> 'failed' OR error IS NOT NULL", name="failed_needs_an_error"
        ),
    )
