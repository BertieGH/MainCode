"""The single place this system talks to Claude.

Every non-research stage is one structured call: a Pydantic contract in, a
validated object out. Only the research fan-out has the open-ended "keep
searching until you have enough" shape that warrants a tool loop.

Three things are enforced here rather than left to each call site, because each
one fails silently when it is forgotten:

* **Effort and model come from `llm_config`**, per scenario. Tuning is a config
  change, not a deploy, and `xhigh` on strategy is a deliberate cost decision
  that should be visible in a table rather than buried in a call.
* **The cached prefix is assembled by `prompt.py`** and nothing else. Cache is a
  prefix match, so one `datetime.now()` in a system block costs the cache on
  every call and reports nothing.
* **`cache_read_input_tokens` is logged on every call.** A silent cache miss is
  the most expensive bug in the system and it is invisible without this.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.config import LlmConfig
from app.services.prompt import PromptAssembly

log = logging.getLogger(__name__)

#: Opus 5 declines some requests outright. Server-side fallback re-runs the same
#: request on another model inside the same call, so a safety refusal on a
#: research prompt degrades instead of crashing a run.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

#: Non-streaming default. Truncation costs a full retry, so this is deliberately
#: not lowballed — `docs/06 §2`.
DEFAULT_MAX_TOKENS = 16000

#: One step down, for a call that thought itself out of room.
QUIETER_THINKING = {"max": "high", "xhigh": "high", "high": "medium", "medium": "low"}


class LlmUnavailableError(RuntimeError):
    """No credentials, or the provider could not be reached.

    `retry_after` and `quota` are set when the provider said why it refused.
    A caller that can pause — the list loop — needs to tell a per-minute
    ceiling from a per-day one, and `is_rate_limit` alone does not say.
    """

    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        quota: str | None = None,
        rate_limited: bool = False,
    ):
        self.retry_after = retry_after
        self.quota = quota
        self.rate_limited = rate_limited
        super().__init__(message)

    @property
    def exhausted_for_the_day(self) -> bool:
        """A quota that resets tomorrow, not in a minute.

        Google names its quotas, and the name is the only reliable signal:
        `GenerateRequestsPerDayPerProjectPerModel` cannot be waited out inside
        a run, while a per-minute one can. Unknown counts as not daily — a
        caller that pauses and retries loses a minute, where one that stops
        early abandons accounts it could have researched.
        """
        return bool(self.quota) and "perday" in self.quota.lower().replace("_", "")


def _unavailable(exc: Exception, *, suffix: str = "") -> LlmUnavailableError:
    """A provider error, keeping whatever it said about why it refused.

    One place rather than at each raise site, so a new call path cannot
    silently drop the retry hint the way every path did until now.
    """
    return LlmUnavailableError(
        f"{exc}{suffix}",
        retry_after=getattr(exc, "retry_after", None),
        quota=getattr(exc, "quota", None),
        rate_limited=bool(getattr(exc, "is_rate_limit", False)),
    )


class NoAdapterError(RuntimeError):
    """The stage is configured for a provider this code cannot call.

    Raised before any request, and named for the provider, because the
    alternative is an AttributeError or a 404 from a URL that means nothing to
    whoever is reading the log. A provider can be added and a credential stored
    long before an adapter exists — that is deliberate — so this is a normal
    state to reach, not a corruption.
    """

    def __init__(self, provider: str, scenario: str):
        self.provider = provider
        self.scenario = scenario
        super().__init__(
            f"{scenario!r} is configured to run on {provider!r}, which has no adapter. "
            f"Runnable providers: {', '.join(_runnable_providers())}."
        )


def _runnable_providers() -> list[str]:
    from app.services.provider_catalogue import CATALOGUE

    return sorted(p.key for p in CATALOGUE if p.runnable)


class LlmRefusedError(RuntimeError):
    """The model and every fallback declined. Carries the category."""

    def __init__(self, category: str | None, explanation: str | None):
        self.category = category
        self.explanation = explanation
        super().__init__(f"refused ({category}): {explanation}")


@dataclass
class StageConfig:
    """What `llm_config` says this stage should run as."""

    scenario: str
    provider: str = "anthropic"
    model: str = "claude-opus-5"
    effort: str = "high"
    max_tokens: int = DEFAULT_MAX_TOKENS
    thinking_mode: str = "adaptive"


@dataclass
class CallResult[R]:
    parsed: R
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    model: str = ""

    @property
    def cache_hit(self) -> bool:
        return self.cache_read_tokens > 0


@dataclass
class Usage:
    """Running totals across a run, for the `run` row."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    calls: list[str] = field(default_factory=list)

    def add(self, scenario: str, result: CallResult[Any]) -> None:
        self.input_tokens += result.input_tokens
        self.output_tokens += result.output_tokens
        self.cache_read_tokens += result.cache_read_tokens
        self.calls.append(scenario)


async def stage_config(session: AsyncSession, scenario: str) -> StageConfig:
    """Read a stage's model settings, falling back to sane defaults.

    A missing row is not an error: it means nobody has tuned this stage yet, and
    refusing to run would make configuration a prerequisite for a first call.
    """
    row = (
        await session.execute(
            select(LlmConfig).where(
                LlmConfig.scenario == scenario, LlmConfig.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()
    if row is None:
        log.info("llm.no_config scenario=%s using defaults", scenario)
        return StageConfig(scenario=scenario)
    return StageConfig(
        scenario=scenario,
        provider=row.provider,
        model=row.model,
        effort=row.effort,
        max_tokens=row.max_tokens,
        thinking_mode=row.thinking_mode,
    )


async def assert_may_call(session: AsyncSession, scenario: str) -> None:
    """Refuse a model call while this installation is a sandbox.

    Checked here rather than relying on there being no credential: a demo
    installation that still holds a working key would otherwise spend it, and
    "we happened not to be configured" is not a safety property.
    """
    from app.services import demo

    demo.assert_no_egress(await demo.current_mode(session), f"a model call for {scenario!r}")


async def stored_api_key(
    session: AsyncSession, provider: str = "anthropic"
) -> str | None:
    """The key a rep entered on the Integrations screen, if there is one.

    That screen is where the product tells people to put their key, so the
    stages have to read from it — otherwise a key entered there is stored,
    shown as valid, and never used, and the only symptom is every stage
    failing to authenticate.

    **`provider` is not optional in practice.** This was hardcoded to
    `anthropic`, so a stage configured to use Gemini was handed the Anthropic
    key and Google answered "API key not valid" — a message that reads as a bad
    credential when the credential was fine and the *wrong one* was sent. Every
    stage on a non-Anthropic provider failed that way, and the credential
    screen went on showing both keys as valid, because both are.

    The value is unwrapped from `SecretValue` here and returned as a plain
    string, which is the one thing `SecretValue` exists to make deliberate.
    It goes straight into the SDK constructor and is never logged, formatted,
    or returned by any endpoint — `docs/01` invariant 9.
    """
    from app.models.config import IntegrationCredential
    from app.services import crypto

    row = (
        await session.execute(
            select(IntegrationCredential).where(
                IntegrationCredential.provider == provider,
                IntegrationCredential.credential_type == "api_key",
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    try:
        return crypto.decrypt(row.value_encrypted).reveal()
    except crypto.CredentialError:
        # SECRET_KEY changed since it was stored. Falling through to the
        # environment is right: it may still be set, and a hard failure here
        # would make an undecryptable row block a working configuration.
        log.warning("llm.stored_key_undecryptable — falling back to the environment")
        return None


def _client(api_key: str | None = None):
    """Build a client, or say plainly that there are no credentials.

    A bare `Anthropic()` also resolves an `ant auth login` profile, so an unset
    `ANTHROPIC_API_KEY` does not by itself mean unauthenticated — the SDK is
    left to decide, and only a construction failure is treated as missing.
    """
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise LlmUnavailableError("the anthropic SDK is not installed") from exc

    settings = get_settings()
    # Stored credential first, then the environment. A rep who pastes a key
    # into the app expects that key to be the one used.
    key = api_key or settings.anthropic_api_key
    try:
        if key:
            return anthropic.AsyncAnthropic(api_key=key)
        return anthropic.AsyncAnthropic()
    except Exception as exc:
        raise LlmUnavailableError(
            "no Anthropic credentials: set ANTHROPIC_API_KEY or run `ant auth login`"
        ) from exc


async def _call_gemini[R: BaseModel](
    *,
    config: StageConfig,
    prefix: PromptAssembly,
    user_content: str,
    output_model: type[R],
    api_key: str | None,
) -> CallResult[R]:
    """Route a stage to Gemini and normalise the result.

    A separate function rather than a branch inside `call_structured` because
    the two paths share almost nothing: different transport, different schema
    dialect, and validation on opposite sides of the wire. What they do share
    is the return type, and that is the point.
    """
    from app.services import gemini

    # Timed from the top so the number covers what the caller waited for,
    # the quieter retry below included.
    started = time.perf_counter()

    # Web stages arrive with `prefix.tools`. `gemini.call` turns them into
    # Google Search and refuses an answer it cannot show was searched — which
    # is what a web stage here used to return, confidently, from memory.
    if not api_key:
        raise LlmUnavailableError(
            "no Gemini credential — add one on the Integrations screen"
        )

    try:
        parsed, usage = await gemini.call(
            model=config.model,
            api_key=api_key,
            prefix=prefix,
            user_content=user_content,
            output_model=output_model,
            effort=config.effort,
            max_tokens=config.max_tokens,
            # Named so the client can hold this stage to its own clock — see
            # `gemini.STAGE_TIMEOUT_SECONDS`.
            scenario=config.scenario,
        )
    except gemini.GeminiRefusedError as exc:
        # Mapped onto the same error the Anthropic path raises, so a caller
        # handling a refusal does not need to know which vendor produced it.
        raise LlmRefusedError(exc.reason, str(exc)) from exc
    except gemini.GeminiError as exc:
        quieter = QUIETER_THINKING.get(config.effort)
        # A budget blowout and a timeout are the same failure wearing two
        # faces: thinking is charged against the output budget *and* runs on
        # the clock, so a derailed call ends at whichever ceiling it reaches
        # first. Both deserve the same quieter second attempt.
        derailed = "maxOutputTokens" in str(exc) or "Timeout" in str(exc)
        if not derailed or not quieter:
            raise _unavailable(exc) from exc

        # Thinking is charged against the output budget, so a call that hits
        # the ceiling spent it deciding rather than answering. Retrying
        # identically — which is what happened until now — asks the same
        # question of the same reasoner and mostly gets the same silence.
        # One step quieter changes the thing that went wrong.
        log.warning(
            "llm.derailed scenario=%s effort=%s — retrying at %s (%s)",
            config.scenario, config.effort, quieter, exc,
        )
        try:
            parsed, usage = await gemini.call(
                model=config.model,
                api_key=api_key,
                prefix=prefix,
                user_content=user_content,
                output_model=output_model,
                effort=quieter,
                max_tokens=config.max_tokens,
                scenario=config.scenario,
            )
        except gemini.GeminiRefusedError as second:
            raise LlmRefusedError(second.reason, str(second)) from second
        except gemini.GeminiError as second:
            raise _unavailable(
                second,
                suffix=f" (retried at {quieter} thinking after the first ran out of room)",
            ) from second

    _log_usage(config, usage, time.perf_counter() - started)
    return CallResult(parsed=parsed, model=config.model, **usage)


def _log_usage(
    config: StageConfig, usage: dict[str, int], seconds: float | None = None
) -> None:
    """One line, the same on every provider.

    A silent cache miss is the most expensive bug in the system and it is
    invisible without this — see the module docstring.

    `seconds` is here because the same was true of time. A research run takes
    two and a half minutes an account and nothing recorded where any of it
    went, so "which call is slow" could be argued but not answered. Measuring
    it costs one `perf_counter` per call.
    """
    log.info(
        "llm.call scenario=%s provider=%s model=%s effort=%s "
        "in=%d out=%d cache_read=%d cache_write=%d%s",
        config.scenario, config.provider, config.model, config.effort,
        usage["input_tokens"], usage["output_tokens"],
        usage["cache_read_tokens"], usage["cache_write_tokens"],
        f" seconds={seconds:.1f}" if seconds is not None else "",
    )
    if usage["cache_read_tokens"] == 0 and usage["cache_write_tokens"] == 0:
        log.warning(
            "llm.no_cache scenario=%s — the prefix neither read nor wrote cache; "
            "it may be below the minimum cacheable length, or an invalidator is present",
            config.scenario,
        )


def _usage_of(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    return {
        "input_tokens": getattr(usage, "input_tokens", 0) or 0,
        "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        "cache_read_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
        "cache_write_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
    }


async def call_structured[R: BaseModel](
    *,
    config: StageConfig,
    prefix: PromptAssembly,
    user_content: str,
    output_model: type[R],
    client: Any | None = None,
    api_key: str | None = None,
) -> CallResult[R]:
    """One structured call. Contract in, validated object out.

    `messages.parse` rather than hand-parsing a text block: the schema is
    enforced by the API and the SDK returns a validated instance, so a malformed
    response is a raised error at the boundary rather than a `KeyError` three
    layers in.

    Dispatches on `config.provider`. Each provider gets whatever shape it
    actually needs — Anthropic parses server-side, Gemini needs its schema
    translated and its output validated here — and every one of them returns
    the same `CallResult`, so nothing above this function knows which vendor
    ran.

    Timed from here rather than inside each branch, so the number covers what
    the caller actually waited for, retries included.
    """
    # Checked before the client is built, so a misconfigured provider is a
    # named error rather than a failed request against the wrong vendor.
    from app.services.provider_catalogue import is_runnable

    if client is None and not is_runnable(config.provider):
        raise NoAdapterError(config.provider, config.scenario)

    if client is None and config.provider == "gemini":
        return await _call_gemini(
            config=config,
            prefix=prefix,
            user_content=user_content,
            output_model=output_model,
            api_key=api_key,
        )

    client = client or _client(api_key)
    started = time.perf_counter()

    request: dict[str, Any] = {
        "model": config.model,
        "max_tokens": config.max_tokens,
        # Order matters and is not incidental: tools → system → messages is the
        # cache prefix, and `prompt.py` owns the first two.
        "system": prefix.system(),
        "messages": [{"role": "user", "content": user_content}],
        "output_format": output_model,
        "output_config": {"effort": config.effort},
    }
    if config.thinking_mode:
        request["thinking"] = {"type": config.thinking_mode}
    if prefix.tools:
        request["tools"] = prefix.tools

    try:
        response = await client.beta.messages.parse(
            **request, betas=[FALLBACK_BETA], fallbacks="default"
        )
    except Exception as exc:
        # A refusal arrives as a 200 with stop_reason, not an exception, so
        # anything raised here is transport, auth or a bad request.
        raise LlmUnavailableError(f"{type(exc).__name__}: {exc}") from exc

    if getattr(response, "stop_reason", None) == "refusal":
        details = getattr(response, "stop_details", None)
        raise LlmRefusedError(
            getattr(details, "category", None), getattr(details, "explanation", None)
        )

    usage = _usage_of(response)
    # The one line that makes a silent cache miss visible. `docs/06 §5`.
    _log_usage(config, usage, time.perf_counter() - started)

    return CallResult(
        parsed=response.parsed_output,
        model=getattr(response, "model", config.model),
        **usage,
    )


@dataclass
class Probe:
    """The result of asking a provider whether a credential actually works."""

    ok: bool
    detail: str


async def probe_anthropic(api_key: str | None = None) -> Probe:
    """The smallest real call that proves a key works.

    Decrypting a stored value proves only that `SECRET_KEY` has not changed.
    It reports `valid` for a key that was mistyped, revoked, or belongs to an
    exhausted workspace — which is the state a rep is actually in when
    outreach silently stops producing drafts.

    One token of output, no thinking, no cache. The error is reduced to its
    class before it is returned: a provider rejection body can quote the key
    that was sent, and this string ends up in an API response.
    """
    try:
        import anthropic
    except ImportError:
        return Probe(False, "the anthropic SDK is not installed")

    try:
        client = (
            anthropic.AsyncAnthropic(api_key=api_key)
            if api_key
            else anthropic.AsyncAnthropic()
        )
        await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
    except Exception as exc:  # noqa: BLE001 — a probe reports, it never propagates
        name = type(exc).__name__
        # Logged in full here and reduced to a class below. Without this, a
        # bug in the probe itself is indistinguishable from a bad key: both
        # surface to the caller as "the provider returned <SomeError>".
        log.warning("llm.probe_failed error=%s: %s", name, exc)
        if "Authentication" in name or "PermissionDenied" in name:
            return Probe(False, "the provider rejected this key")
        if "RateLimit" in name:
            return Probe(True, "reachable — rate limited right now")
        # The most common real-world failure, and the least guessable from a
        # class name: the key is fine and the workspace has no money. Matched
        # on a marker rather than echoed, so no provider text is passed
        # through — a rejection body can quote the key that was sent.
        if "credit balance" in str(exc).lower():
            return Probe(
                False,
                "the key is valid but the workspace has no credit balance — "
                "top up in the Anthropic console",
            )
        if "APIConnection" in name or "Timeout" in name:
            return Probe(False, "could not reach the provider")
        # Deliberately the exception class only. See the docstring.
        return Probe(False, f"the provider returned {name}")

    return Probe(True, "reachable — the provider accepted this key")
