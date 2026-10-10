"""The Gemini adapter, and the schema translation that makes it possible.

Two dialects that disagree in ways which fail *silently in the useful
direction* — the request is accepted and the output is subtly wrong. Every case
below was found by running against the live API, not by reading a spec:

* Pydantic hoists nested models into `$defs`/`$ref`; Gemini has no `$ref`, so
  every one of our contracts arrived as an empty object.
* Dropping `format: uuid` left a plain string, and the model invented
  "signal-123" for a `list[uuid.UUID]`. Schema-valid, contract-invalid.
* `dict[str, float]` cannot be described at all.
* A `thoughtSignature` part sits beside the text part and corrupts the JSON if
  parts are concatenated blindly.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from app.schemas.draft import DraftSet, FreshnessVerdict
from app.schemas.evaluation import EvaluationResult
from app.schemas.qualification import DimensionAssessments
from app.schemas.strategy import StrategyProposal
from app.services import gemini
from app.services.gemini_schema import (
    SchemaTooComplexError,
    to_gemini_schema,
    translate,
)


def _walk(node, seen=None):
    """Every dict in a schema tree, for whole-tree assertions."""
    seen = seen if seen is not None else []
    if isinstance(node, dict):
        seen.append(node)
        for v in node.values():
            _walk(v, seen)
    elif isinstance(node, list):
        for v in node:
            _walk(v, seen)
    return seen


class TestNestingSurvives:
    """The failure that made every contract useless: a dropped reference."""

    @pytest.mark.parametrize(
        "model", [DraftSet, StrategyProposal, DimensionAssessments, FreshnessVerdict]
    )
    def test_no_reference_survives_translation(self, model):
        schema = to_gemini_schema(model)
        for node in _walk(schema):
            assert "$ref" not in node
            assert "$defs" not in node

    def test_a_nested_model_is_inlined_with_its_properties(self):
        touches = to_gemini_schema(DraftSet)["properties"]["touches"]
        assert touches["type"] == "array"
        item = touches["items"]
        assert item["type"] == "object"
        # If the reference had been dropped this would be empty, and every call
        # would return one empty object per touch.
        assert "step_no" in item["properties"]
        assert "signal_dependence" in item["properties"]

    def test_an_object_that_lost_its_properties_is_refused(self):
        """Better to fail than to return an empty object from every call."""

        class Empty(BaseModel):
            pass

        with pytest.raises(SchemaTooComplexError):
            to_gemini_schema(Empty)


class TestTheKeywordsGeminiDoesNotKnow:
    @pytest.mark.parametrize(
        "model", [DraftSet, StrategyProposal, DimensionAssessments]
    )
    def test_unsupported_keywords_are_stripped(self, model):
        for node in _walk(to_gemini_schema(model)):
            for banned in (
                "additionalProperties",
                "$schema",
                "anyOf",
                "allOf",
                "default",
            ):
                assert banned not in node

    def test_optional_fields_become_nullable_rather_than_a_union(self):
        """An optional string is a union in Pydantic and nullable in Gemini."""
        item = to_gemini_schema(DraftSet)["properties"]["touches"]["items"]
        assert item["properties"]["subject"]["nullable"] is True
        assert item["properties"]["subject"]["type"] == "string"

    def test_a_real_two_type_union_is_refused_not_guessed(self):
        class Ambiguous(BaseModel):
            value: int | str

        with pytest.raises(SchemaTooComplexError):
            to_gemini_schema(Ambiguous)

    def test_property_order_is_pinned(self):
        """Gemini emits fields in the order given; unpinned it drifts."""
        schema = to_gemini_schema(FreshnessVerdict)
        assert schema["propertyOrdering"] == list(schema["properties"])


class TestConstraintsThatMustSurviveAsProse:
    """A constraint the schema cannot carry has to be said in words.

    Observed live: with the uuid format simply dropped, the model returned
    "signal-..." for a list of UUIDs. The output satisfied the schema and
    failed the contract, which is the most expensive kind of wrong.
    """

    def test_a_uuid_field_tells_the_model_it_is_a_uuid(self):
        field = to_gemini_schema(FreshnessVerdict)["properties"]["stale_signal_ids"]
        assert "format" not in field["items"]
        assert "UUID" in field["items"]["description"]
        # And that it must not make one up, which is the actual failure.
        assert "never invent" in field["items"]["description"].lower()

    def test_an_existing_description_is_kept_alongside_the_hint(self):
        import uuid as _uuid

        class Cites(BaseModel):
            ref: _uuid.UUID = Field(description="The signal this rests on")

        described = to_gemini_schema(Cites)["properties"]["ref"]["description"]
        assert "The signal this rests on" in described
        assert "UUID" in described


class TestWhatCannotBeExpressedAtAll:
    def test_a_free_form_map_is_dropped_and_reported(self):
        """EvaluationResult.scores is an arbitrary criterion-name map.

        Optional, so the contract still runs — but the capability gap is
        reported rather than discovered later from output quietly missing it.
        """
        result = translate(EvaluationResult)
        assert result.dropped_fields == ["scores"]
        assert "scores" not in result.schema["properties"]

    def test_a_required_free_form_map_raises(self):
        """A contract whose mandatory field cannot be asked for is not runnable."""

        class NeedsMap(BaseModel):
            weights: dict[str, float]

        with pytest.raises(SchemaTooComplexError):
            to_gemini_schema(NeedsMap)


class TestReadingTheResponse:
    def test_a_thought_signature_part_does_not_corrupt_the_json(self):
        """Parts carry reasoning artefacts with no text beside the real one."""
        payload = {
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {
                        "parts": [
                            {"text": '{"proceed": true}'},
                            {"thoughtSignature": "EuMOCuAOARFNMg9zc0"},
                        ]
                    },
                }
            ]
        }
        assert gemini.extract_text(payload) == '{"proceed": true}'

    def test_truncation_is_named_as_a_token_budget_problem(self):
        """Reporting invalid JSON would send someone to look at the schema."""
        payload = {
            "candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": []}}]
        }
        with pytest.raises(gemini.GeminiError, match="maxOutputTokens"):
            gemini.extract_text(payload)

    def test_a_safety_stop_is_a_refusal_not_an_error(self):
        payload = {"candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}]}
        with pytest.raises(gemini.GeminiRefusedError):
            gemini.extract_text(payload)

    def test_a_blocked_prompt_is_a_refusal(self):
        with pytest.raises(gemini.GeminiRefusedError):
            gemini.extract_text({"promptFeedback": {"blockReason": "SAFETY"}})

    def test_usage_maps_onto_the_shared_names(self):
        usage = gemini.usage_of(
            {
                "usageMetadata": {
                    "promptTokenCount": 407,
                    "candidatesTokenCount": 427,
                    "cachedContentTokenCount": 128,
                }
            }
        )
        assert usage == {
            "input_tokens": 407,
            "output_tokens": 427,
            "cache_read_tokens": 128,
            "cache_write_tokens": 0,
        }


class TestTheContractIsEnforcedHereNotByTheSchema:
    """The whole reason validation happens client-side on this provider.

    Observed live: the model returned a dimension scored 20 while declaring it
    had no evidence. Schema-valid, and exactly what the contract exists to
    refuse.
    """

    def test_a_schema_valid_contract_violation_is_caught(self):
        body = (
            '{"assessments": [{"dimension": "buyer", "score": 20, '
            '"reason": "guessed", "evidence_ids": [], "basis": "no_evidence"}]}'
        )
        with pytest.raises(gemini.GeminiError, match="must score 0"):
            gemini.parse_output(body, DimensionAssessments)

    def test_the_failing_field_is_named(self):
        """Without this the only way to learn what went wrong is another call."""
        with pytest.raises(gemini.GeminiError) as exc:
            gemini.parse_output('{"proceed": false}', FreshnessVerdict)
        assert "stop_reason" in str(exc.value)

    def test_non_json_is_reported_as_non_json(self):
        with pytest.raises(gemini.GeminiError):
            gemini.parse_output("I cannot help with that.", FreshnessVerdict)


class TestTheRequestShape:
    def _body(self, **over):
        from app.services.prompt import PromptAssembly, SystemBlock

        kwargs = {
            "model": "gemini-3.8-flash",
            "prefix": PromptAssembly(blocks=[SystemBlock("stage", "instructions")]),
            "user_content": "the account",
            "output_model": FreshnessVerdict,
            "effort": "high",
            "max_tokens": 4000,
        }
        kwargs.update(over)
        return gemini.build_request(**kwargs)

    def test_the_system_prefix_is_sent_as_system_instruction(self):
        body = self._body()
        assert body["systemInstruction"]["parts"][0]["text"] == "instructions"
        # Per-account content stays in `contents`, which is not cached.
        assert body["contents"][0]["parts"][0]["text"] == "the account"

    @pytest.mark.parametrize(
        ("effort", "level"),
        [
            ("low", "low"),
            ("medium", "medium"),
            ("high", "high"),
            ("xhigh", "high"),
            ("max", "high"),
        ],
    )
    def test_effort_maps_onto_a_thinking_level(self, effort, level):
        """xhigh and max hit a real ceiling rather than rounding up."""
        body = self._body(effort=effort)
        assert body["generationConfig"]["thinkingConfig"]["thinkingLevel"] == level

    def test_json_output_is_requested_with_the_schema(self):
        config = self._body()["generationConfig"]
        assert config["responseMimeType"] == "application/json"
        assert config["responseSchema"]["type"] == "object"

    def test_a_repair_turn_quotes_the_rejected_output(self):
        """Anchored to what the model produced, not a fresh "try again"."""
        turns = gemini.repair_turns('{"score": 20}', "buyer: must score 0")
        assert turns[0]["role"] == "model"
        assert '{"score": 20}' in turns[0]["parts"][0]["text"]
        assert "buyer: must score 0" in turns[1]["parts"][0]["text"]

    def test_repairs_are_bounded_at_one(self):
        """A model that cannot comply given the complaint will not on the fifth."""
        assert gemini.MAX_REPAIRS == 1


class TestEveryContractCanBeAskedFor:
    """A stage whose contract cannot be translated cannot run on Gemini.

    Checked for all of them at once, because the failure appears mid-run on a
    rep's account after research has already been paid for.
    """

    @pytest.mark.parametrize(
        "name",
        [
            "EvidenceBatch",
            "ContactBatch",
            "SignalBatch",
            "AccountContextPayload",
            "DimensionAssessments",
            "StrategyProposal",
            "DraftSet",
            "FreshnessVerdict",
            "EvaluationResult",
            "SalesPrepPayload",
        ],
    )
    def test_the_contract_translates(self, name):
        import importlib

        for module in (
            "app.schemas.evidence",
            "app.schemas.contact",
            "app.schemas.signal",
            "app.schemas.context",
            "app.schemas.qualification",
            "app.schemas.strategy",
            "app.schemas.draft",
            "app.schemas.evaluation",
            "app.schemas.prep",
        ):
            model = getattr(importlib.import_module(module), name, None)
            if model is not None:
                assert to_gemini_schema(model)["type"] == "object"
                return
        pytest.fail(f"{name} not found in any schema module")

    def test_the_registry_built_batch_translates(self):
        """Built per run from the active signal types, so it is not static."""
        from app.schemas.signal import build_batch_model

        schema = to_gemini_schema(build_batch_model(["hiring_surge", "funding_round"]))
        signal = schema["properties"]["signals"]["items"]
        assert signal["properties"]["signal_type"]["enum"] == [
            "hiring_surge",
            "funding_round",
        ]


@pytest.mark.llm
class TestAgainstTheLiveApi:
    """The only thing the fakes above cannot prove: that it actually runs.

    Run with `pytest -m llm`. Excluded from the default run because it bills.
    Uses the stored Gemini credential rather than an environment variable, so
    it exercises the same path a stage does.
    """

    async def _key(self):
        import os

        if not os.getenv("TEST_DATABASE_URL") and not os.getenv("GEMINI_API_KEY"):
            pytest.skip("no Gemini credential available")
        if key := os.getenv("GEMINI_API_KEY"):
            return key

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.config import get_settings
        from app.models.config import IntegrationCredential
        from app.services import crypto

        engine = create_async_engine(str(get_settings().database_url))
        async with async_sessionmaker(engine)() as session:
            row = (
                await session.execute(
                    select(IntegrationCredential).where(
                        IntegrationCredential.provider == "gemini"
                    )
                )
            ).scalars().first()
        await engine.dispose()
        if row is None:
            pytest.skip("no stored Gemini credential")
        return crypto.decrypt(row.value_encrypted).reveal()

    async def test_a_flat_contract_round_trips(self):
        from app.services import instructions, llm
        from app.services.prompt import PromptAssembly, SystemBlock

        result = await llm.call_structured(
            config=llm.StageConfig(
                scenario="pre_send_revalidation",
                provider="gemini",
                model="gemini-3.8-flash",
                effort="low",
                max_tokens=4000,
            ),
            prefix=PromptAssembly(
                blocks=[
                    SystemBlock("stage", instructions.block("pre_send_revalidation"))
                ]
            ),
            user_content=(
                "A scheduled message says 'congratulations on your Series B'. The "
                "round it cites closed in March 2019 and its signal has expired. "
                "Today is September 2026. Should it still send?"
            ),
            output_model=FreshnessVerdict,
            api_key=await self._key(),
        )
        assert result.parsed.proceed is False
        assert result.parsed.stop_reason == "signal_expired"
        assert result.input_tokens > 0

    async def test_a_nested_contract_honours_a_rule_the_schema_cannot_express(self):
        """Six dimensions, and an evidence-free one pinned to zero.

        Neither is expressible in Gemini's schema subset — they are enforced by
        the Pydantic contract on the way back in, with one repair attempt if
        the first response misses.
        """
        from app.services import instructions, llm
        from app.services.prompt import PromptAssembly, SystemBlock

        result = await llm.call_structured(
            config=llm.StageConfig(
                scenario="qualification_assessment",
                provider="gemini",
                model="gemini-3.8-flash",
                effort="medium",
                max_tokens=8000,
            ),
            prefix=PromptAssembly(
                blocks=[
                    SystemBlock(
                        "stage", instructions.block("qualification_assessment")
                    )
                ]
            ),
            user_content=(
                "Assess this account. Evidence: [ev-1] 'Northwind opened six QA "
                "engineer roles in August 2026.' [ev-2] 'Northwind closed a $30m "
                "Series B in March 2026.' We have never contacted them, so "
                "engagement has no evidence at all. Cite ids exactly as given."
            ),
            output_model=DimensionAssessments,
            api_key=await self._key(),
        )

        by_dimension = result.parsed.by_dimension()
        assert len(by_dimension) == 6
        engagement = by_dimension["engagement"]
        assert engagement.basis == "no_evidence"
        assert engagement.score == 0


class TestWhatA429Says:
    """"HTTP 429" alone cannot be acted on.

    It cost a fifty-account run its last five accounts, and left no way to
    tell whether to wait a minute or until tomorrow — the answer was in the
    response and was being discarded. The body is still never read as text,
    because a rejection can quote the key that was sent (invariant 9). Only
    Google's own structured identifiers are taken out of it.
    """

    def test_the_quota_and_the_retry_delay_are_read(self):
        from app.services.gemini import _quota_hint

        retry_after, quota = _quota_hint(
            {
                "error": {
                    "code": 429,
                    "status": "RESOURCE_EXHAUSTED",
                    "message": "Quota exceeded for key AIzaSyFAKEKEYFAKEKEY",
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                            "violations": [
                                {
                                    "quotaMetric": "generativelanguage.googleapis.com/generate_content_requests",
                                    "quotaId": "GenerateRequestsPerDayPerProjectPerModel",
                                }
                            ],
                        },
                        {
                            "@type": "type.googleapis.com/google.rpc.RetryInfo",
                            "retryDelay": "41s",
                        },
                    ],
                }
            }
        )
        assert quota == "GenerateRequestsPerDayPerProjectPerModel"
        assert retry_after == 41.0

    def test_the_message_is_never_carried(self):
        """The one field that can echo the request is the one left behind."""
        from app.services.gemini import GeminiError, _quota_hint

        body = {
            "error": {
                "message": "Quota exceeded for key AIzaSyFAKEKEYFAKEKEY",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [{"quotaId": "GenerateRequestsPerMinutePerProject"}],
                    }
                ],
            }
        }
        retry_after, quota = _quota_hint(body)
        exc = GeminiError(
            f"Gemini returned HTTP 429 for model 'x', quota {quota}",
            status_code=429,
            retry_after=retry_after,
            quota=quota,
        )
        assert "AIzaSyFAKEKEYFAKEKEY" not in str(exc)
        assert "AIzaSyFAKEKEYFAKEKEY" not in repr(exc.__dict__)
        assert exc.is_rate_limit

    def test_a_shape_that_is_not_what_is_expected_is_not_an_error(self):
        """This runs while handling an error; it must not replace one."""
        from app.services.gemini import _quota_hint

        for junk in (None, "", [], {"error": "nope"}, {"error": {"details": "nope"}},
                     {"error": {"details": [None, 7, {"@type": "RetryInfo"}]}}):
            assert _quota_hint(junk) == (None, None)

    def test_a_per_day_quota_is_told_from_a_per_minute_one(self):
        from app.services.llm import LlmUnavailableError

        daily = LlmUnavailableError(
            "429", quota="GenerateRequestsPerDayPerProjectPerModel", rate_limited=True
        )
        minutely = LlmUnavailableError(
            "429", quota="GenerateRequestsPerMinutePerProject", rate_limited=True
        )
        unnamed = LlmUnavailableError("429", rate_limited=True)

        assert daily.exhausted_for_the_day
        assert not minutely.exhausted_for_the_day
        # Unknown counts as not daily: a caller that waits a minute loses a
        # minute, where one that stops abandons accounts it could have done.
        assert not unnamed.exhausted_for_the_day

    def test_a_body_that_names_nothing_still_says_it_was_quota(self):
        """Measured against the live API: this is the common shape.

        While genuinely rate limited, Google returned `code`, `message` and
        `status` and no `details` at all — and the message held no quota
        identifier in any form. `RESOURCE_EXHAUSTED` is then the only honest
        answer, and it is still worth carrying: it separates a quota refusal
        from any other 429.
        """
        from app.services.gemini import _quota_hint

        retry_after, quota = _quota_hint(
            {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "..."}}
        )
        assert retry_after is None
        assert quota == "RESOURCE_EXHAUSTED"

    def test_a_named_quota_beats_the_fallback(self):
        """And a violation that names nothing must not shadow one that does."""
        from app.services.gemini import _quota_hint

        _, quota = _quota_hint(
            {
                "error": {
                    "status": "RESOURCE_EXHAUSTED",
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                            "violations": [
                                {"subject": "project:1"},
                                {"quotaId": "GenerateRequestsPerDayPerProjectPerModel"},
                            ],
                        }
                    ],
                }
            }
        )
        assert quota == "GenerateRequestsPerDayPerProjectPerModel"

    def test_a_spend_cap_is_not_a_rate_limit(self):
        """The two arrive identically and want opposite responses.

        Measured against the live API: Google answers `429
        RESOURCE_EXHAUSTED` both for "too many requests" and for "this project
        has exceeded its monthly spending cap". With the message withheld, the
        second read as the first for two days — a research run and a prep
        brief were both waited out, and the cap does not reset on a clock.
        """
        from app.services.gemini import GeminiError, redacted

        message = (
            "Your project has exceeded its monthly spending cap. Please go to "
            "AI Studio at https://ai.studio/spend to manage your project spend cap."
        )
        exc = GeminiError(
            "Gemini returned HTTP 429",
            status_code=429,
            quota="RESOURCE_EXHAUSTED",
            detail=redacted(message),
        )
        assert exc.is_rate_limit
        assert exc.is_spend_cap, "a spend cap must be distinguishable from a rate limit"

        ordinary = GeminiError(
            "Gemini returned HTTP 429",
            status_code=429,
            quota="GenerateRequestsPerMinutePerProject",
            detail=redacted("Quota exceeded for requests per minute."),
        )
        assert ordinary.is_rate_limit
        assert not ordinary.is_spend_cap


class TestRepeatingWhatTheProviderSaid:
    """The message is carried now, because withholding it hid the diagnosis.

    The rule it was withheld under — a rejection can quote the key that was
    sent — is about keys reaching logs, not about refusing to repeat a
    provider's own sentence. Redaction serves that rule; silence only served
    ignorance.
    """

    def test_a_google_key_never_survives(self):
        from app.services.gemini import redacted

        out = redacted(
            "Quota exceeded for key AIzaSyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r on project 42"
        )
        assert "AIza" not in out
        assert "[redacted]" in out
        # And the part worth reading survives.
        assert "Quota exceeded" in out and "project 42" in out

    def test_a_bearer_token_never_survives(self):
        from app.services.gemini import redacted

        out = redacted("Unauthorized: bearer sk-abcdefghijklmnopqrstuvwxyz0123456789")
        assert "sk-abcdefghij" not in out
        assert "Unauthorized" in out

    def test_any_long_opaque_run_is_removed(self):
        """Not every secret announces itself with a prefix."""
        from app.services.gemini import redacted

        out = redacted("Rejected credential ZmFrZXNlY3JldGZha2VzZWNyZXRmYWtlc2VjcmV0MTIzNDU2")
        assert "ZmFrZXNlY3JldGZha2V" not in out

    def test_an_absent_message_stays_absent(self):
        from app.services.gemini import redacted

        assert redacted(None) is None
        assert redacted("") is None

    def test_a_long_message_is_cut_rather_than_carried_whole(self):
        """An error line is for reading, not for pasting a page into a log."""
        from app.services.gemini import redacted

        prose = "Quota exceeded for this project and policy. " * 60
        assert len(redacted(prose)) == 300
