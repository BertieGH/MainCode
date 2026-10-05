"""Running a stage on Gemini.

Raw REST rather than the `google-genai` SDK, for two reasons that both bit
during this build:

* **TLS.** This product runs on corporate networks with inspecting proxies. A
  client we construct is a client whose certificate store we control, and
  `truststore` is the difference between working and reporting every provider
  as unreachable. An SDK that builds its own client hides that decision.
* **Verifiability.** Every shape below was checked against the live API — the
  nested `responseSchema`, `thinkingConfig`, the `thoughtSignature` part that
  has to be skipped when reading the text. None of it is written from memory.

**Structured output is enforced twice, deliberately.** `responseSchema` steers
the model; the Pydantic contract validates what comes back. They are not
redundant: Gemini's schema subset cannot express "exactly six dimensions" or
"a dated touch must cite its signal", so the schema gets the shape roughly
right and the contract is what actually holds the line. Anthropic's
`messages.parse` does both in one step, which is why this module is longer than
its counterpart rather than better or worse.

**One repair attempt, and only one.** The gap between those two layers is real
and observed: on the first live run the model returned a dimension scored 20
while declaring it had no evidence — schema-valid, contract-invalid. Rejecting
outright would mean the strictest contracts simply never run here, and the
strict ones are the ones worth having. So a failure is sent back with the
validation errors and retried exactly once. Once, because a model that cannot
satisfy a contract given the specific complaint will not satisfy it on the
fifth attempt either, and an unbounded loop turns one bad call into a bill.

**Web stages search with Google Search, and must be seen to.** A stage whose
prefix carries web tools is sent with `googleSearch`, and its answer passes
through `gemini_grounding.ground` before it is returned: refused if nothing
shows a search happened, and research evidence kept only where its link came
from a result. See that module for what the live API does and does not report.

**Caching is not comparable across the two providers**, and this module does
not pretend otherwise. Anthropic caches an explicit prefix we mark; Gemini does
it implicitly on a repeated prefix, reported as `cachedContentTokenCount`. The
system block order that `prompt.py` guarantees is what gives either of them a
chance, so it is preserved here — but a run costed on Anthropic's cache
behaviour should not be assumed to cost the same here.
"""

from __future__ import annotations

import json
import logging
import ssl
from typing import Any

from pydantic import BaseModel, ValidationError

from app.services import gemini_grounding as grounding
from app.services.gemini_schema import SchemaTooComplexError, translate
from app.services.prompt import PromptAssembly

log = logging.getLogger(__name__)

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

#: Long, because a stage at high effort with a large contract genuinely takes a
#: while and a timeout here costs the whole call.
TIMEOUT_SECONDS = 180.0

#: What a stage is allowed before it is treated as having derailed.
#:
#: Thinking is unbounded inside `maxOutputTokens`, so a call that goes wrong
#: does not fail — it thinks, for as long as the ceiling and the clock allow.
#: Two strategy calls ran the full three minutes and returned nothing, while a
#: sound one on the same stage took nine seconds. A call still thinking long
#: past that is not producing better copy, it is lost, and the sooner it says
#: so the sooner it can be retried at a lower thinking level.
STAGE_TIMEOUT_SECONDS = {
    "strategy_synthesis": 60.0,
    "outreach_drafting": 75.0,
    "pre_send_revalidation": 30.0,
    # The fast sweep is meant to be fast: it only has to answer "is there
    # anything here at all?", and one still going at ninety seconds has found
    # nothing cheap to find. The family passes are deliberately *not* listed —
    # they already get `TIMEOUT_SECONDS`, which is the three minutes the deep
    # pass is supposed to have. Repeating that number here would read as a cap
    # somebody chose and would silently stop tracking the default if it moved.
    "signal_scan": 90.0,
}

#: Repair attempts after a contract violation. One. See the module docstring.
MAX_REPAIRS = 1

#: `llm_config.effort` is an Anthropic vocabulary. Gemini takes a thinking
#: level, and the two do not line up one-to-one — `xhigh` and `max` both map to
#: the highest Gemini offers, which is a real ceiling and not a rounding.
EFFORT_TO_THINKING = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "high",
    "max": "high",
}


class GeminiError(RuntimeError):
    """The call could not be completed. Carries no provider text."""


class GeminiRefusedError(RuntimeError):
    """Generation stopped on a safety or recitation finish reason."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"Gemini stopped generating: {reason}")


def _client(timeout: float = TIMEOUT_SECONDS):
    """An httpx client that trusts the operating system's certificates.

    Same reasoning as `probes.py`: certifi does not contain a corporate
    proxy's root, and the resulting handshake failure reads as "the provider is
    down".
    """
    import httpx

    try:
        import truststore

        verify: Any = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:  # noqa: BLE001 — fall back to the bundled roots
        log.info("gemini.truststore_unavailable falling back to bundled roots")
        verify = True
    return httpx.AsyncClient(timeout=timeout, verify=verify)


def repair_turns(previous: str, errors: str) -> list[dict[str, Any]]:
    """The follow-up turns that ask for a corrected object.

    The rejected output is sent back as the model's own turn and the complaint
    as ours, rather than restating the whole task. That keeps the correction
    anchored to what it actually produced — a fresh "try again" tends to
    return the same shape with different words.
    """
    return [
        {"role": "model", "parts": [{"text": previous}]},
        {
            "role": "user",
            "parts": [
                {
                    "text": (
                        "That response did not satisfy the contract:\n"
                        f"{errors}\n\n"
                        "Return the corrected object. Fix only what is listed; "
                        "keep everything else identical. Do not explain."
                    )
                }
            ],
        },
    ]


def build_request(
    *,
    model: str,
    prefix: PromptAssembly,
    user_content: str,
    output_model: type[BaseModel],
    effort: str,
    max_tokens: int,
    thinking: bool = True,
    extra_turns: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The request body. Pure, so the shape is testable without a network."""
    try:
        translated = translate(output_model)
    except SchemaTooComplexError as exc:
        raise GeminiError(
            f"{output_model.__name__} cannot be expressed in Gemini's schema "
            f"subset: {exc}"
        ) from exc

    if translated.dropped_fields:
        # A capability gap, reported rather than discovered later from output
        # that is quietly missing a field.
        log.warning(
            "gemini.fields_dropped contract=%s fields=%s — Gemini cannot describe "
            "these, so they will come back empty",
            output_model.__name__,
            ",".join(translated.dropped_fields),
        )

    generation: dict[str, Any] = {
        "responseMimeType": "application/json",
        "responseSchema": translated.schema,
        "maxOutputTokens": max_tokens,
    }
    if thinking:
        generation["thinkingConfig"] = {
            "thinkingLevel": EFFORT_TO_THINKING.get(effort, "medium")
        }

    body: dict[str, Any] = {
        # The cached prefix, in the order `prompt.py` fixes. Gemini caches
        # implicitly on a repeated prefix, so the order still earns its keep.
        "systemInstruction": {
            "parts": [{"text": block.text} for block in prefix.blocks]
        },
        "contents": [
            {"role": "user", "parts": [{"text": user_content}]},
            *(extra_turns or []),
        ],
        "generationConfig": generation,
    }
    if prefix.tools:
        try:
            body["tools"] = grounding.translate_tools(prefix.tools)
        except grounding.GroundingError as exc:
            raise GeminiError(str(exc)) from exc
        # Last, so the shared prefix before it stays byte-identical.
        body["systemInstruction"]["parts"].append({"text": grounding.SEARCH_NOTE})
    return body


def extract_text(payload: dict[str, Any]) -> str:
    """The generated JSON, from the first candidate.

    Parts also carry `thoughtSignature`, an opaque reasoning artefact with no
    `text`. Concatenating every part blindly corrupts the JSON, so only parts
    that actually carry text are joined.
    """
    candidates = payload.get("candidates") or []
    if not candidates:
        blocked = (payload.get("promptFeedback") or {}).get("blockReason")
        if blocked:
            raise GeminiRefusedError(str(blocked))
        raise GeminiError("Gemini returned no candidates")

    candidate = candidates[0]
    reason = candidate.get("finishReason")
    if reason in ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT"):
        raise GeminiRefusedError(str(reason))
    if reason == "MAX_TOKENS":
        # Truncated JSON does not parse, and "invalid JSON" would send someone
        # looking at the schema instead of at the token budget.
        #
        # **Which half** filled the budget is reported, because the old message
        # asserted it was thinking and sent at least one person down that road
        # for an afternoon. Gemini splits it: `thoughtsTokenCount` is
        # deliberation, `candidatesTokenCount` is the answer. Lowering effort
        # helps only the first; a runaway answer needs the contract or the
        # prompt looked at instead.
        usage = payload.get("usageMetadata") or {}
        thinking = usage.get("thoughtsTokenCount")
        answer = usage.get("candidatesTokenCount")
        if thinking is not None or answer is not None:
            split = (
                f" — {thinking or 0} tokens of thinking and {answer or 0} of "
                f"answer. "
                + (
                    "Thinking filled it: lower this stage's effort."
                    if (thinking or 0) > (answer or 0)
                    else "The answer filled it, not thinking: lowering effort "
                    "will not help. Look at how much this stage is being asked "
                    "to write."
                )
            )
        else:
            split = (
                " — thinking is charged against that budget, so lower this "
                "stage's effort before raising max_tokens"
            )
        raise GeminiError(f"Gemini hit maxOutputTokens before finishing{split}")

    parts = (candidate.get("content") or {}).get("parts") or []
    text = "".join(p["text"] for p in parts if isinstance(p.get("text"), str))
    if not text.strip():
        raise GeminiError("Gemini returned a candidate with no text")
    return text


def parse_output[R: BaseModel](text: str, output_model: type[R]) -> R:
    """Validate against the real contract.

    This is where the guarantees the schema could not carry are enforced. A
    model that returns five dimensions instead of six produces schema-valid
    JSON and an invalid `DimensionAssessments`, and it has to fail here rather
    than three layers downstream.
    """
    try:
        return output_model.model_validate_json(text)
    except ValidationError as exc:
        # Naming the fields is safe and necessary: these are our own model's
        # messages about our own contract, not provider text, so nothing from
        # the vendor — and certainly no key — passes through. Without them the
        # only way to find out what a stage disagreed about is to add logging
        # and run it again, which costs another call.
        where = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}"
            for e in exc.errors()[:5]
        )
        raise GeminiError(
            f"Gemini returned JSON that does not satisfy {output_model.__name__} "
            f"({exc.error_count()} error(s)) — {where}"
        ) from exc
    except ValueError as exc:
        raise GeminiError("Gemini returned text that is not valid JSON") from exc


def usage_of(payload: dict[str, Any]) -> dict[str, int]:
    """Token counts, mapped onto the same names the Anthropic path reports.

    `cachedContentTokenCount` is Gemini's implicit prefix cache. Reported as
    `cache_read_tokens` so one log line means the same thing on both providers
    — with the caveat in the module docstring that the two caches are not
    equivalent and cost should not be extrapolated between them.
    """
    meta = payload.get("usageMetadata") or {}
    return {
        "input_tokens": int(meta.get("promptTokenCount") or 0),
        "output_tokens": int(meta.get("candidatesTokenCount") or 0),
        "cache_read_tokens": int(meta.get("cachedContentTokenCount") or 0),
        "cache_write_tokens": 0,  # Gemini does not report one for implicit caching
    }


async def _post(
    client: Any, *, model: str, api_key: str, body: dict[str, Any]
) -> dict[str, Any]:
    try:
        response = await client.post(
            f"{BASE_URL}/{model}:generateContent",
            headers={"x-goog-api-key": api_key, "content-type": "application/json"},
            json=body,
        )
    except Exception as exc:  # noqa: BLE001 — surfaced as one error type
        raise GeminiError(f"could not reach Gemini: {type(exc).__name__}") from exc

    if response.status_code != 200:
        # Never the body. A rejection can quote the key that was sent — the
        # same rule the probes follow.
        raise GeminiError(
            f"Gemini returned HTTP {response.status_code} for model {model!r}"
        )
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        raise GeminiError("Gemini returned a non-JSON response") from exc


async def _count_tokens(
    client: Any, *, model: str, api_key: str, body: dict[str, Any]
) -> int:
    """What the request alone costs in prompt tokens.

    Free. Compared with what the call was billed, it tells an answer that
    searched from one written from memory — see `gemini_grounding`.
    """
    try:
        response = await client.post(
            f"{BASE_URL}/{model}:countTokens",
            headers={"x-goog-api-key": api_key, "content-type": "application/json"},
            json={"generateContentRequest": {"model": f"models/{model}", **body}},
        )
    except Exception as exc:  # noqa: BLE001 — surfaced as one error type
        raise GeminiError(f"could not reach Gemini: {type(exc).__name__}") from exc
    if response.status_code != 200:
        raise GeminiError(
            f"Gemini countTokens returned HTTP {response.status_code} for model {model!r}"
        )
    try:
        return int(response.json()["totalTokens"])
    except (ValueError, KeyError, TypeError) as exc:
        raise GeminiError("Gemini countTokens returned no token count") from exc


async def _grounded[R: BaseModel](
    parsed: R,
    *,
    client: Any,
    model: str,
    api_key: str,
    body: dict[str, Any],
    prompt_tokens: int,
) -> R:
    async def count() -> int:
        return await _count_tokens(client, model=model, api_key=api_key, body=body)

    async def resolve(links: set[str]) -> dict[str, str | None]:
        return await grounding.resolve_links(links, client)

    try:
        return await grounding.ground(
            parsed, prompt_tokens=prompt_tokens,
            count_request_tokens=count, resolve=resolve,
        )
    except grounding.GroundingError as exc:
        raise GeminiError(str(exc)) from exc


async def call[R: BaseModel](
    *,
    model: str,
    api_key: str,
    prefix: PromptAssembly,
    user_content: str,
    output_model: type[R],
    effort: str,
    max_tokens: int,
    scenario: str = "",
) -> tuple[R, dict[str, int]]:
    """One structured call, plus at most one repair. Validated object out.

    The one repair covers either failure a web stage meets: a contract
    violation, or a refusal for reciting a source at length. Never both —
    the bound is on calls, not on reasons.
    """
    grounded = bool(prefix.tools)

    def request(extra_turns=None, note: str | None = None):
        return build_request(
            model=model,
            prefix=prefix,
            user_content=f"{user_content}\n\n{note}" if note else user_content,
            output_model=output_model,
            effort=effort,
            max_tokens=max_tokens,
            extra_turns=extra_turns,
        )

    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }

    async with _client(STAGE_TIMEOUT_SECONDS.get(scenario, TIMEOUT_SECONDS)) as client:
        body = request()
        for attempt in range(MAX_REPAIRS + 1):
            payload = await _post(client, model=model, api_key=api_key, body=body)
            # Accumulated across attempts: a repair is a real call and a bill
            # that reports only the successful one understates what a stage costs.
            for key, value in usage_of(payload).items():
                totals[key] += value

            try:
                text = extract_text(payload)
            except GeminiRefusedError as exc:
                # Observed on search: quoting a well-covered company's press
                # verbatim trips the recitation filter, and a shorter quote
                # usually passes. Other refusals are final.
                if not (grounded and exc.reason == "RECITATION" and attempt < MAX_REPAIRS):
                    raise
                log.warning(
                    "gemini.recitation_retry contract=%s attempt=%d",
                    output_model.__name__, attempt + 1,
                )
                body = request(note=grounding.RECITATION_RETRY_NOTE)
                continue

            try:
                parsed = parse_output(text, output_model)
            except GeminiError as exc:
                if attempt >= MAX_REPAIRS:
                    raise
                log.warning(
                    "gemini.repair contract=%s attempt=%d reason=%s",
                    output_model.__name__, attempt + 1, exc,
                )
                body = request(extra_turns=repair_turns(text, str(exc)))
                continue

            if grounded:
                parsed = await _grounded(
                    parsed, client=client, model=model, api_key=api_key,
                    body=body, prompt_tokens=usage_of(payload)["input_tokens"],
                )
            return parsed, totals

    raise GeminiError("unreachable")  # pragma: no cover
