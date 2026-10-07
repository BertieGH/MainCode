"""Providers as data, and the guard that keeps that honest.

Making providers addable creates one new way to fail, and it is a quiet one: a
stage can now be pointed at a vendor no code can call. The configuration saves,
shows as active, and looks exactly like a working one — until the first real
call, mid-run, after research has already been paid for.

So the trade is explicit. The *schema* stops caring which providers exist, and
`llm.py` starts caring, by name, before it builds a client. These tests hold
both halves: that an unknown provider is storable, and that running on one is
refused with a message that says what to do.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.config import CredentialIn, LlmConfigIn
from app.services import llm, provider_catalogue


class TestTheCatalogueIsSuggestionsNotAList:
    def test_a_provider_we_do_not_ship_validates(self):
        provider_catalogue.validate("mistral", "mistral-large-3")

    def test_a_typo_for_a_provider_we_do_ship_is_rejected(self):
        """The case worth catching: a real vendor, a model it does not have."""
        with pytest.raises(ValueError, match="does not offer"):
            provider_catalogue.validate("anthropic", "claude-opus-4")

    def test_every_external_provider_says_where_its_keys_come_from(self):
        """The CRM is exempt: it is ours, and there is no console to link to."""
        for provider in provider_catalogue.CATALOGUE:
            if provider.kind == "crm":
                continue
            assert provider.console_url.startswith("https://"), provider.key

    def test_runnable_is_only_where_a_real_adapter_exists(self):
        """Fails the day an adapter lands, which is the point.

        Whoever writes one has to come here and say so, rather than the
        catalogue quietly disagreeing with the code. CRM is the one still
        outstanding — a stub adapter, which is not a client.
        """
        runnable = {p.key for p in provider_catalogue.CATALOGUE if p.runnable}
        # `searlo` joined when `services/linkedin_serp.py` landed — the
        # adapter the `linkedin_index` source is dispatched to.
        assert runnable == {
            "anthropic", "gemini", "contactout", "apollo", "lgm", "searlo",
        }

    def test_verifiable_is_wider_than_runnable(self):
        """The distinction the Gemini case forced.

        A key can be perfectly checkable on a vendor no stage can call. One
        boolean cannot say both, and collapsing them meant Gemini keys could
        not be tested at all. OpenAI is now the provider standing in that gap:
        checkable, and nothing runs on it.
        """
        verifiable = {p.key for p in provider_catalogue.CATALOGUE if p.verifiable}
        # OpenAI stands in the gap: checkable, and nothing runs on it. LGM is
        # now both — its published API gave us a route that authenticates.
        assert verifiable == {
            "anthropic", "openai", "gemini", "contactout", "apollo", "lgm",
            "searlo",
        }
        assert not provider_catalogue.BY_KEY["openai"].runnable
        assert provider_catalogue.BY_KEY["openai"].verifiable

    def test_verifiable_is_derived_from_the_probe_and_cannot_drift(self):
        for provider in provider_catalogue.CATALOGUE:
            if provider.key == "anthropic":
                continue  # probed through the SDK, not a declared HTTP spec
            assert provider.verifiable == (provider.probe is not None), provider.key

    def test_a_model_id_resolves_only_under_its_own_provider(self):
        assert provider_catalogue.model_for("anthropic", "claude-opus-5") is not None
        assert provider_catalogue.model_for("openai", "claude-opus-5") is None


class TestProviderKeysAreShapeChecked:
    @pytest.mark.parametrize("good", ["anthropic", "openai", "gemini", "x-ai", "my_vendor2"])
    def test_a_slug_is_accepted(self, good):
        assert CredentialIn(provider=good, credential_type="api_key", value="x").provider == good

    @pytest.mark.parametrize("bad", ["", "A", "Anthropic", " anthropic", "an thropic", "9lives"])
    def test_anything_else_is_rejected(self, bad):
        """Two providers that look identical in a table is the failure here.

        " anthropic" renders the same as "anthropic" and shares no credential
        with it, so a rep sees one row marked valid and another marked
        untested, for what they believe is one vendor.
        """
        with pytest.raises(ValidationError):
            CredentialIn(provider=bad, credential_type="api_key", value="x")

    def test_an_llm_config_provider_is_shape_checked_too(self):
        with pytest.raises(ValidationError):
            LlmConfigIn(
                scenario="signal_extraction",
                provider="Anthropic",
                model="claude-opus-5",
                effort="medium",
                max_tokens=16000,
                output_contract="SignalBatch",
            )

    def test_the_default_provider_is_anthropic(self):
        cfg = LlmConfigIn(
            scenario="signal_extraction",
            model="claude-opus-5",
            effort="medium",
            max_tokens=16000,
            output_contract="SignalBatch",
        )
        assert cfg.provider == "anthropic"


class TestAStageOnAnUnrunnableProviderRefusesBeforeCalling:
    """The failure that the schema no longer prevents, caught where it belongs."""

    async def test_it_raises_named_for_the_provider(self):
        from app.schemas.draft import FreshnessVerdict
        from app.services.prompt import PromptAssembly, SystemBlock

        config = llm.StageConfig(
            scenario="signal_extraction", provider="openai", model="gpt-5.2"
        )
        with pytest.raises(llm.NoAdapterError) as exc:
            await llm.call_structured(
                config=config,
                prefix=PromptAssembly(blocks=[SystemBlock("s", "x")]),
                user_content="anything",
                output_model=FreshnessVerdict,
            )
        assert exc.value.provider == "openai"
        assert exc.value.scenario == "signal_extraction"
        # The message has to say what to do, not only what went wrong.
        assert "anthropic" in str(exc.value)
        assert "gemini" in str(exc.value)

    async def test_an_added_provider_refuses_the_same_way(self):
        from app.schemas.draft import FreshnessVerdict
        from app.services.prompt import PromptAssembly, SystemBlock

        config = llm.StageConfig(
            scenario="evaluation", provider="mistral", model="mistral-large-3"
        )
        with pytest.raises(llm.NoAdapterError):
            await llm.call_structured(
                config=config,
                prefix=PromptAssembly(blocks=[SystemBlock("s", "x")]),
                user_content="anything",
                output_model=FreshnessVerdict,
            )

    async def test_an_injected_client_bypasses_the_guard(self):
        """Otherwise no test could exercise a stage on a future provider.

        A supplied client *is* the adapter, so there is nothing missing.
        """
        from app.schemas.draft import FreshnessVerdict
        from app.services.prompt import PromptAssembly, SystemBlock
        from tests.test_llm_call_sites import FakeClient

        verdict = FreshnessVerdict(proceed=True)
        result = await llm.call_structured(
            config=llm.StageConfig(scenario="evaluation", provider="gemini"),
            prefix=PromptAssembly(blocks=[SystemBlock("s", "x")]),
            user_content="anything",
            output_model=FreshnessVerdict,
            client=FakeClient(verdict),
        )
        assert result.parsed is verdict

