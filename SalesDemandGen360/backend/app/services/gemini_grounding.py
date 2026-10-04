"""Web search on Gemini, and proving it happened.

The web stages carry Anthropic's server tools (`stages.WEB_TOOLS`). On Gemini
the equivalent is Grounding with Google Search. The request shape is the easy
part; what comes back is what this module is for. Every point below was found
by live probe against `gemini-3.5-flash-lite`, not read from a spec:

* **With a response schema, no grounding metadata is returned** — no
  `groundingMetadata`, no `webSearchQueries`, no `citationMetadata`. The one
  per-link proof that a page came from a search is the link itself: Google's
  `vertexaisearch…/grounding-api-redirect/…` links, which the model can only
  have copied from a real result. Each answers 302 with the real page.
* **The model may not search at all.** At thinking level `low` it answered from
  memory: tidy, plausible passages with newsroom URLs, and a prompt token count
  equal to what was sent. At `high` it searched, and the count rose by the
  injected results (125 sent, 704 billed). That difference is how an answer with
  no links is told apart from one nobody looked for.
* **Long verbatim quotes are refused** (`finishReason: RECITATION`), which the
  excerpt rule invites. Quotes are asked to be one short sentence, and a
  refusal is retried once with that repeated (`gemini.call`).

So a web stage on Gemini is accepted only when it can be shown to have
searched, and research evidence is kept only when its link came from a result.
Anything else is discarded and *said* to have been — a passage nothing shows
was read is the failure `docs/01` invariant 1 exists to prevent.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)

#: Where Google's grounding links point. A link with this prefix came from a
#: search result; nothing else the model writes is evidence of that.
REDIRECT_PREFIX = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/"

#: Prompt tokens beyond the request's own count that mean results were
#: injected. Observed: +0 without a search, +127 to +3,400 with one.
SEARCH_TOKEN_MARGIN = 64

#: Appended to the system instruction of every web stage sent to Gemini.
SEARCH_NOTE = (
    "# Web search on this provider\n"
    "Search with Google Search before answering; never answer from memory. When "
    "you give the page a passage or fact came from, use the exact link of the "
    "Google Search result you took it from. Keep any quoted text to the single "
    "sentence that states the fact, under 30 words — this provider refuses long "
    "verbatim passages."
)

#: Added to the user turn when a first answer was refused for recitation.
RECITATION_RETRY_NOTE = (
    "Your previous answer was stopped for reproducing source text at length. "
    "Answer again with every quoted excerpt cut to the one sentence that states "
    "the fact, under 30 words."
)

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class GroundingError(RuntimeError):
    """A web stage's answer cannot be shown to rest on a search."""


def translate_tools(tools: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Anthropic server tools → Gemini tools.

    `web_search_*` becomes `googleSearch`. `web_fetch_*` is dropped rather than
    mapped to URL context: under a response schema URL context reports nothing
    we could check a page against, so a page it "read" would be unverifiable.
    Search reaches the same pages as links that can be checked.

    Anything else is refused. Sending a stage without a tool it asked for is
    how research came to answer from memory in the first place.
    """
    out: list[dict[str, Any]] = []
    for tool in tools:
        kind = str(tool.get("type", ""))
        if kind.startswith("web_search"):
            if {"googleSearch": {}} not in out:
                out.append({"googleSearch": {}})
        elif kind.startswith("web_fetch"):
            continue
        else:
            raise GroundingError(f"no Gemini equivalent for the {kind!r} tool")
    return out


def is_redirect(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(REDIRECT_PREFIX)


def redirect_links(node: Any) -> set[str]:
    """Every grounding link anywhere in a dumped contract."""
    found: set[str] = set()
    if is_redirect(node):
        found.add(node)
    elif isinstance(node, dict):
        for value in node.values():
            found |= redirect_links(value)
    elif isinstance(node, list):
        for value in node:
            found |= redirect_links(value)
    return found


def replace_links(node: Any, mapping: dict[str, str]) -> Any:
    if isinstance(node, str):
        return mapping.get(node, node)
    if isinstance(node, dict):
        return {k: replace_links(v, mapping) for k, v in node.items()}
    if isinstance(node, list):
        return [replace_links(v, mapping) for v in node]
    return node


async def resolve_links(links: Iterable[str], client: Any) -> dict[str, str | None]:
    """Where each grounding link leads, read from its `Location` header.

    The page itself is never fetched — only the redirect answered. `None` for a
    link that does not answer with a redirect to a real address: expired, or
    not what it claims to be. Sent without any of our headers, so no key goes
    to the redirect host.
    """
    async def one(url: str) -> str | None:
        try:
            response = await client.get(url, follow_redirects=False, timeout=15.0)
        except Exception as exc:  # noqa: BLE001 — an unresolved link is dropped, not fatal
            log.info("grounding.unresolved err=%s", type(exc).__name__)
            return None
        target = response.headers.get("location")
        if (
            response.status_code in _REDIRECT_STATUSES
            and isinstance(target, str)
            and target.startswith(("https://", "http://"))
            and not is_redirect(target)
        ):
            return target
        return None

    ordered = sorted(set(links))
    results = await asyncio.gather(*(one(url) for url in ordered))
    return dict(zip(ordered, results, strict=True))


def keep_retrieved_evidence(
    data: dict[str, Any], resolved: dict[str, str | None]
) -> tuple[dict[str, Any], int]:
    """For a research batch: keep the passages whose link came from a result.

    Each kept passage has its grounding link swapped for the page it leads to,
    so `source_url` re-opens the page and the dedup hash is stable — the
    grounding link differs on every call, the page does not.
    """
    kept: list[dict[str, Any]] = []
    dropped = 0
    for item in data.get("evidence") or []:
        url = item.get("source_url")
        real = resolved.get(url) if is_redirect(url) else None
        if real:
            kept.append({**item, "source_url": real})
        else:
            dropped += 1

    out = {**data, "evidence": kept}
    if dropped:
        out["not_found"] = [
            *(data.get("not_found") or []),
            f"{dropped} passage(s) discarded: their links were not Google Search "
            "results, or no longer resolve, so nothing shows they were read",
        ]
    return out, dropped


async def ground[R: BaseModel](
    parsed: R,
    *,
    prompt_tokens: int,
    count_request_tokens: Callable[[], Awaitable[int]],
    resolve: Callable[[set[str]], Awaitable[dict[str, str | None]]],
) -> R:
    """Accept a web stage's answer only if it searched; point links at pages.

    The request's own token count is fetched only when the answer carries no
    grounding link — a link already proves a search, and counting is a call.
    """
    data = parsed.model_dump(mode="json")
    links = redirect_links(data)

    if not links:
        baseline = await count_request_tokens()
        if prompt_tokens - baseline < SEARCH_TOKEN_MARGIN:
            raise GroundingError(
                "Gemini answered without searching the web "
                f"({prompt_tokens} prompt tokens for a {baseline}-token request), "
                "so its answer came from memory. Raise this stage's effort on the "
                "Model config screen — it searched at high, not at low."
            )

    resolved = await resolve(links) if links else {}
    if isinstance(data.get("evidence"), list):
        data, dropped = keep_retrieved_evidence(data, resolved)
    else:
        data = replace_links(data, {k: v for k, v in resolved.items() if v})
        dropped = 0

    log.info(
        "grounding.done contract=%s links=%d resolved=%d discarded=%d",
        type(parsed).__name__, len(links),
        sum(1 for v in resolved.values() if v), dropped,
    )
    try:
        return type(parsed).model_validate(data)
    except ValidationError as exc:
        raise GroundingError(
            f"{type(parsed).__name__} no longer validates after grounding: "
            f"{exc.error_count()} error(s)"
        ) from exc
