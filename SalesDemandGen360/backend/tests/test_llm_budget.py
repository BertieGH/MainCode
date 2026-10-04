"""What happens when a call thinks itself out of room.

Two strategy calls ran the full three minutes and returned nothing, while a
sound call on the same stage took nine seconds. Thinking is charged against
`maxOutputTokens`, so a derailed call does not fail — it thinks until the
ceiling or the clock stops it, and the retry that followed asked the same
question of the same reasoner.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import gemini, llm


def config(effort: str = "high") -> SimpleNamespace:
    return SimpleNamespace(
        scenario="strategy_synthesis", provider="gemini", model="gemini-3.8-flash",
        effort=effort, max_tokens=48000, thinking_mode="adaptive",
    )


class TestARunawayIsRetriedQuieter:
    async def test_it_drops_one_thinking_level_rather_than_repeating_itself(
        self, monkeypatch
    ):
        efforts: list[str] = []

        async def out_of_room(**kw):
            efforts.append(kw["effort"])
            if len(efforts) == 1:
                raise gemini.GeminiError("Gemini hit maxOutputTokens before finishing")
            return SimpleNamespace(), {"input_tokens": 10, "output_tokens": 20,
                                       "cache_read_tokens": 0, "cache_write_tokens": 0}

        monkeypatch.setattr(gemini, "call", out_of_room)
        result = await llm.call_structured(
            config=config(), prefix=SimpleNamespace(tools=None, blocks=[]),
            user_content="{}", output_model=dict, api_key="k",
        )
        assert efforts == ["high", "medium"], "the second attempt changes what went wrong"
        assert result.output_tokens == 20

    async def test_a_timeout_is_the_same_failure_and_is_retried_too(self, monkeypatch):
        """Thinking runs against the budget *and* the clock, so a derailed
        call ends at whichever ceiling it reaches first."""
        efforts: list[str] = []

        async def slow(**kw):
            efforts.append(kw["effort"])
            if len(efforts) == 1:
                raise gemini.GeminiError("could not reach Gemini: ReadTimeout")
            return SimpleNamespace(), {"input_tokens": 10, "output_tokens": 20,
                                       "cache_read_tokens": 0, "cache_write_tokens": 0}

        monkeypatch.setattr(gemini, "call", slow)
        await llm.call_structured(
            config=config(), prefix=SimpleNamespace(tools=None, blocks=[]),
            user_content="{}", output_model=dict, api_key="k",
        )
        assert efforts == ["high", "medium"]

    async def test_a_failure_that_is_not_about_budget_is_not_retried(self, monkeypatch):
        calls: list[str] = []

        async def refused(**kw):
            calls.append(kw["effort"])
            raise gemini.GeminiError("the model is overloaded")

        monkeypatch.setattr(gemini, "call", refused)
        with pytest.raises(llm.LlmUnavailableError, match="overloaded"):
            await llm.call_structured(
                config=config(), prefix=SimpleNamespace(tools=None, blocks=[]),
                user_content="{}", output_model=dict, api_key="k",
            )
        assert calls == ["high"], "only a budget blowout earns a quieter second try"

    async def test_the_lowest_level_has_nowhere_quieter_to_go(self, monkeypatch):
        async def out_of_room(**kw):
            raise gemini.GeminiError("Gemini hit maxOutputTokens before finishing")

        monkeypatch.setattr(gemini, "call", out_of_room)
        with pytest.raises(llm.LlmUnavailableError):
            await llm.call_structured(
                config=config("low"), prefix=SimpleNamespace(tools=None, blocks=[]),
                user_content="{}", output_model=dict, api_key="k",
            )

    async def test_the_second_failure_says_what_was_already_tried(self, monkeypatch):
        async def out_of_room(**kw):
            raise gemini.GeminiError("Gemini hit maxOutputTokens before finishing")

        monkeypatch.setattr(gemini, "call", out_of_room)
        with pytest.raises(llm.LlmUnavailableError, match="retried at medium thinking"):
            await llm.call_structured(
                config=config(), prefix=SimpleNamespace(tools=None, blocks=[]),
                user_content="{}", output_model=dict, api_key="k",
            )


class TestAStageGetsItsOwnClock:
    def test_the_slow_stages_are_held_to_a_tighter_one(self):
        """A call still thinking at a minute is not producing better copy."""
        assert gemini.STAGE_TIMEOUT_SECONDS["strategy_synthesis"] < gemini.TIMEOUT_SECONDS
        assert gemini.STAGE_TIMEOUT_SECONDS["outreach_drafting"] < gemini.TIMEOUT_SECONDS

    def test_an_unnamed_stage_keeps_the_long_default(self):
        """Research genuinely takes minutes; only the short stages are capped."""
        assert gemini.STAGE_TIMEOUT_SECONDS.get("company_research") is None
