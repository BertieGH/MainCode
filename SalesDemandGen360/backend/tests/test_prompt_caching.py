"""Prompt caching, in two layers.

`docs/06 §5`: a silent cache miss costs money on every call and reports nothing.
The live assertion — `cache_read_input_tokens` non-zero across repeated runs —
is the real one, but it needs an API key and it bills. So there are two:

* **Determinism tests, always run.** Two independently built prefixes must be
  byte-identical. Every invalidator §5 names — a timestamp, an unsorted dict, a
  set-ordered tool list — breaks that equality, and breaks it locally, in a
  second, for free.
* **A live test, skipped without `ANTHROPIC_API_KEY`.** Nothing but a real
  response proves the cache actually hit.

The determinism layer is not a substitute for the live one. It is what makes
the live one almost never fail.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from app.services.prompt import (
    MAX_BREAKPOINTS,
    PromptAssembly,
    SystemBlock,
    build_research_prefix,
    stable_json,
)

ORG = {"name": "CGVAK", "icp": {"employees": "50-500", "regions": ["US", "UK"]}}
SERVICES = [
    {"code": "qa", "name": "QA engineering"},
    {"code": "data", "name": "Data platform"},
]
PROOFS = [
    {"title": "Retail migration", "is_approved": True},
    {"title": "Unapproved claim", "is_approved": False},
]


def _prefix(**over):
    kwargs = dict(
        org_profile=ORG,
        service_catalog=SERVICES,
        approved_proofs=PROOFS,
        stage_instructions="Find evidence. Cite everything.",
        writing_samples=["Short and plain."],
    )
    return build_research_prefix(**{**kwargs, **over})


class TestTheSameConfigRendersTheSameBytes:
    def test_two_builds_are_identical(self):
        assert _prefix().fingerprint() == _prefix().fingerprint()

    def test_dict_insertion_order_does_not_change_the_bytes(self):
        """Config comes back from Postgres in whatever order the rows were
        updated. If that reached the prompt, the cache would break on any edit
        to an unrelated field."""
        shuffled = {"icp": {"regions": ["US", "UK"], "employees": "50-500"}, "name": "CGVAK"}
        assert _prefix(org_profile=shuffled).fingerprint() == _prefix().fingerprint()

    def test_catalog_row_order_does_not_change_the_bytes(self):
        assert _prefix(service_catalog=list(reversed(SERVICES))).fingerprint() == (
            _prefix().fingerprint()
        )

    def test_a_real_change_does_change_the_bytes(self):
        """The counterpart. A fingerprint that never moves would pass every
        test above while proving nothing."""
        assert _prefix(stage_instructions="Different.").fingerprint() != (
            _prefix().fingerprint()
        )


class TestTheKnownInvalidatorsAreRefused:
    def test_a_timestamp_in_a_cached_block_raises(self):
        # The canonical silent invalidator: renders fine, differs every call.
        with pytest.raises(TypeError, match="timestamp"):
            stable_json({"generated_at": datetime.now(UTC)})

    def test_a_set_raises_rather_than_serialising_in_arbitrary_order(self):
        with pytest.raises(TypeError, match="not stable"):
            stable_json({"tools": {"web_search", "web_fetch"}})

    def test_a_uuid_is_allowed_because_it_is_stable(self):
        import uuid

        fixed = uuid.UUID("11111111-2222-3333-4444-555555555555")
        assert stable_json({"id": fixed}) == stable_json({"id": fixed})


class TestBlockStructure:
    def test_the_three_blocks_are_in_the_order_section_5_mandates(self):
        assert [b.name for b in _prefix().blocks] == ["org", "catalog", "stage"]

    def test_every_prefix_block_is_marked_cacheable(self):
        assert all(b.render().get("cache_control") for b in _prefix().blocks)

    def test_unapproved_proof_points_never_reach_the_prompt(self):
        """Blocked at generation, not caught at review — an unapproved claim
        that reaches the model can be drafted with."""
        text = _prefix().blocks[1].text
        assert "Retail migration" in text
        assert "Unapproved claim" not in text

    def test_exceeding_the_breakpoint_limit_fails_loudly(self):
        """Anthropic allows four. Silently dropping the fifth would cache the
        wrong prefix and nothing would report it."""
        assembly = PromptAssembly(
            blocks=[SystemBlock(f"b{i}", "x") for i in range(MAX_BREAKPOINTS + 1)]
        )
        with pytest.raises(ValueError, match="breakpoints"):
            assembly.system()

    def test_the_limit_itself_is_allowed(self):
        assembly = PromptAssembly(
            blocks=[SystemBlock(f"b{i}", "x") for i in range(MAX_BREAKPOINTS)]
        )
        assert len(assembly.system()) == MAX_BREAKPOINTS


@pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — the live cache assertion bills real tokens",
)
@pytest.mark.llm
class TestTheCacheActuallyHits:
    """The assertion `docs/08` asks for. Only a real response proves it."""

    async def test_cache_read_input_tokens_is_non_zero_on_the_second_call(self):
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic()
        prefix = _prefix()
        # Padded past the minimum cacheable prefix length; a short system block
        # is silently not cached and the test would fail for the wrong reason.
        prefix.blocks[2] = SystemBlock("stage", "Find evidence. Cite everything. " * 400)

        async def call(question: str):
            return await client.messages.create(
                model="claude-opus-5",
                max_tokens=64,
                system=prefix.system(),
                messages=[{"role": "user", "content": question}],
            )

        await call("Reply with the single word: one")
        second = await call("Reply with the single word: two")

        assert second.usage.cache_read_input_tokens > 0, (
            "the cached prefix did not hit on the second call — a silent "
            "invalidator is present in the system blocks"
        )
