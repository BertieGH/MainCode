"""Request and response contracts for Domain 1.

The response models are the enforcement point for one rule that cannot be left
to endpoint authors: **a credential value never leaves the process.**
``CredentialOut`` has no field capable of carrying it, so no future endpoint can
return one by forgetting to strip it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Effort = Literal["low", "medium", "high", "xhigh", "max"]
#: Retained for anything that still wants the shipped set. It is no longer
#: the set of *allowed* providers — see `PROVIDER_KEY`.
Provider = Literal["anthropic", "openai", "gemini", "apollo", "contactout", "lgm", "crm"]
CredentialType = Literal["api_key", "token", "webhook_secret", "base_url"]
Scope = Literal["company", "contact"]
Channel = Literal["linkedin", "email"]
ProofKind = Literal["case_study", "metric", "logo", "testimonial"]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------
# org profile
# --------------------------------------------------------------------------
class OrgProfileIn(BaseModel):
    """Who is *selling*.

    No `icp`. Who we sell to lives on `IcpProfile`, shared across the services
    linked to it — a description of a buyer belongs with the offers it buys,
    not with the seller.
    """

    name: str = Field(min_length=1)
    description: str | None = None


class OrgProfileOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str | None
    version: int
    is_active: bool
    created_at: datetime


# --------------------------------------------------------------------------
# service catalog + proof points
# --------------------------------------------------------------------------
class IcpProfileIn(BaseModel):
    """A new ICP, with the services it sells to.

    `service_codes` is required and must be non-empty. An ICP linked to nothing
    is a note rather than configuration — no stage would ever read it — and the
    minimum is enforced here rather than by a constraint because a row-level
    rule cannot express "at least one link" without making the first insert
    impossible.
    """

    name: str = Field(min_length=1, max_length=80)
    description: str | None = None
    definition: dict = Field(default_factory=dict)
    service_codes: list[str] = Field(min_length=1)


#: Which buyer an ICP is for. Two, and only two: `tech_company` is an ISV, a
#: SaaS business or an IT product company — software is what it sells —
#: and `enterprise` is everything else, a non-technology business running
#: internal IT. Insurance brokerages sit inside `enterprise` rather than beside
#: it.
ICP_TRACKS = ("enterprise", "tech_company")


class IcpDefinitionIn(BaseModel):
    """A new *version* of an existing profile's definition."""

    definition: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def track_is_known(self) -> IcpDefinitionIn:
        """Refuse a track nobody reads.

        The definition is a free JSON document, so an unrecognised key is
        normally harmless. `track` is not: the strategy and drafting prompts
        branch on it, and a value they do not know falls through to "no track
        stated" — which is the safe behaviour but silent. "enterprize" would
        cost every draft on that list its register, with nothing anywhere
        saying so.
        """
        track = self.definition.get("track")
        if track is None:
            return self
        if track not in ICP_TRACKS:
            raise ValueError(
                f"track must be one of {', '.join(ICP_TRACKS)} — got {track!r}"
            )
        return self


class IcpServicesIn(BaseModel):
    """Which services this ICP sells to. Replaces the whole set."""

    service_codes: list[str] = Field(min_length=1)


class IcpProfileOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    #: The active definition, or `None` when no version has been written yet.
    #: Distinguished from `{}` on purpose: a linked profile nobody has
    #: described cannot target anyone, and enrichment refuses it.
    definition: dict | None
    version: int | None
    service_codes: list[str]
    #: How many account lists point at this profile. Zero means it can be
    #: deleted outright; anything else means deprecate.
    list_count: int = 0


def _blank_to_none(v: str | None) -> str | None:
    """An empty box means "not said", which is stored as nothing, not as ''."""
    if v is None:
        return None
    v = v.strip()
    return v or None


class ServiceIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    positioning_angles: list[str] = Field(default_factory=list)
    #: Who signs off, broadly. The people to reach are an ICP's buyer personas.
    economic_buyer: str | None = None
    is_active: bool = True

    @field_validator("code")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()

    _economic_buyer = field_validator("economic_buyer")(_blank_to_none)


class ServiceUpdate(BaseModel):
    """What a service says about itself. The code is not here: strategy
    threads and matrix cells refer to it, and it never changes."""

    name: str | None = Field(None, min_length=1)
    description: str | None = Field(None, min_length=1)
    positioning_angles: list[str] | None = None
    economic_buyer: str | None = None

    _economic_buyer = field_validator("economic_buyer")(_blank_to_none)


class ServiceOut(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    description: str
    positioning_angles: list[str] | None
    economic_buyer: str | None
    is_active: bool


class ProofPointIn(BaseModel):
    service_id: uuid.UUID | None = None
    kind: ProofKind
    title: str = Field(min_length=1)
    body: str = Field(min_length=1)
    client_industry: str | None = None
    client_size_band: str | None = None
    metrics: dict = Field(default_factory=dict)
    source: str | None = None
    # Deliberately absent: is_approved. Approval is a separate, deliberate act —
    # see the approve endpoint. Allowing it here would let a proof point arrive
    # pre-approved in the same request that created it.


class ProofPointOut(ORMModel):
    id: uuid.UUID
    service_id: uuid.UUID | None
    kind: str
    title: str
    body: str
    client_industry: str | None
    client_size_band: str | None
    metrics: dict | None
    is_approved: bool
    source: str | None


# --------------------------------------------------------------------------
# writing samples
# --------------------------------------------------------------------------
class WritingSampleIn(BaseModel):
    channel: Channel
    subject: str | None = None
    body: str = Field(min_length=1)
    notes: str | None = None
    is_active: bool = True


class WritingSampleOut(ORMModel):
    id: uuid.UUID
    channel: str
    subject: str | None
    body: str
    notes: str | None
    is_active: bool


# --------------------------------------------------------------------------
# sales rules
# --------------------------------------------------------------------------
class SalesRulesIn(BaseModel):
    priority_threshold: Annotated[float, Field(ge=0, le=100)]
    persona_weight_threshold: Annotated[float, Field(ge=0, le=100)]
    max_concurrent_threads: Annotated[int, Field(ge=1, le=10)]
    thread_start_offset_days: Annotated[int, Field(ge=0, le=30)]
    signal_ttl_days: dict[str, int] = Field(default_factory=dict)
    sample_rate: Annotated[float, Field(gt=0, le=1)] = 0.40
    no_go: dict = Field(default_factory=dict)
    compliance: dict = Field(default_factory=dict)

    @field_validator("signal_ttl_days")
    @classmethod
    def _positive_ttls(cls, v: dict[str, int]) -> dict[str, int]:
        bad = [k for k, days in v.items() if days <= 0]
        if bad:
            raise ValueError(f"TTL must be positive; got non-positive for {bad}")
        return v


class SalesRulesOut(ORMModel):
    id: uuid.UUID
    version: int
    is_active: bool
    priority_threshold: float
    persona_weight_threshold: float
    max_concurrent_threads: int
    thread_start_offset_days: int
    signal_ttl_days: dict
    sample_rate: float
    no_go: dict | None
    compliance: dict | None
    created_at: datetime


# --------------------------------------------------------------------------
# scoring config
# --------------------------------------------------------------------------
DIMENSIONS = ("fit", "opportunity", "buyer", "commercial", "intent", "engagement")


class ScoringConfigIn(BaseModel):
    dimension_weights: dict[str, float]
    #: `{industry_key: {dimension: factor}}` and `{size_band: {dimension: factor}}`.
    #: Both are applied and the result renormalised once — see
    #: `scoring.effective_weights`.
    industry_multipliers: dict[str, dict[str, float]] = Field(default_factory=dict)
    size_multipliers: dict[str, dict[str, float]] = Field(default_factory=dict)
    persona_role_weights: dict[str, float] = Field(default_factory=dict)
    band_cutoffs: dict[str, float]
    man_view_enabled: bool = True
    #: The weakest band that may join a queue; `low` is no restriction.
    min_queue_band: Literal["low", "medium", "high"] = "low"

    @field_validator("dimension_weights")
    @classmethod
    def _all_six_dimensions(cls, v: dict[str, float]) -> dict[str, float]:
        missing = set(DIMENSIONS) - set(v)
        unknown = set(v) - set(DIMENSIONS)
        if missing:
            raise ValueError(f"missing dimension weights: {sorted(missing)}")
        if unknown:
            raise ValueError(f"unknown dimensions: {sorted(unknown)}")
        return v

    @field_validator("dimension_weights")
    @classmethod
    def _weights_sum_to_100(cls, v: dict[str, float]) -> dict[str, float]:
        """The six dimensions are a distribution and must total 100.

        Without this, weights of 20/20/15/15/20/10 and 40/40/30/30/40/20 produce
        identical rankings but wildly different absolute scores — so a
        `priority_threshold` of 65 means something different after an edit, and
        the band cut-offs silently stop matching the numbers they were set
        against. Nothing errors; the book just re-bands overnight.

        Industry and size multipliers apply *on top* of these and are
        re-normalised once at scoring time, which is why they are separate
        fields rather than baked in here.
        """
        total = round(sum(v.values()), 6)
        if total != 100:
            raise ValueError(
                f"dimension weights must total 100, got {total}. "
                "They are a distribution across the six dimensions, not independent knobs."
            )
        return v

    @field_validator("band_cutoffs")
    @classmethod
    def _bands_ordered(cls, v: dict[str, float]) -> dict[str, float]:
        if "high" not in v or "medium" not in v:
            raise ValueError("band_cutoffs needs both 'high' and 'medium'")
        if v["high"] <= v["medium"]:
            # Otherwise every Medium account also clears High and the band
            # becomes meaningless without anything erroring.
            raise ValueError("'high' cutoff must be above 'medium'")
        return v


class ScoringConfigOut(ORMModel):
    id: uuid.UUID
    version: int
    is_active: bool
    dimension_weights: dict
    industry_multipliers: dict
    size_multipliers: dict
    persona_role_weights: dict
    band_cutoffs: dict
    man_view_enabled: bool
    min_queue_band: str = "low"
    created_at: datetime


# --------------------------------------------------------------------------
# llm config
# --------------------------------------------------------------------------
#: A provider key, not a member of a fixed set. Which vendors exist is data —
#: this only rules out shapes that would silently become distinct providers,
#: like " Anthropic " next to "anthropic".
PROVIDER_KEY = r"^[a-z][a-z0-9_-]{1,39}$"


class LlmConfigIn(BaseModel):
    scenario: str = Field(min_length=1)
    provider: str = Field(default="anthropic", pattern=PROVIDER_KEY)
    model: str = Field(default="claude-opus-5", min_length=1)
    effort: Effort
    max_tokens: Annotated[int, Field(ge=256, le=128_000)]
    thinking_mode: str = "adaptive"
    output_contract: str = Field(min_length=1)


class LlmConfigOut(ORMModel):
    id: uuid.UUID
    scenario: str
    provider: str
    model: str
    effort: str
    max_tokens: int
    thinking_mode: str
    output_contract: str
    version: int
    is_active: bool
    #: Whether a stage on this provider can actually run. Not stored — derived
    #: from whether an adapter exists, which is a property of the code.
    runnable: bool = True


class ModelOptionOut(BaseModel):
    id: str
    label: str
    structured_output: bool
    effort: bool
    prompt_caching: bool
    #: frontier | balanced | economy. Lets a stage be set to "the cheap one"
    #: without anybody memorising model ids.
    tier: str = "balanced"
    notes: str | None = None


class ProviderOut(BaseModel):
    """A provider we ship suggestions for. Not the list of allowed providers."""

    key: str
    label: str
    kind: str
    purpose: str
    console_url: str
    runnable: bool
    verifiable: bool = True
    credential_types: list[str]
    models: list[ModelOptionOut]


# --------------------------------------------------------------------------
# enrichment waterfall
# --------------------------------------------------------------------------
class EnrichmentConfigIn(BaseModel):
    #: Best first. Duplicates and unknown keys are rejected by the endpoint —
    #: a waterfall that asks the same provider twice bills twice for the same
    #: answer.
    provider_order: list[str] = Field(min_length=1)
    required_fields: list[str] = Field(default_factory=lambda: ["email"])
    #: People Apollo's free search may propose per persona per account.
    suggestions_per_persona: int = Field(default=5, ge=1, le=25)


class EnrichmentConfigOut(ORMModel):
    id: uuid.UUID
    provider_order: list[str]
    required_fields: list[str]
    suggestions_per_persona: int = 5
    version: int
    is_active: bool


class ResearchConfigIn(BaseModel):
    #: How old a family's result may be and still be reused. A day to a year:
    #: zero would mean "never reuse", which is what "Rerun research" is for.
    freshness_days: int = Field(ge=1, le=365)


class ResearchConfigOut(ORMModel):
    #: None, with version 0, when nothing has been saved — the default applies.
    id: uuid.UUID | None
    version: int
    is_active: bool
    freshness_days: int
    created_at: datetime | None = None


# --------------------------------------------------------------------------
# model availability
# --------------------------------------------------------------------------
class ProviderAvailabilityOut(BaseModel):
    provider: str
    label: str
    #: Whether stages can actually run on this provider.
    runnable: bool
    #: Model ids a stage may be pointed at.
    enabled: list[str]
    #: Everything the catalogue knows, enabled or not — the tick-list.
    catalogue: list[str]
    #: Enabled ids the catalogue does not know. Vendor ids drift.
    custom: list[str]
    #: No choice has been made; the catalogue is standing in.
    defaulted: bool


class ModelInUseOut(BaseModel):
    provider: str
    model: str
    #: Stages that would be stranded if this model were removed.
    scenarios: list[str]


class AvailabilityOut(BaseModel):
    providers: list[ProviderAvailabilityOut]
    in_use: list[ModelInUseOut] = Field(default_factory=list)


class AvailabilityIn(BaseModel):
    #: `{provider: [model_id, ...]}`. A provider left out has made no choice
    #: and resolves to its whole catalogue.
    enabled: dict[str, list[str]]


# --------------------------------------------------------------------------
# installation mode
# --------------------------------------------------------------------------
class ModeIn(BaseModel):
    mode: Literal["production", "demo"]
    #: Why. Kept because the switch is versioned, and a history of "someone
    #: changed it" without "why" answers nothing.
    reason: str | None = None
    switched_by: str | None = None
    #: Required to leave demo mode when demo-produced runs exist. Naming the
    #: risk and making the caller acknowledge it is the point — see the
    #: endpoint.
    acknowledge_demo_data: bool = False


class ModeOut(ORMModel):
    id: uuid.UUID
    mode: str
    reason: str | None
    switched_by: str | None
    version: int
    is_active: bool


# --------------------------------------------------------------------------
# setup readiness
# --------------------------------------------------------------------------
class CredentialStateOut(BaseModel):
    provider: str
    label: str
    status: str
    last_four: str | None = None
    console_url: str | None = None
    #: An adapter exists to do this provider's actual work.
    runnable: bool
    #: The key can be checked against the vendor. Independent of `runnable` —
    #: a Gemini key is checkable and no stage can run on it.
    verifiable: bool = True
    #: Carried through so the setup screen and the integrations screen cannot
    #: disagree about what the same credential's badge says.
    last_test_code: str | None = None
    last_test_detail: str | None = None


class SlotOut(BaseModel):
    kind: str
    title: str
    why: str
    #: `missing` / `unverified` / `ready`. Three states, because "you have not
    #: added a key" and "you added one that has not been verified" send the
    #: reader somewhere different.
    state: str
    satisfied: bool
    blocker: str | None = None
    #: Satisfied, but something downstream will still fail. Never gates.
    warning: str | None = None
    credentials: list[CredentialStateOut] = Field(default_factory=list)


class ReadinessOut(BaseModel):
    #: Everything connected, outreach included. The whole-installation answer.
    ready: bool
    #: LLM and enrichment connected — enough to import, enrich, research,
    #: qualify and strategise. **This is what the navigation locks on.**
    #:
    #: Separate from `ready` because La Growth Machine only matters at send
    #: time: gating the rest on it sealed an installation that could do
    #: everything up to a draft, to prevent a disappointment two stages later
    #: that the outreach routes refuse anyway.
    workable: bool = False
    #: `production` or `demo`. An unlocked menu means two very different
    #: things, so every screen is told which.
    mode: str = "production"
    #: Runs produced while in demo mode. Non-zero in production is the state
    #: worth surfacing: fixture evidence beside real evidence.
    demo_runs: int = 0
    slots: list[SlotOut]
    blockers: list[str]
    #: Reported even when `ready` is true — see `Slot.warning`.
    warnings: list[str] = Field(default_factory=list)
    #: Configuration decisions nobody has made yet — a service to sell, and an
    #: ICP saying who it is for. A second category alongside the credential
    #: slots, because a key connects you to a vendor without telling it who to
    #: look for.
    requirements: list[str] = Field(default_factory=list)
    enrichment_order: list[str]
    #: Stored credentials belonging to no slot — a provider name this build
    #: cannot classify, which in practice means a typo. Returned so the screen
    #: can offer a delete: providers are typeable, and a row rendered nowhere
    #: is a live secret nobody can remove without SQL.
    unrecognised: list[CredentialStateOut] = Field(default_factory=list)


# --------------------------------------------------------------------------
# credentials
# --------------------------------------------------------------------------
class CredentialIn(BaseModel):
    #: Free-form key rather than an enum: a provider can be added without a
    #: deploy. Shape is checked so a stray space cannot create a second,
    #: identical-looking provider.
    provider: str = Field(pattern=PROVIDER_KEY)
    credential_type: CredentialType
    value: str = Field(min_length=1, repr=False)  # repr=False: never in a traceback
    spend_cap: float | None = None
    #: Where this provider issues keys. Filled from the catalogue for the
    #: vendors we know; supplied by whoever adds a new one.
    console_url: str | None = None


class CredentialOut(ORMModel):
    """Has no field that can carry the secret. That is the whole design.

    A future endpoint cannot leak a credential by forgetting to redact it,
    because there is nowhere for the value to go.
    """

    id: uuid.UUID
    provider: str
    credential_type: str
    last_four: str | None
    status: str
    last_tested_at: datetime | None
    spend_cap: float | None
    console_url: str | None = None
    #: Why the last test ended as it did, as a short slug the UI maps to a
    #: label. `status` alone cannot distinguish "this key expired" from "this
    #: account has no credit", and those need different words and different
    #: actions from the reader.
    last_test_code: str | None = None
    #: The same reason in a sentence, for a tooltip. Carries the *outcome*,
    #: never the value: a provider's message is reduced to its class before it
    #: is stored, because a rejection body can quote the key that was sent.
    last_test_detail: str | None = None


# --------------------------------------------------------------------------
# signal types
# --------------------------------------------------------------------------
class SignalTypeIn(BaseModel):
    key: str = Field(min_length=2, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1)
    description: str | None = None
    scope: Scope
    default_ttl_days: Annotated[int, Field(ge=1, le=3650)]
    #: How long a fact of this type stays worth reading, as against how long it
    #: stays a hook. Null means three times the TTL — the default the rule was
    #: stated as, and the right answer for nearly every type. Set it only where
    #: the facts genuinely outlive that: an acquisition is permanently true.
    durability_days: Annotated[int, Field(ge=1, le=7300)] | None = None
    weight: Annotated[float, Field(ge=0, le=5)] = 1.0
    produced_by: list[str] = Field(default_factory=list)
    #: What to look for. Required when the type claims no family — otherwise
    #: nothing would ever run it, and a type that never runs is a permanent
    #: coverage gap wearing a registry row.
    search_instruction: str | None = Field(default=None, max_length=2000)
    #: Types sharing this label are searched once, together.
    search_group: str | None = Field(default=None, max_length=80)
    #: `event` — one signal per dated occurrence; `theme` — one live signal
    #: that moves forward. See `SignalType.kind`.
    kind: Literal["event", "theme"] = "event"

    @model_validator(mode="after")
    def durability_covers_ttl(self) -> SignalTypeIn:
        """Refuse a durability shorter than the TTL, here rather than at the DB.

        A type like this could never produce a usable signal: research would
        refuse the evidence before the signal stopped counting, so expiry would
        be unreachable because nothing could be stored to reach it. The check
        constraint catches it too, but a 500 from an aborted transaction is a
        worse answer to a form than a 422 naming the field.
        """
        if (
            self.durability_days is not None
            and self.durability_days < self.default_ttl_days
        ):
            raise ValueError(
                "durability_days must be at least default_ttl_days — a fact "
                "cannot stop being worth reading before it stops being a hook"
            )
        return self

    # Deliberately not refused here: a type with neither a source nor an
    # instruction is allowed, because registering one before deciding how it
    # will be found is a real flow (`test_no_families_yet_is_allowed`). It is
    # reported instead — `build_plan` returns it in `orphan_types` and the
    # screen shows it as "never runs", which is the honest state rather than a
    # silent coverage gap.

    # Which sources exist is a question for the database now that the registry
    # is a table, so the check lives in the route rather than here. The reason
    # for checking at all is unchanged and worth restating: an unrunnable
    # source name reports as a permanent coverage gap, which looks exactly like
    # a prospect nobody could find anything about.


class NewSourceProposal(BaseModel):
    """A place worth reading that the registry does not have yet.

    Returned separately from the keys that already exist, and never created on
    its own. A source is what a coverage row is named after; one invented by a
    model and written straight to the registry would start reporting gaps in a
    place nobody agreed to look.
    """

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=2, max_length=60, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=80)
    #: What lives there, written as the brief a search will actually run.
    description: str = Field(min_length=1, max_length=600)
    scopes: list[Scope] = Field(default_factory=lambda: ["company"])
    why: str = Field(default="", max_length=400)


class TypeSourceAsk(BaseModel):
    """The type being asked about — from the form, saved or not.

    Sent rather than looked up by key on purpose: the question is most useful
    while a rep is still typing the description, before anything exists to look
    up.
    """

    key: str = Field(default="", max_length=60)
    label: str = Field(min_length=1, max_length=80)
    scope: Scope
    description: str | None = Field(default=None, max_length=2000)


class TypeSourceSuggestion(BaseModel):
    """Where one signal type is usually found, and what to look for."""

    model_config = ConfigDict(extra="forbid")

    #: Existing registry keys. Anything not in the registry is dropped by the
    #: route rather than trusted — a claimed source nothing runs reports as a
    #: permanent coverage gap.
    sources: list[str] = Field(default_factory=list)
    #: A draft for "what to look for", used only where the ordinary sweeps
    #: would miss this. Empty is the common and correct answer.
    search_instruction: str = Field(default="", max_length=2000)
    #: Why this type needs words of its own, or why it does not.
    why: str = Field(default="", max_length=600)
    new_sources: list[NewSourceProposal] = Field(default_factory=list)


class IcpSourceProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=60)
    #: Which of the ICP's signal types expect this source. Empty means the
    #: model is proposing it as an extra, which is a claim a rep should read.
    for_types: list[str] = Field(default_factory=list)
    why: str = Field(default="", max_length=400)


class IcpSourceSuggestions(BaseModel):
    """The sources an ICP should read, assembled and explained."""

    model_config = ConfigDict(extra="forbid")

    sources: list[IcpSourceProposal] = Field(default_factory=list)
    new_sources: list[NewSourceProposal] = Field(default_factory=list)
    #: Anything the rep should know before accepting — a type nothing covers,
    #: a source that will be expensive. One or two lines, not an essay.
    notes: str = Field(default="", max_length=800)


class SearchGroupProposal(BaseModel):
    """One suggested grouping: types that read the same sources."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=80)
    type_keys: list[str] = Field(min_length=2)
    #: Why these belong together, in a sentence a rep can disagree with.
    why: str = Field(min_length=1)


class SearchGroupSuggestions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    groups: list[SearchGroupProposal] = Field(default_factory=list)
    #: Types that read something nobody else reads. Named, so the answer is
    #: visibly complete rather than quietly partial.
    ungrouped: list[str] = Field(default_factory=list)


class SignalTypePatch(BaseModel):
    """Only the tuning knobs.

    `key` is absent on purpose: it is written into the extraction output schema
    and referenced by every historical signal, so renaming it would orphan them.
    `scope` is absent because moving a type between scopes would leave existing
    contact signals attached to a company type.

    Changing a weight affects **future** scoring only. Past qualifications keep
    the scores they were computed with, which is what makes them explainable.
    """

    weight: Annotated[float, Field(ge=0, le=5)] | None = None
    default_ttl_days: Annotated[int, Field(ge=1, le=3650)] | None = None
    #: How long the fact stays worth reading. `0` clears it back to the default
    #: of three times the TTL — null cannot mean "clear" in a patch, where it
    #: already means "leave alone".
    durability_days: Annotated[int, Field(ge=0, le=7300)] | None = None
    label: str | None = Field(default=None, min_length=1)
    description: str | None = None
    produced_by: list[str] | None = None
    #: What to look for. A prompt fragment: editing it changes what every later
    #: coverage row means, which is why the coverage row records the run and
    #: the report says which types a search covered.
    search_instruction: str | None = Field(default=None, max_length=2000)
    #: Types sharing a label are searched once, together. `""` clears it.
    search_group: str | None = Field(default=None, max_length=80)
    #: Switching a type to `theme` affects readings from now on; older live
    #: copies are consolidated by `scripts/supersede_duplicate_signals.py`.
    kind: Literal["event", "theme"] | None = None


class ResearchSourceIn(BaseModel):
    """A place a rep wants research to read.

    Only `search` sources can be created here. A `fetch` reads a feed and a
    `provider` spends credits: both need code behind them, and a row claiming
    one with nothing behind it reports a coverage gap forever.
    """

    key: str = Field(min_length=2, max_length=60, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=80)
    #: The brief. This is what the search is told to read for, so it is written
    #: as an instruction about the place, not as a definition of a conclusion.
    description: str = Field(min_length=1, max_length=600)
    scopes: list[Scope] = Field(min_length=1)
    support_only: bool = False
    reuse_days: Annotated[int, Field(ge=1, le=3650)] | None = None


class SourceTrialIn(BaseModel):
    """A candidate source and the accounts to try it against.

    The same fields as `ResearchSourceIn` plus `kind` and the sample, because
    the point is to trial exactly what would be stored. `key` is wanted even
    though nothing is written under it: it appears in the prompt and in the
    log line, and a trial of an unnamed thing is hard to talk about afterwards.
    """

    key: str = Field(min_length=2, max_length=60, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=600)
    scopes: list[Scope] = Field(min_length=1)
    #: `search` or `fetch`. Anything else is refused with 422 rather than
    #: trialled, because there is no client to run it and a green result would
    #: mean nothing.
    kind: Literal["search", "fetch"] = "search"
    #: Which accounts to sample. At least one, and the service caps the list.
    account_ids: list[uuid.UUID] = Field(min_length=1)
    #: A second wording to run against **the same accounts in the same call**.
    #: That is what makes it an A/B: the prompt, model, account and day are held
    #: still and one field moves, so a difference is attributable to the words.
    description_b: str | None = Field(default=None, min_length=1, max_length=600)


class AccountTrialOut(ORMModel):
    account_id: uuid.UUID
    account_name: str
    #: What came back, in full. Shown rather than counted: the decision is
    #: whether these passages are worth paying for, which a number cannot say.
    found: list[dict]
    not_found: list[str]
    duration_ms: int
    input_tokens: int
    output_tokens: int
    error: str | None = None
    #: "A" or "B". Always "A" when no second wording was given.
    variant: str = "A"
    #: Account fields that were empty, in plain words. An account with no stored
    #: website finds nothing for every source, and without this the empty result
    #: reads as a verdict on the brief instead of on the row.
    missing: list[str] = []


class SourceTrialOut(ORMModel):
    """What a trial returned, and nothing stored."""

    candidate: dict
    route: str
    #: The search logic as sent: the editable `company_research` template, and
    #: the rendered payload. Shown so a brief can be tuned against what runs —
    #: and so it can be pasted into a model elsewhere and argued with.
    prompt: str = ""
    payload: dict = {}
    #: Echoed when an A/B ran, so the screen can label the two columns.
    variant_b: str | None = None
    accounts: int
    found: int
    #: Accounts where it ran cleanly and found nothing — the number that decides
    #: whether a source is worth having.
    dry: int
    failed: int
    input_tokens: int
    output_tokens: int
    verdict: str
    trials: list[AccountTrialOut]


class ResearchSourcePatch(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, min_length=1, max_length=600)
    scopes: list[Scope] | None = Field(default=None, min_length=1)
    support_only: bool | None = None
    reuse_days: Annotated[int, Field(ge=1, le=3650)] | None = None
    status: Literal["active", "paused", "deprecated"] | None = None


class ResearchSourceOut(ORMModel):
    id: uuid.UUID
    key: str
    label: str
    description: str
    kind: str
    scopes: list[str]
    support_only: bool
    reuse_days: int | None
    builtin: bool
    status: str
    #: Why it is not active. Shown beside the status, because that is where
    #: someone stands when they decide whether to turn it back on.
    status_reason: str | None = None
    #: How many active signal types name this source. Zero is not a fault —
    #: an ICP can read a source no type asked for — but it is worth seeing.
    claimed_by: int = 0
    #: What it has actually produced lately: reads, and evidence rows from them.
    attempts: int = 0
    evidence: int = 0
    #: Tried repeatedly and never produced anything. A prompt to look, not a
    #: verdict: a registry only ever grows, and a dead source costs a read per
    #: account on every run forever.
    dead_weight: bool = False


class QueryFamilyOut(BaseModel):
    """The families a signal type may claim, for populating the picker."""

    key: str
    label: str
    description: str
    scopes: list[str]
    support_only: bool
    #: `search`, `provider` or `manual` — see `query_families.Runner`. The
    #: screen reads it to explain why a non-search family has no coverage of
    #: its own rather than showing it as a permanent gap.
    runner: str = "search"


class SignalTypeOut(ORMModel):
    id: uuid.UUID
    key: str
    label: str
    description: str | None
    scope: str
    default_ttl_days: int
    #: Null when it is the default. `durability_effective_days` carries the
    #: number that actually applies, so the screen never has to know the
    #: multiple — and never drifts from it if it changes.
    durability_days: int | None = None
    durability_effective_days: int = 0
    weight: float
    produced_by: list[str]
    #: These two were missing, so the screen showed every type as having no
    #: extra search and an edit could not see what it was editing.
    search_instruction: str | None = None
    search_group: str | None = None
    kind: str = "event"
    status: str
    paused_at: datetime | None
    deprecated_at: datetime | None
    #: How many signals cite this type. Zero means deleting it destroys no
    #: history, which is the only condition under which deletion is allowed.
    signal_count: int = 0
