"""Every external service this system can talk to, and what we know about it.

Three kinds of provider, and the distinction is not cosmetic — each is a
**separate mandatory dependency** that the application cannot work without:

* `enrichment` — turns a name into a reachable contact. Without one, research
  produces accounts nobody can be written to.
* `llm` — turns evidence into signals, strategy and copy. Without one, nothing
  downstream of a raw page exists.
* `outreach` — actually sends. Without it the whole pipeline stops at approval.

`crm` is deliberately *not* mandatory: a missing CRM makes the pipeline
cautious (it halts research rather than prospecting blind), which is a
degraded state rather than a broken one.

Three facts are tracked per provider and none implies another:

* **A credential can be stored.** Any provider, including one somebody adds.
* **`verifiable`** — `probes.py` can ask the vendor whether a key works. This
  is what the Test button and the setup gate depend on.
* **`runnable`** — an adapter exists to do the actual work: call a model, find
  a contact, enrol a sequence.

The first version of this file collapsed the last two into one flag, and it
read differently by kind — which meant "we can check your Gemini key" and "we
can run drafting on Gemini" were the same boolean and could not both be told
truthfully. They are different questions with different answers, and the
Gemini case is exactly where that broke: a perfectly checkable key on a vendor
no stage can call.

A picker that offers something we cannot call produces a configuration that
validates, saves, shows as active, and then fails at the first real call —
mid-run, after money has been spent. So both flags are returned by the API and
shown on every screen that can act on them.

The catalogue is **suggestions, not a closed list**. Which vendors a business
buys from changes on a purchase order, not on a deploy, so a provider can be
added from the Integrations screen and this file simply has nothing to say
about it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Kind = Literal["llm", "enrichment", "outreach", "crm"]

#: The kinds that must be configured and verified before the rest of the
#: application is usable, in the order the setup screen walks them.
#:
#: Setup order, not pipeline order — the pipeline enriches before it drafts.
#: A model key comes first because it is the one dependency that is both fully
#: verifiable and fully runnable today, so it is where somebody finds out
#: whether this installation works at all. Enrichment and delivery then follow
#: the send path.
MANDATORY_KINDS: tuple[Kind, ...] = ("llm", "enrichment", "outreach")


@dataclass(frozen=True)
class ModelOption:
    id: str
    label: str
    #: Whether the model takes a structured-output contract. Every non-research
    #: stage needs one, so a model without it is research-only.
    structured_output: bool = True
    #: Whether it takes an effort level. `llm_config.effort` is meaningless for
    #: a model that does not.
    effort: bool = True
    #: Whether the provider caches a repeated prompt prefix. The cost model for
    #: a book of 200 accounts assumes this.
    prompt_caching: bool = True
    #: Rough tier, so a stage can be pointed at "the cheap one" without anyone
    #: memorising model ids.
    tier: Literal["frontier", "balanced", "economy"] = "balanced"
    notes: str | None = None


@dataclass(frozen=True)
class ProbeSpec:
    """How to ask a provider whether a key works, without doing anything else.

    Declared as data rather than written per provider so the endpoint we use is
    **visible**. When a vendor moves its auth route, the symptom is a 404 — and
    a probe that reported that as "your key is invalid" would send someone to
    re-issue a perfectly good key. `probes.py` reports a 404 as *our* problem.

    `live_verified` means this exact request has been run against the live
    vendor and its behaviour observed — not that it was copied from a doc.
    Every spec here that carries it was checked with a deliberately invalid key
    and, where possible, a real one. Three were wrong on the first attempt,
    which is the reason the field exists:

    * Apollo's health route answers **200 for any key**, and only the body says
      whether it authenticated. A status-only check marked garbage as valid and
      would have satisfied the setup gate with it.
    * ContactOut's search route is POST-only (405). `/v1/stats` is the GET that
      actually authenticates.
    * Google answers **400**, not 401, for a malformed key.

    None of that is guessable from a status code alone, which is why a spec
    that has not been run is marked `live_verified=False` and why the
    inconclusive branches in `probes.py` exist.
    """

    method: str
    url: str
    #: How the key is presented. `header` names the header; `{key}` in
    #: `value_template` is replaced with the credential.
    header: str = "authorization"
    value_template: str = "Bearer {key}"
    #: Sent on every probe. Some APIs 400 without an Accept.
    extra_headers: dict[str, str] = field(default_factory=dict)
    #: Whether this exact request has been run against the live vendor and its
    #: behaviour observed. See the class docstring — flip it when you have.
    live_verified: bool = False
    #: Statuses this vendor uses to mean "bad key". Only needed where it is not
    #: 401/403 — Google answers 400, which otherwise reads as our request being
    #: malformed and reports the key as untested.
    rejects_with: tuple[int, ...] = ()
    #: A JSON field in a 200 body that must be truthy for the key to count as
    #: accepted. Apollo returns 200 with `is_logged_in: false` for any key, so
    #: without this the probe is a coin that always lands heads.
    success_flag: str | None = None


@dataclass(frozen=True)
class ProviderCatalogue:
    key: str
    label: str
    kind: Kind
    #: Where this vendor issues API keys.
    console_url: str = ""
    #: True when an adapter exists to do this provider's actual work: run a
    #: model, find a contact, enrol a sequence. Not the same as being able to
    #: check its key — see `verifiable`.
    runnable: bool = False
    credential_types: tuple[str, ...] = ("api_key",)
    models: tuple[ModelOption, ...] = field(default_factory=tuple)
    probe: ProbeSpec | None = None
    #: One line on what this provider is for, shown on the setup screen.
    purpose: str = ""

    @property
    def verifiable(self) -> bool:
        """Whether a stored key can be checked against the vendor for real.

        Derived rather than stored so it cannot drift from the probe registry:
        adding a `ProbeSpec` makes a provider checkable in the same edit, and
        removing one makes it honestly uncheckable again.
        """
        # Anthropic is probed through the SDK rather than a declared HTTP spec,
        # so that the check exercises the same client the stages use.
        return self.key == "anthropic" or self.probe is not None


CATALOGUE: tuple[ProviderCatalogue, ...] = (
    # ---------------------------------------------------------------- llm
    ProviderCatalogue(
        key="anthropic",
        label="Anthropic",
        kind="llm",
        console_url="https://console.anthropic.com/settings/keys",
        runnable=True,
        purpose="Reads evidence, writes signals, strategy and outreach copy.",
        models=(
            ModelOption(
                "claude-opus-5",
                "Claude Opus 5",
                tier="frontier",
                notes="The default. Every stage's effort level is tuned against it.",
            ),
            ModelOption(
                "claude-sonnet-5",
                "Claude Sonnet 5",
                tier="balanced",
                notes="Cheaper. Reasonable for extraction and revalidation.",
            ),
            ModelOption(
                "claude-haiku-4-5-20251001",
                "Claude Haiku 4.5",
                effort=False,
                tier="economy",
                notes="Cheapest. Used for the credential probe; too small for drafting.",
            ),
        ),
    ),
    ProviderCatalogue(
        key="openai",
        label="OpenAI",
        kind="llm",
        console_url="https://platform.openai.com/api-keys",
        # The key can be checked; no stage can run on it yet. Two different
        # facts, and both are told.
        runnable=False,
        purpose="Alternative model vendor. Key can be verified; no adapter yet.",
        probe=ProbeSpec(
            method="GET",
            url="https://api.openai.com/v1/models",
            header="authorization",
            value_template="Bearer {key}",
            extra_headers={"accept": "application/json"},
            live_verified=True,
        ),
        models=(
            ModelOption("gpt-5.2", "GPT-5.2", tier="frontier"),
            ModelOption("gpt-5.2-mini", "GPT-5.2 mini", tier="economy"),
        ),
    ),
    ProviderCatalogue(
        key="gemini",
        label="Google Gemini",
        kind="llm",
        console_url="https://aistudio.google.com/apikey",
        runnable=True,
        purpose="Reads evidence and writes signals, strategy and copy.",
        probe=ProbeSpec(
            method="GET",
            url="https://generativelanguage.googleapis.com/v1beta/models",
            # Google takes the key in its own header rather than a bearer
            # token. Sending it as `Authorization: Bearer` returns 401 for a
            # perfectly good key, which is the worst possible wrong answer.
            header="x-goog-api-key",
            value_template="{key}",
            extra_headers={"accept": "application/json"},
            # Google answers 400 for a malformed key, not 401. Without this the
            # probe reports "the key was not tested" for a key that was in fact
            # rejected. Verified against both a real key (200) and junk (400).
            rejects_with=(400,),
            live_verified=True,
        ),
        models=(
            # Ids confirmed against `/v1beta/models` with a live key. The ones
            # written from memory first — `gemini-3-pro`, `gemini-3-flash` —
            # do not exist, and a stage set to one fails at its first call
            # with a 404 that names nothing useful.
            ModelOption(
                "gemini-3.1-pro-preview",
                "Gemini 3.1 Pro",
                tier="frontier",
                notes="The strongest Gemini this key can reach. Preview naming.",
            ),
            ModelOption(
                "gemini-3.8-flash",
                "Gemini 3.8 Flash",
                tier="balanced",
                notes="Fast and cheap. Verified end to end on structured output.",
            ),
            ModelOption(
                "gemini-3.5-flash-lite",
                "Gemini 3.5 Flash Lite",
                tier="economy",
                notes="Cheapest. Suitable for revalidation, not for drafting.",
            ),
        ),
    ),
    # --------------------------------------------------------- enrichment
    ProviderCatalogue(
        key="contactout",
        label="ContactOut",
        kind="enrichment",
        console_url="https://contactout.com/dashboard/api",
        # Routes and auth confirmed by live probe; the response mapping is
        # not, and `enrichment_clients.py` reports an unrecognised body rather
        # than reading it as "nobody found". See that module's docstring.
        runnable=True,
        purpose="Finds and verifies a contact's email and phone.",
        probe=ProbeSpec(
            method="GET",
            # `/v1/people/search` is POST-only and answers 405 to a probe.
            # `/v1/stats` is the GET that actually authenticates — verified
            # returning 401 for an invalid key.
            url="https://api.contactout.com/v1/stats",
            header="authorization",
            value_template="{key}",
            extra_headers={"accept": "application/json"},
            live_verified=True,
        ),
    ),
    ProviderCatalogue(
        key="apollo",
        label="Apollo.io",
        kind="enrichment",
        console_url="https://developer.apollo.io/keys/",
        # Auth route, request shape and response fields all confirmed
        # against a live key; the client is
        # `enrichment_clients.ApolloProvider`.
        runnable=True,
        purpose="Finds contacts and company data. Common waterfall fallback.",
        probe=ProbeSpec(
            method="GET",
            url="https://api.apollo.io/api/v1/auth/health",
            header="x-api-key",
            value_template="{key}",
            extra_headers={"accept": "application/json"},
            # Answers `{"healthy":true,"is_logged_in":false}` with HTTP 200 for
            # a junk key. Checking only the status marked garbage as valid and
            # satisfied the setup gate with it — the exact failure the gate
            # exists to prevent. Confirmed from both sides since: a real key
            # returns `is_logged_in: true` on the same route.
            success_flag="is_logged_in",
            live_verified=True,
        ),
    ),
    # ----------------------------------------------------------- outreach
    ProviderCatalogue(
        key="lgm",
        label="La Growth Machine",
        kind="outreach",
        console_url="https://app.lagrowthmachine.com/settings/api",
        runnable=True,
        credential_types=("api_key", "base_url"),
        purpose="Enrols approved sequences and actually sends them.",
        # `/flow/members` is the check LGM's own documentation suggests: it
        # needs authentication, reads nothing, and changes nothing. The key may
        # be presented as a Bearer token, an `x-api-key` header or a query
        # parameter; the header is used here so it never reaches a URL, a proxy
        # log or a redirect.
        probe=ProbeSpec(
            method="GET",
            url="https://apiv2.lagrowthmachine.com/flow/members",
            extra_headers={"accept": "application/json"},
            # Run against the live account on 2026-09-20: a real key returned
            # 200 with the workspace's members, and the same request without
            # one is refused. The documentation was right, but that is not why
            # this is true now.
            live_verified=True,
        ),
    ),
    # ---------------------------------------------------------------- crm
    ProviderCatalogue(
        key="crm",
        label="CGVAK CRM",
        kind="crm",
        runnable=False,
        credential_types=("api_key", "base_url"),
        purpose=(
            "Checked before research so we never prospect into an existing "
            "customer. Optional — without it, research halts rather than "
            "guessing."
        ),
    ),
)

BY_KEY: dict[str, ProviderCatalogue] = {p.key: p for p in CATALOGUE}


def of_kind(kind: Kind) -> list[ProviderCatalogue]:
    return [p for p in CATALOGUE if p.kind == kind]


def kind_of(provider: str) -> Kind | None:
    cat = BY_KEY.get(provider)
    return cat.kind if cat else None


def model_for(provider: str, model_id: str) -> ModelOption | None:
    cat = BY_KEY.get(provider)
    if cat is None:
        return None
    return next((m for m in cat.models if m.id == model_id), None)


def is_runnable(provider: str) -> bool:
    """Can we do this provider's actual work."""
    cat = BY_KEY.get(provider)
    return bool(cat and cat.runnable)


def is_verifiable(provider: str) -> bool:
    """Can we check this provider's key against the vendor."""
    cat = BY_KEY.get(provider)
    return bool(cat and cat.verifiable)


def models_by_tier(provider: str) -> dict[str, ModelOption]:
    """One model per tier, so a stage can be set to "the cheap one".

    Nobody should have to memorise model ids to make a cost decision, and the
    ids are the part that changes. Where a provider ships two models in a tier
    the first wins — the catalogue order is the recommendation.
    """
    out: dict[str, ModelOption] = {}
    for model in BY_KEY.get(provider, ProviderCatalogue("", "", "llm")).models:
        out.setdefault(model.tier, model)
    return out


def validate(provider: str, model_id: str) -> None:
    """Reject a pair that cannot mean anything. An unknown provider is not one.

    A provider we have never heard of is one somebody added, and we have no
    list to check its model ids against — so there is nothing to reject. What
    *is* rejected is a model id for a provider we know that does not have it:
    that is a typo, and it produces a row which would fail at the first call
    for a reason nobody would guess.
    """
    cat = BY_KEY.get(provider)
    if cat is None:
        return
    if model_for(provider, model_id) is None:
        raise ValueError(
            f"{cat.label} does not offer {model_id!r}; "
            f"available: {[m.id for m in cat.models]}"
        )
