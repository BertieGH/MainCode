"""API contract tests that need no database.

These assert the shape of the contract — which validation rejects what, and what
a response model is structurally capable of carrying. Behaviour that needs rows
lives in test_versioning.py behind the ``db`` marker.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.config import (
    CredentialIn,
    CredentialOut,
    ProofPointIn,
    SalesRulesIn,
    ScoringConfigIn,
    SignalTypeIn,
)


class TestCredentialsCannotLeak:
    def test_response_model_has_no_field_for_the_value(self):
        """The structural guarantee, not a convention.

        No future endpoint can return a credential by forgetting to strip it,
        because CredentialOut has nowhere to put one.
        """
        fields = set(CredentialOut.model_fields)
        for forbidden in ("value", "value_encrypted", "secret", "api_key", "token"):
            assert forbidden not in fields
        assert "last_four" in fields

    def test_request_model_keeps_the_value_out_of_reprs(self):
        """A ValidationError or a debugger shows the model's repr.

        With repr=False the secret is absent from it.
        """
        payload = CredentialIn(
            provider="anthropic", credential_type="api_key", value="sk-ant-SECRET-1234"
        )
        assert "SECRET" not in repr(payload)

    def test_a_provider_we_do_not_ship_is_accepted(self):
        """Providers are data, not schema.

        Which vendors a business buys from changes on a purchase order, not on
        a deploy. Storing the key is separate from being able to *run* on it —
        that is decided at call time by whether an adapter exists.
        """
        assert CredentialIn(
            provider="hubspot", credential_type="api_key", value="x"
        ).provider == "hubspot"

    @pytest.mark.parametrize("bad", ["", " anthropic", "Anthropic", "an thropic", "1st"])
    def test_a_malformed_provider_key_is_rejected(self, bad):
        """Shape is still checked.

        " anthropic" and "Anthropic" would each become a second provider that
        looks identical in the table and shares no credential with the first.
        """
        with pytest.raises(ValidationError):
            CredentialIn(provider=bad, credential_type="api_key", value="x")

    def test_empty_value_is_rejected(self):
        with pytest.raises(ValidationError):
            CredentialIn(provider="apollo", credential_type="api_key", value="")


class TestScoringConfigValidation:
    def _valid(self, **over):
        base = dict(
            dimension_weights={
                "fit": 20, "opportunity": 20, "buyer": 15,
                "commercial": 15, "intent": 20, "engagement": 10,
            },
            band_cutoffs={"high": 75, "medium": 50},
        )
        return {**base, **over}

    def test_accepts_all_six_dimensions(self):
        assert ScoringConfigIn(**self._valid()).dimension_weights["fit"] == 20

    def test_missing_dimension_is_rejected(self):
        weights = self._valid()["dimension_weights"]
        del weights["engagement"]
        with pytest.raises(ValidationError) as exc:
            ScoringConfigIn(**self._valid(dimension_weights=weights))
        assert "engagement" in str(exc.value)

    def test_unknown_dimension_is_rejected(self):
        """A typo would otherwise create a weight that silently does nothing."""
        weights = {**self._valid()["dimension_weights"], "vibes": 10}
        with pytest.raises(ValidationError) as exc:
            ScoringConfigIn(**self._valid(dimension_weights=weights))
        assert "vibes" in str(exc.value)

    def test_weights_must_total_100(self):
        """A distribution, not six independent knobs.

        20/20/15/15/20/10 and double that rank identically but score
        differently, so priority_threshold and the band cut-offs would silently
        stop meaning what they were set to mean.
        """
        doubled = {k: v * 2 for k, v in self._valid()["dimension_weights"].items()}
        with pytest.raises(ValidationError) as exc:
            ScoringConfigIn(**self._valid(dimension_weights=doubled))
        assert "total 100" in str(exc.value)
        assert "200" in str(exc.value), "the error should name the actual total"

    def test_weights_that_total_100_are_accepted(self):
        assert ScoringConfigIn(**self._valid()).dimension_weights["fit"] == 20

    def test_fractional_weights_totalling_100_are_accepted(self):
        """Rounding must not reject a legitimate split."""
        weights = {
            "fit": 16.7, "opportunity": 16.7, "buyer": 16.6,
            "commercial": 16.7, "intent": 16.7, "engagement": 16.6,
        }
        assert ScoringConfigIn(**self._valid(dimension_weights=weights))

    def test_high_cutoff_below_medium_is_rejected(self):
        """Otherwise every Medium account also clears High, silently."""
        with pytest.raises(ValidationError) as exc:
            ScoringConfigIn(**self._valid(band_cutoffs={"high": 40, "medium": 50}))
        assert "above" in str(exc.value)


class TestSalesRulesValidation:
    def _valid(self, **over):
        base = dict(
            priority_threshold=65,
            persona_weight_threshold=50,
            max_concurrent_threads=2,
            thread_start_offset_days=3,
        )
        return {**base, **over}

    def test_thread_cap_must_be_at_least_one(self):
        with pytest.raises(ValidationError):
            SalesRulesIn(**self._valid(max_concurrent_threads=0))

    def test_sample_rate_must_be_a_proportion(self):
        with pytest.raises(ValidationError):
            SalesRulesIn(**self._valid(sample_rate=1.5))

    def test_sample_rate_of_zero_is_rejected(self):
        """A zero sample rate would accept every clean thread unread."""
        with pytest.raises(ValidationError):
            SalesRulesIn(**self._valid(sample_rate=0))

    def test_non_positive_signal_ttl_is_rejected(self):
        """A zero TTL would expire a signal the moment it is created."""
        with pytest.raises(ValidationError) as exc:
            SalesRulesIn(**self._valid(signal_ttl_days={"funding": 0}))
        assert "funding" in str(exc.value)


class TestProofPointApprovalIsSeparate:
    def test_is_approved_cannot_be_set_on_creation(self):
        """Approval is its own act on its own route.

        If it were settable here, a claim could arrive pre-approved in the
        request that created it — and sign-off is what gates a claim reaching a
        prospect.
        """
        assert "is_approved" not in ProofPointIn.model_fields

        pp = ProofPointIn(kind="case_study", title="T", body="B", is_approved=True)
        assert not hasattr(pp, "is_approved")


class TestSignalTypeValidation:
    def test_key_must_be_snake_case(self):
        with pytest.raises(ValidationError):
            SignalTypeIn(key="Funding Round", label="x", scope="company", default_ttl_days=90)

    def test_scope_must_be_company_or_contact(self):
        """There is deliberately no 'both'."""
        with pytest.raises(ValidationError):
            SignalTypeIn(key="mixed", label="x", scope="both", default_ttl_days=90)

    def test_ttl_must_be_positive(self):
        with pytest.raises(ValidationError):
            SignalTypeIn(key="ok_key", label="x", scope="company", default_ttl_days=0)

    # The registry checks — an unknown source, one from the other scope, and a
    # support-only source on its own — moved to tests/test_research_sources.py
    # when the registry became a table. They need a database now; the guarantee
    # they protect is unchanged, and so is the reason for it.

    def test_no_families_yet_is_allowed(self):
        """A type can be registered before its research family exists."""
        assert SignalTypeIn(
            key="ok_key", label="x", scope="company", default_ttl_days=90
        ).produced_by == []

    def test_valid_contact_type_is_accepted(self):
        st = SignalTypeIn(
            key="role_change", label="New in role", scope="contact",
            default_ttl_days=180, weight=1.45,
        )
        assert st.scope == "contact"
        assert st.weight == 1.45


class TestSignalTypeKind:
    def test_a_type_is_an_event_unless_said_otherwise(self):
        assert SignalTypeIn(key="ok_key", label="x", scope="company", default_ttl_days=90).kind == "event"

    def test_only_event_or_theme(self):
        with pytest.raises(ValidationError):
            SignalTypeIn(key="ok_key", label="x", scope="company", default_ttl_days=90, kind="trend")

    def test_the_response_carries_what_the_screen_edits(self):
        """`search_instruction` and `search_group` were missing from the
        response, so every type showed no extra search whatever was saved."""
        from app.schemas.config import SignalTypeOut

        for field in ("search_instruction", "search_group", "kind"):
            assert field in SignalTypeOut.model_fields
