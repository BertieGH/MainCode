"""Domain 1 — Configuration (Enterprise Memory).

Set up once, versioned, read by every run.

Two patterns recur and are worth naming up front:

**Versioned singletons** (`org_profile`, `sales_rules`, `scoring_config`) hold
many rows but exactly one active. That "exactly one" is enforced by a partial
unique index on a constant expression, not by application code — two concurrent
activations would otherwise both pass a check-then-write and leave the system
with two active configs and no error.

**Versioned per-key** (`llm_config`) is the same, scoped to a key: one active
row per scenario.
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
    Column,
    LargeBinary,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# --------------------------------------------------------------------------
# org_profile — CGVAK's own business profile
# --------------------------------------------------------------------------
class OrgProfile(Base):
    __tablename__ = "org_profile"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # No `icp` here. Who we sell *to* lives on `IcpProfile`, shared across the
    # services that sell to it; this row is who is *selling*, which is a
    # different question and the only one without another home.
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    __table_args__ = (
        # Only one row may be active. Unique on a constant, filtered on the flag.
        Index(
            "uq_org_profile_single_active",
            text("(true)"),
            unique=True,
            postgresql_where=text("is_active"),
        ),
        UniqueConstraint("version", name="uq_org_profile_version"),
    )


# --------------------------------------------------------------------------
# service_catalog + proof_point
# --------------------------------------------------------------------------
class ServiceCatalog(Base):
    __tablename__ = "service_catalog"

    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    positioning_angles: Mapped[list | None] = mapped_column(JSONB)
    #: Who signs off for this service, broadly — "CIO / Head of IT". Context
    #: for the prompt, not a filter: the people to reach are the buyer personas
    #: on an ICP, and only there.
    economic_buyer: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    proof_points: Mapped[list[ProofPoint]] = relationship(back_populates="service")
    icps: Mapped[list[IcpProfile]] = relationship(
        secondary="service_icp_link", back_populates="services"
    )




class IcpProfile(Base):
    """A kind of buyer, named once and shared.

    The identity, deliberately separate from the definition in
    `IcpProfileVersion`. Services and account lists link to *this* row, so
    activating a new version does not orphan every link that pointed at the
    old one — which is what a single versioned table would do.

    Shared rather than owned by a service: two services genuinely can sell to
    the same kind of buyer, and an account list has to be able to target an ICP
    without dragging a service along with it. See `docs/11`.
    """

    __tablename__ = "icp_profile"

    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)

    versions: Mapped[list[IcpProfileVersion]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by="IcpProfileVersion.version",
    )
    services: Mapped[list[ServiceCatalog]] = relationship(
        secondary="service_icp_link", back_populates="icps"
    )


class IcpProfileVersion(Base):
    """What an ICP actually says, at one point in time.

    Versioned because an enrichment run records which version selected its
    contacts. Editing in place would make "why were these people chosen?"
    unanswerable the moment somebody widened the profile.

    A new run resolves whichever version is active; a finished run keeps the
    id of the one it used. Both halves of that rule need this table.
    """

    __tablename__ = "icp_profile_version"

    icp_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("icp_profile.id", ondelete="CASCADE"),
        nullable=False,
    )
    definition: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    profile: Mapped[IcpProfile] = relationship(back_populates="versions")

    __table_args__ = (
        Index(
            "uq_icp_profile_single_active",
            "icp_profile_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        UniqueConstraint(
            "icp_profile_id", "version", name="uq_icp_profile_version_number"
        ),
    )


#: Which services sell to which buyers. Many-to-many, chosen from the ICP side
#: ("Product/services to sell"). An ICP needs at least one — one that sells
#: nothing is a note rather than configuration — but a service needs none: it
#: is what you sell, and who to sell it to is the ICP's question. The minimum
#: is enforced by the API, since a row-level rule cannot express "at least one
#: link" without making the first insert impossible.
service_icp_link = Table(
    "service_icp_link",
    Base.metadata,
    Column(
        "service_id",
        UUID(as_uuid=True),
        ForeignKey("service_catalog.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "icp_profile_id",
        UUID(as_uuid=True),
        ForeignKey("icp_profile.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class ProofPoint(Base):
    """Only `is_approved` rows may appear in a draft.

    The block is at generation, not at review: an unapproved claim never reaches
    a rep, so it cannot be waved through by a tired reviewer.
    """

    __tablename__ = "proof_point"

    service_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_catalog.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    client_industry: Mapped[str | None] = mapped_column(Text)
    client_size_band: Mapped[str | None] = mapped_column(Text)
    metrics: Mapped[dict | None] = mapped_column(JSONB)
    is_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    source: Mapped[str | None] = mapped_column(Text)

    service: Mapped[ServiceCatalog | None] = relationship(back_populates="proof_points")

    __table_args__ = (
        CheckConstraint(
            "kind IN ('case_study','metric','logo','testimonial')",
            name="kind_valid",
        ),
        Index("ix_proof_point_service_id", "service_id"),
        # Only approved proof points are ever selected for a draft.
        Index(
            "ix_proof_point_approved",
            "service_id",
            postgresql_where=text("is_approved"),
        ),
    )


# --------------------------------------------------------------------------
# writing_sample — the voice reference for drafting
# --------------------------------------------------------------------------
class WritingSample(Base):
    __tablename__ = "writing_sample"

    channel: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    __table_args__ = (
        CheckConstraint("channel IN ('linkedin','email')", name="channel_valid"),
    )


# --------------------------------------------------------------------------
# sales_rules — versioned singleton
# --------------------------------------------------------------------------
class SalesRules(Base):
    __tablename__ = "sales_rules"

    version: Mapped[int] = mapped_column(Integer, nullable=False)
    priority_threshold: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    persona_weight_threshold: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    max_concurrent_threads: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("2")
    )
    thread_start_offset_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("3")
    )
    signal_ttl_days: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    sample_rate: Mapped[float] = mapped_column(
        Numeric(4, 3), nullable=False, server_default=text("0.40")
    )
    no_go: Mapped[dict | None] = mapped_column(JSONB)
    compliance: Mapped[dict | None] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    __table_args__ = (
        Index(
            "uq_sales_rules_single_active",
            text("(true)"),
            unique=True,
            postgresql_where=text("is_active"),
        ),
        UniqueConstraint("version", name="uq_sales_rules_version"),
        CheckConstraint("max_concurrent_threads > 0", name="thread_cap_positive"),
        CheckConstraint("sample_rate > 0 AND sample_rate <= 1", name="sample_rate_range"),
    )


# --------------------------------------------------------------------------
# scoring_config — versioned singleton, deterministic maths
# --------------------------------------------------------------------------
class ScoringConfig(Base):
    __tablename__ = "scoring_config"

    version: Mapped[int] = mapped_column(Integer, nullable=False)
    dimension_weights: Mapped[dict] = mapped_column(JSONB, nullable=False)
    #: `{industry_key: {dimension: factor}}`. Keys are normalised industry
    #: strings — see `scoring.normalise_industry`. Rows come from the active
    #: ICP's industries; an industry no longer in the ICP is shown as orphaned
    #: rather than dropped, because removing it silently would change how the
    #: whole book scores without appearing in any diff a person reads.
    industry_multipliers: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    #: `{size_band: {dimension: factor}}` for `small`, `mid` and `large`.
    #: Never `unknown` — that is the absence of a headcount, not a size.
    size_multipliers: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    persona_role_weights: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    band_cutoffs: Mapped[dict] = mapped_column(JSONB, nullable=False)
    man_view_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    #: The weakest band that may be added to a queue. `low` means no
    #: restriction. Above it, an account with no qualification is refused too —
    #: "not qualified yet" is a different instruction from "too weak".
    min_queue_band: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'low'")
    )

    __table_args__ = (
        CheckConstraint(
            "min_queue_band IN ('low','medium','high')", name="min_queue_band_valid"
        ),
        Index(
            "uq_scoring_config_single_active",
            text("(true)"),
            unique=True,
            postgresql_where=text("is_active"),
        ),
        UniqueConstraint("version", name="uq_scoring_config_version"),
    )


# --------------------------------------------------------------------------
# llm_call — what every model call cost, in tokens
# --------------------------------------------------------------------------
class LlmCall(Base):
    """One model call. Written for every stage, including the ones that fail.

    Spend used to be invisible: `run` had the columns and never filled them,
    and the two most expensive stages made no run row at all. A stage could be
    configured into thinking for thirty thousand tokens a call and nothing
    would show it — which is exactly what happened to `strategy_synthesis`.

    Tokens, not currency. A price is a fact about a contract with a vendor and
    changes without notice; a rate invented here would read as authoritative
    and be wrong. Multiply these by your own rates.
    """

    __tablename__ = "llm_call"

    scenario: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    effort: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cache_write_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    #: The provider's reason, never a payload — prompts carry account research
    #: and a prospect's own words.
    error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0", name="tokens_non_negative"
        ),
    )


# --------------------------------------------------------------------------
# llm_config — versioned per scenario
# --------------------------------------------------------------------------
class LlmConfig(Base):
    __tablename__ = "llm_config"

    scenario: Mapped[str] = mapped_column(Text, nullable=False)
    #: Which vendor runs this stage. Separate from `model` because a model id
    #: alone cannot be routed — and because the picker needs to scope its
    #: options to one vendor's list.
    provider: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'anthropic'")
    )
    model: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'claude-opus-5'")
    )
    effort: Mapped[str] = mapped_column(Text, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    thinking_mode: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'adaptive'")
    )
    output_contract: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    __table_args__ = (
        # One active row per scenario, not one overall.
        Index(
            "uq_llm_config_active_per_scenario",
            "scenario",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        UniqueConstraint("scenario", "version", name="uq_llm_config_scenario_version"),
        CheckConstraint(
            "effort IN ('low','medium','high','xhigh','max')", name="effort_valid"
        ),
        # A format check, not a membership one. Which providers exist is
        # data — see migration 4d6fa083b322.
        CheckConstraint(
            r"provider ~ '^[a-z][a-z0-9_-]{1,39}$'", name="provider_valid"
        ),
        CheckConstraint("max_tokens > 0", name="max_tokens_positive"),
    )


# --------------------------------------------------------------------------
# model_availability — which models this installation may use
# --------------------------------------------------------------------------
class ModelAvailability(Base):
    """The shortlist a stage may be pointed at, per provider.

    Two separate questions were being answered by one list, and they have
    different owners. *What a vendor offers* is a fact about the vendor and
    lives in `provider_catalogue`. *What this installation is willing to spend
    money on* is a commercial decision — a workspace may be entitled to Opus
    and choose to run everything on Sonnet — and it belongs in the database
    where it can change without a deploy.

    Stored as `{provider: [model_id, ...]}`. An absent provider means "no
    choice has been made", which resolves to every model the catalogue knows
    for it; that keeps a fresh install working rather than presenting twelve
    stages with an empty dropdown.

    Versioned like every other config surface. A draft written last month was
    written by whichever model was selected then, and editing that row in place
    would make the audit trail disagree with the copy.
    """

    __tablename__ = "model_availability"

    #: `{provider: [model_id, ...]}`. Not a join table: the set is small, it is
    #: read whole on every config screen, and versioning a JSONB column is one
    #: row rather than a diff across two tables.
    enabled: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    __table_args__ = (
        Index(
            "uq_model_availability_single_active",
            text("(true)"),
            unique=True,
            postgresql_where=text("is_active"),
        ),
        UniqueConstraint("version", name="uq_model_availability_version"),
    )


# --------------------------------------------------------------------------
# installation_mode — demo or production
# --------------------------------------------------------------------------
class InstallationMode(Base):
    """Whether this installation is a real book or a sandbox.

    `production` is the default and the strict one: the three mandatory
    external connections must be configured and verified before anything else
    is usable.

    `demo` exists because a client evaluating the product should be able to
    walk the whole application without an Anthropic account, a ContactOut
    contract and a La Growth Machine seat. It satisfies the mandatory slots
    with named stubs — **not** with fake credentials. Writing a row into
    `integration_credential` with `status='valid'` would be claiming a live
    round-trip that never happened, and that column is the one thing the setup
    gate trusts; faking it once makes it worthless everywhere.

    Versioned rather than a mutable flag so the switch has a history. "Was this
    campaign built while the installation was a sandbox?" is a question that
    gets asked exactly once, at the worst possible moment, and a flag that was
    edited in place cannot answer it.
    """

    __tablename__ = "installation_mode"

    mode: Mapped[str] = mapped_column(Text, nullable=False)
    #: Free text. Why somebody switched — "client walkthrough", "go live".
    reason: Mapped[str | None] = mapped_column(Text)
    switched_by: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    __table_args__ = (
        CheckConstraint("mode IN ('production','demo')", name="mode_valid"),
        Index(
            "uq_installation_mode_single_active",
            text("(true)"),
            unique=True,
            postgresql_where=text("is_active"),
        ),
        UniqueConstraint("version", name="uq_installation_mode_version"),
    )


# --------------------------------------------------------------------------
# enrichment_config — the contact waterfall, in order
# --------------------------------------------------------------------------
class EnrichmentConfig(Base):
    """Which enrichment providers to ask, and in what order.

    A waterfall rather than a race, because these are metered per call: asking
    everyone and keeping the best answer multiplies the bill on every contact
    the first provider already resolved.

    The order is configuration rather than code because it is a commercial
    decision — which contract has the better rate, which vendor has better
    coverage in a region — and it changes without a deploy. Versioned like
    every other config surface: a contact enriched last month was enriched
    under a particular order, and editing that row in place would make the
    per-field `sources` on the contact unexplainable.
    """

    __tablename__ = "enrichment_config"

    #: Provider keys, best first. The first to satisfy every required field
    #: ends the waterfall.
    provider_order: Mapped[list] = mapped_column(JSONB, nullable=False)
    #: What has to be present before we stop asking. `email` alone by default:
    #: a phone number nobody will call is not worth a second metered call.
    required_fields: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[\"email\"]'::jsonb")
    )
    #: Tier 0 sources, best first. Apollo's domain lookup is the cheapest call
    #: in the system and returns firmographics as a by-product; the LLM
    #: fallback runs only when it comes back empty.
    resolution_order: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[\"apollo_org\", \"website\", \"llm_web\"]'::jsonb"),
    )
    #: How many people Apollo's free search may propose per persona per
    #: account. Each is a decision for a rep and, if accepted, a credit.
    suggestions_per_persona: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("5")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    __table_args__ = (
        CheckConstraint(
            "suggestions_per_persona BETWEEN 1 AND 25",
            name="suggestions_per_persona_range",
        ),
        Index(
            "uq_enrichment_config_single_active",
            text("(true)"),
            unique=True,
            postgresql_where=text("is_active"),
        ),
        UniqueConstraint("version", name="uq_enrichment_config_version"),
        # An empty waterfall is not a configuration, it is a broken one — and
        # it would fail silently, as "no provider returned anything".
        CheckConstraint(
            "jsonb_array_length(provider_order) > 0",
            name="the_waterfall_has_at_least_one_provider",
        ),
    )


class ResearchConfig(Base):
    """How research spends — starting with how old an answer may be.

    Research is several model calls per account. A second list working the
    same company used to pay for all of it again, for company facts that had
    not changed since last week. `freshness_days` is how old a family's result
    may be and still be reused; "Rerun research" ignores it on purpose.
    """

    __tablename__ = "research_config"

    freshness_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("30")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    __table_args__ = (
        Index(
            "uq_research_config_single_active",
            text("(true)"),
            unique=True,
            postgresql_where=text("is_active"),
        ),
        UniqueConstraint("version", name="uq_research_config_version"),
        CheckConstraint(
            "freshness_days BETWEEN 1 AND 365", name="freshness_is_a_day_to_a_year"
        ),
    )


# --------------------------------------------------------------------------
# integration_credential
# --------------------------------------------------------------------------
class IntegrationCredential(Base):
    """Encrypted at rest. The API returns `last_four` and never the value.

    `value_encrypted` is deliberately LargeBinary rather than Text: it cannot be
    rendered into a log line or an f-string by accident and look like a password.
    """

    __tablename__ = "integration_credential"

    provider: Mapped[str] = mapped_column(Text, nullable=False)
    credential_type: Mapped[str] = mapped_column(Text, nullable=False)
    value_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    last_four: Mapped[str | None] = mapped_column(String(4))
    #: Where this provider issues keys. Carried on the row rather than looked
    #: up, so a provider somebody added is not a four-character suffix with no
    #: origin.
    console_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'untested'")
    )
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Why the last test ended as it did, as a short machine-readable slug.
    #: `status` alone cannot carry this: `expired` covers both a key that has
    #: genuinely expired and an account with no credit, and those need
    #: different words on screen and different actions from the reader.
    last_test_code: Mapped[str | None] = mapped_column(Text)
    #: The same reason in a sentence, for the tooltip. Persisted so it survives
    #: a reload — a test result that vanishes on refresh leaves a status badge
    #: nobody can explain. Always our own words: a provider's response body can
    #: quote the key that was sent, so nothing from one is ever stored here.
    last_test_detail: Mapped[str | None] = mapped_column(Text)
    spend_cap: Mapped[float | None] = mapped_column(Numeric(12, 2))

    __table_args__ = (
        UniqueConstraint("provider", "credential_type", name="uq_credential_provider_type"),
        CheckConstraint(
            r"provider ~ '^[a-z][a-z0-9_-]{1,39}$'", name="provider_valid"
        ),
        CheckConstraint(
            "credential_type IN ('api_key','token','webhook_secret','base_url')",
            name="credential_type_valid",
        ),
        CheckConstraint(
            "status IN ('valid','invalid','untested','expired')", name="status_valid"
        ),
    )


# --------------------------------------------------------------------------
# research_source — where research looks
# --------------------------------------------------------------------------
class ResearchSource(Base):
    """A place worth reading about an account. Configuration, not code.

    This was a closed tuple in `query_families.py`, and closed for a good
    reason: a source no runner knows about is indistinguishable from one that
    ran and found nothing, so it reports as a permanent coverage gap on a
    prospect who may be perfectly well covered.

    A table keeps that guarantee while removing the deploy. The key is still
    checked against a registry before it can be claimed; the registry is now a
    thing a rep can add to. `builtin` rows are the old closed set, seeded on
    migration under their original keys so that coverage written before this
    existed still lines up with coverage written after.

    What is *not* here is per-account addressing — a feed URL, a careers page.
    A source is a class of place, true for every account; which of them a given
    company actually has is discovered at run time and recorded in coverage.
    """

    __tablename__ = "research_source"

    key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    #: What lives here, in the words that will go into the search. This is the
    #: brief: a source reads what it reads, and extraction decides afterwards
    #: which signal types the passages support.
    description: Mapped[str] = mapped_column(Text, nullable=False)
    #: How the reading is done — see `query_families.Runner`. A rep may add
    #: `search` sources; `fetch` and `provider` need code behind them, so they
    #: arrive seeded and cannot be invented from the screen.
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'search'"))
    scopes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[\"company\"]'::jsonb")
    )
    #: Reviews corroborate a signal but never create one: a single complaint is
    #: noise, a repeated theme is evidence (docs/06 §7.1 rule 1).
    support_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    #: How long an answer from this source stays good, overriding the global
    #: window. News is worth re-reading weekly and filings quarterly, and one
    #: number for both either wastes searches or reads stale.
    reuse_days: Mapped[int | None] = mapped_column(Integer)
    #: Seeded with the code that runs it. Its `key` and `kind` are fixed —
    #: renaming one would orphan every coverage row already written under it.
    builtin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'active'")
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('search','fetch','provider','manual')", name="kind_valid"
        ),
        CheckConstraint(
            "status IN ('active','paused','deprecated')", name="status_valid"
        ),
        CheckConstraint("jsonb_array_length(scopes) > 0", name="scopes_not_empty"),
        CheckConstraint(
            "reuse_days IS NULL OR reuse_days > 0", name="reuse_days_positive"
        ),
    )


# --------------------------------------------------------------------------
# signal_type — the registry
# --------------------------------------------------------------------------
class SignalType(Base):
    """Configuration, not schema. Adding a type is an INSERT.

    Retired by deprecation, never deletion: a qualification decided partly on a
    since-retired type must still be able to explain itself.
    """

    __tablename__ = "signal_type"

    key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    default_ttl_days: Mapped[int] = mapped_column(Integer, nullable=False)
    #: How long a fact of this type stays worth *reading*, as against how long
    #: it stays a hook — see `default_ttl_days`. NULL means three times the
    #: TTL. Research refuses a document older than this and extraction refuses
    #: a signal dated beyond it, so a signal can no longer be born already
    #: expired. Read it through `services.durability.durability_of`, never
    #: directly: the fallback is the normal case, not the exception.
    durability_days: Mapped[int | None] = mapped_column(Integer)
    weight: Mapped[float] = mapped_column(
        Numeric(4, 2), nullable=False, server_default=text("1.00")
    )
    produced_by: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    #: What to look for, in the words of whoever wants it found. Run as its own
    #: search when the type claims no family — which is what lets a type be
    #: added without code. It is a prompt fragment: editing it changes what
    #: every later coverage row means.
    search_instruction: Mapped[str | None] = mapped_column(Text)
    #: Types sharing a label are searched once, together. Without it a registry
    #: of twenty types is twenty calls per account, most of them reading the
    #: same pages.
    search_group: Mapped[str | None] = mapped_column(Text)
    #: `event` — a dated fact, one signal per occurrence: two funding rounds are
    #: two signals. `theme` — an ongoing state, one live signal per account or
    #: person that moves forward when a newer reading arrives: what a company
    #: keeps publishing about is one theme, not a signal per post. Dedupe treats
    #: the two differently — see `extraction._current_themes`.
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'event'"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("scope IN ('company','contact')", name="scope_valid"),
        CheckConstraint("kind IN ('event','theme')", name="kind_valid"),
        # `signal` carries a composite FK on (signal_type, scope) so that a
        # contact-scoped type cannot be written as a company signal. That FK
        # needs a unique key to point at; `key` alone is not it.
        UniqueConstraint("key", "scope", name="key_scope"),
        # Three states, and the difference matters: pause is reversible and
        # deprecate is terminal. Collapsing them would mean a type taken out
        # while it is tuned can never come back.
        CheckConstraint(
            "status IN ('active','paused','deprecated')", name="status_valid"
        ),
        CheckConstraint("default_ttl_days > 0", name="ttl_positive"),
        # Durability shorter than the TTL would refuse the evidence before the
        # signal stopped counting — expiry could never be reached, because
        # nothing could be stored to reach it.
        CheckConstraint(
            "durability_days IS NULL OR durability_days >= default_ttl_days",
            name="durability_covers_ttl",
        ),
        CheckConstraint("weight >= 0", name="weight_non_negative"),
        # deprecated_at is set exactly when status says so
        CheckConstraint(
            "(status = 'deprecated') = (deprecated_at IS NOT NULL)",
            name="deprecated_at_consistent",
        ),
        # A type paused six months ago is probably retired in practice, so the
        # timestamp is worth having — and keeping it in step with the status
        # stops a resumed type carrying a stale "paused since".
        CheckConstraint(
            "(status = 'paused') = (paused_at IS NOT NULL)",
            name="paused_at_consistent",
        ),
        # Extraction reads only active types, on every run.
        Index(
            "ix_signal_type_active",
            "scope",
            postgresql_where=text("status = 'active'"),
        ),
    )
