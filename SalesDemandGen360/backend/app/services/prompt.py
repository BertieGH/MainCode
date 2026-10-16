"""Cache-safe prompt assembly.

`docs/06 §5`: the render order is `tools` → `system` → `messages`, and any byte
change invalidates everything after it. The first three system blocks are
identical across every account in a batch — that is the whole point, and it is
also the whole fragility. A `datetime.now()` in a block, a dict serialised in
insertion order, or a tool list built from a set silently costs the cache on
every call, and nothing anywhere reports an error.

So the blocks are built here and nowhere else, and `stable_json` is the only
sanctioned way to put config into one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

#: Anthropic allows at most four cache breakpoints per request.
MAX_BREAKPOINTS = 4


def stable_json(value: Any) -> str:
    """Serialise config so the same config always renders the same bytes.

    `sort_keys` because Python dict order reflects insertion, which reflects
    the order rows came back from Postgres — a detail that changes under you
    when a row is updated. `separators` because the default puts a space after
    ':' in some paths and not others depending on indent.
    """
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=_fallback, ensure_ascii=False
    )


def _fallback(value: Any) -> Any:
    # Deliberately narrow. A datetime reaching a cached block is the exact bug
    # this module exists to prevent, so it raises rather than being formatted.
    import datetime as _dt
    import decimal
    import uuid as _uuid

    if isinstance(value, _dt.datetime | _dt.date):
        raise TypeError(
            f"{value!r} is a timestamp and must not appear in a cached prompt block — "
            "it changes between runs and silently invalidates the cache"
        )
    if isinstance(value, _uuid.UUID):
        return str(value)
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, set | frozenset):
        raise TypeError(
            f"{value!r} is a set; its iteration order is not stable across processes. "
            "Sort it into a list first."
        )
    raise TypeError(f"{type(value).__name__} is not safely serialisable into a prompt")


@dataclass
class SystemBlock:
    name: str
    text: str
    cache: bool = True

    def render(self) -> dict[str, Any]:
        block: dict[str, Any] = {"type": "text", "text": self.text}
        if self.cache:
            block["cache_control"] = {"type": "ephemeral"}
        return block


@dataclass
class PromptAssembly:
    """The cached prefix of a request, in the order §5 mandates."""

    blocks: list[SystemBlock] = field(default_factory=list)
    #: Deterministic order, never sorted differently between calls.
    tools: list[dict[str, Any]] = field(default_factory=list)
    #: Which version of the stage's instructions built this, for stamping onto
    #: whatever the call produces. Deliberately **not** part of any block: it
    #: would change the prefix byte-for-byte on every edit and the point of the
    #: prefix is that it is identical across a batch so the cache hits. It
    #: rides alongside the text, not inside it. None when the stage ran on the
    #: shipped default with no row to name.
    prompt_version: int | None = None

    def system(self) -> list[dict[str, Any]]:
        cached = sum(1 for b in self.blocks if b.cache)
        if cached > MAX_BREAKPOINTS:
            raise ValueError(
                f"{cached} cache breakpoints requested; the limit is {MAX_BREAKPOINTS}. "
                "Merge blocks rather than dropping cache_control from one."
            )
        return [b.render() for b in self.blocks]

    def fingerprint(self) -> str:
        """What the cache actually keys on, for assertions and logging.

        Two runs that should share a cache entry must produce the same value.
        Comparing this is how a silent invalidator gets caught in a test rather
        than in a month of billing.
        """
        return stable_json(
            {"tools": self.tools, "system": [b.render() for b in self.blocks]}
        )


def build_research_prefix(
    *,
    org_profile: dict[str, Any],
    service_catalog: list[dict[str, Any]],
    icp_profiles: list[dict[str, Any]] | None = None,
    approved_proofs: list[dict[str, Any]],
    stage_instructions: str,
    writing_samples: list[str],
    tools: list[dict[str, Any]] | None = None,
    prompt_version: int | None = None,
) -> PromptAssembly:
    """The three-block prefix from §5, in that order.

    Everything here must be identical across accounts in a batch. The volatile
    per-account context belongs in `messages`, which is not cached.
    """
    return PromptAssembly(
        tools=list(tools or []),
        prompt_version=prompt_version,
        blocks=[
            SystemBlock(
                "org",
                "# CGVAK\n" + stable_json({"org_profile": org_profile}),
            ),
            SystemBlock(
                "catalog",
                "# Services and approved proof points\n"
                + stable_json(
                    {
                        "services": sorted(service_catalog, key=lambda s: str(s.get("code", ""))),
                        # Beside the services rather than in the org block, so
                        # the prefix stays identical across every account in a
                        # batch and the cache keeps hitting.
                        "icp_profiles": sorted(
                            icp_profiles or [], key=lambda p: str(p.get("name", ""))
                        ),
                        # Only approved claims may reach a prompt at all, so the
                        # filter is here rather than at draft review.
                        "proof_points": sorted(
                            [p for p in approved_proofs if p.get("is_approved")],
                            key=lambda p: str(p.get("title", "")),
                        ),
                    }
                ),
            ),
            SystemBlock(
                "stage",
                stage_instructions.strip()
                + (
                    "\n\n# Writing samples\n"
                    "Voice only: tone, length, rhythm and register. Never reuse a sample's "
                    "phrases, structure, greeting, sign-off or ask — the ask comes from the "
                    "strategy. Each is labelled with its channel; follow one only for steps "
                    "on that channel.\n"
                    if writing_samples
                    else "\n\n# Writing samples\n"
                )
                + "\n---\n".join(writing_samples),
            ),
        ],
    )
