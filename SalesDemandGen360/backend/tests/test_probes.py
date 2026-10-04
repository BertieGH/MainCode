"""Probe classification: telling a bad key from a stale endpoint.

Three HTTP responses look identical to a naive probe and mean completely
different things to the person reading the result:

* 401 — re-issue the key.
* 404 — the key may be perfectly fine; *our* endpoint moved. Reporting this as
  "invalid" sends someone to rotate a working credential, and the new one
  fails the same way.
* 5xx — nothing is wrong with anything; try again.

Only the first is the credential's fault, and only the first should mark it
invalid. The rest come back `inconclusive`, which the setup gate treats as
"not verified" rather than "broken".
"""

from __future__ import annotations

import pytest

from app.services import probes
from app.services.probes import _classify


class TestClassification:
    @pytest.mark.parametrize("status", [200, 201, 204])
    def test_success_is_valid(self, status):
        result = _classify(status, label="Apollo.io", url="https://x")
        assert result.ok and result.status == "valid"

    @pytest.mark.parametrize("status", [401, 403])
    def test_a_rejection_is_the_key_and_is_conclusive(self, status):
        result = _classify(status, label="Apollo.io", url="https://x")
        assert not result.ok
        assert not result.inconclusive
        assert result.status == "invalid"
        assert "rejected this key" in result.detail

    def test_a_404_blames_us_and_names_the_url(self):
        """The failure that would otherwise burn a working credential."""
        result = _classify(404, label="Apollo.io", url="https://api.apollo.io/health")
        assert not result.ok
        assert result.inconclusive
        assert result.status == "untested"
        assert "https://api.apollo.io/health" in result.detail
        assert "may be" in result.detail

    def test_rate_limiting_proves_reachability(self):
        """A 429 means the credential got far enough to be counted."""
        result = _classify(429, label="ContactOut", url="https://x")
        assert result.ok

    def test_a_server_error_is_inconclusive_not_invalid(self):
        result = _classify(503, label="ContactOut", url="https://x")
        assert not result.ok and result.inconclusive

    def test_a_400_is_our_request_shape_not_their_key(self):
        result = _classify(400, label="ContactOut", url="https://x")
        assert result.inconclusive
        assert "not tested" in result.detail


class TestNoProviderTextIsEchoed:
    """A rejection body can quote the key that was sent — invariant 9.

    These strings are returned by an API endpoint, so nothing from a provider's
    response may pass through them.
    """

    def test_classification_only_uses_our_own_words(self):
        for status in (200, 401, 404, 429, 500, 400):
            detail = _classify(status, label="Apollo.io", url="https://x").detail
            assert "sk-" not in detail

    async def test_an_unexpected_exception_is_reduced_to_its_class(self, monkeypatch):
        import anthropic

        leaked = "sk-ant-SECRET-0000"

        class _Leaky:
            def __init__(self, **_):
                self.messages = self

            async def create(self, **_):
                raise RuntimeError(f"rejected {leaked}")

        monkeypatch.setattr(anthropic, "AsyncAnthropic", _Leaky)
        result = await probes.probe("anthropic", leaked)
        assert leaked not in result.detail


class TestProvidersWithoutALiveCheck:
    async def test_an_unknown_provider_is_inconclusive_not_valid(self):
        """Otherwise adding a provider would unlock the gate on a decrypt."""
        result = await probes.probe("mistral", "whatever")
        assert not result.ok
        assert result.inconclusive
        assert result.status == "untested"

    async def test_the_crm_has_no_probe_and_says_so(self):
        result = await probes.probe("crm", "whatever")
        assert result.status == "untested"
        assert "no live check" in result.detail


class TestTheDeclaredEndpoints:
    """Pinned, so a change to one is deliberate rather than incidental.

    None of these has been confirmed against a real account — outbound TLS to
    these hosts is blocked from the machine this was built on. The pin is not a
    claim that they are correct; it is a tripwire so that when somebody with a
    real account fixes one, the fix is visible in a diff rather than buried.
    """

    EXPECTED = {
        "contactout": "https://api.contactout.com/v1/stats",
        "apollo": "https://api.apollo.io/api/v1/auth/health",
        "openai": "https://api.openai.com/v1/models",
        "gemini": "https://generativelanguage.googleapis.com/v1beta/models",
    }

    @pytest.mark.parametrize("key", sorted(EXPECTED))
    def test_the_url_is_what_the_catalogue_says(self, key):
        from app.services.provider_catalogue import BY_KEY

        assert BY_KEY[key].probe.url == self.EXPECTED[key]

    def test_every_shipped_probe_has_been_run_against_the_live_vendor(self):
        """Flip `live_verified` when you have actually checked, not before.

        A probe marked verified that has never run is worse than one marked
        unverified: it makes the setup gate look trustworthy on a guess. Three
        of these were wrong when first written from documentation — Apollo
        answered 200 for junk, ContactOut's route was POST-only, and Google
        rejects with 400 — so "it came from the docs" is not evidence.
        """
        from app.services.provider_catalogue import CATALOGUE

        unverified = [p.key for p in CATALOGUE if p.probe and not p.probe.live_verified]
        # LGM was the last exception. It held out because no key had been
        # stored here, so nobody had run it — the documentation looking right
        # was never the bar. A real key has since been tested against the live
        # account and `/flow/members` answered 200, so it is honestly true.
        assert unverified == []

    def test_lgm_probes_the_route_its_own_documentation_names(self):
        """It used to ship none: every route we could find answered 404.

        LGM has since published its API. `/flow/members` is the check its
        documentation gives for an API key — it authenticates, reads nothing
        and changes nothing — so the outreach slot is checkable at last. The
        key goes in a header rather than the query string the docs also allow:
        a key in a URL reaches proxy logs and redirects.
        """
        from app.services.provider_catalogue import BY_KEY

        spec = BY_KEY["lgm"].probe
        assert spec is not None and BY_KEY["lgm"].verifiable
        assert spec.url == "https://apiv2.lagrowthmachine.com/flow/members"
        assert spec.method == "GET"
        assert "{key}" in spec.value_template and spec.header == "authorization"

    def test_a_probe_never_uses_a_write_method(self):
        """An auth check must not change anything at the provider."""
        from app.services.provider_catalogue import CATALOGUE

        for provider in CATALOGUE:
            if provider.probe:
                assert provider.probe.method == "GET", provider.key

    def test_gemini_is_sent_its_key_in_googles_own_header(self):
        """A bearer token would 401 a perfectly good Gemini key.

        The worst possible wrong answer: the user is told to re-issue a key
        that was never the problem, and the new one fails identically.
        """
        from app.services.provider_catalogue import BY_KEY

        spec = BY_KEY["gemini"].probe
        assert spec.header == "x-goog-api-key"
        assert spec.value_template == "{key}"

    def test_every_llm_provider_can_at_least_be_checked(self):
        """A key nobody can verify can never satisfy the setup gate.

        Shipping a model vendor with no probe means offering somewhere to paste
        a key and no way to find out whether it works.
        """
        from app.services.provider_catalogue import of_kind

        for provider in of_kind("llm"):
            assert provider.verifiable, provider.key


class TestAnExhaustedAccountIsNotABadKey:
    """The status column and the detail line must not contradict each other.

    "invalid" beside "the key works" is a screen nobody can act on: re-issuing
    the key changes nothing, and the reader has no way to know that.
    """

    async def test_credit_exhaustion_reports_expired_not_invalid(self, monkeypatch):
        import anthropic

        class BadRequestError(Exception):
            pass

        class _Broke:
            def __init__(self, **_):
                self.messages = self

            async def create(self, **_):
                raise BadRequestError(
                    "Error code: 400 - Your credit balance is too low to access "
                    "the Anthropic API."
                )

        monkeypatch.setattr(anthropic, "AsyncAnthropic", _Broke)
        result = await probes.probe("anthropic", "sk-ant-whatever")

        assert result.status == "expired"
        assert result.ok is False, "an unbillable account still cannot run a stage"
        assert "credit balance" in result.detail
        # And it must not tell someone their key is bad.
        assert "rejected" not in result.detail

    def test_expired_does_not_satisfy_a_slot(self):
        """It still blocks. Only the wording changes, not the gate."""
        from app.services.readiness import CredentialState

        assert not CredentialState("anthropic", "Anthropic", "expired").verified


class TestATlsFailureIsNotAnUnreachableProvider:
    """The bug that hid behind "could not reach" for a whole build.

    A corporate TLS-inspecting proxy presents its own certificate. Its root is
    in the OS store and not in certifi's bundle, so certifi-based verification
    fails on exactly the networks this product is sold into — and it failed as
    `ConnectError`, which reads as "the provider is down".
    """

    def test_a_certificate_failure_is_named_as_one(self):
        exc = Exception(
            "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
            "unable to get local issuer certificate"
        )
        result = probes._classify_transport(exc, label="Google Gemini")
        assert result.code == "tls_untrusted"
        assert result.inconclusive
        # It must not say the key is bad, and it must not say the host is down.
        assert "reachable" in result.detail
        assert "certificate" in result.detail

    def test_a_genuine_connection_failure_still_reads_as_one(self):
        result = probes._classify_transport(
            ConnectionError("no route to host"), label="Apollo.io"
        )
        assert result.code == "unreachable"
        assert "could not reach" in result.detail

    def test_probes_verify_against_the_operating_system_store(self):
        """certifi does not contain a corporate proxy root. The OS store does.

        Asserted on the object rather than on behaviour because the failure is
        environmental — this is the line that would silently regress to
        `verify=True` in a refactor and break every enterprise install.
        """
        import ssl

        ctx = probes._verify_context()
        assert isinstance(ctx, ssl.SSLContext), (
            "probes fell back to the bundled roots; on a TLS-inspecting network "
            "every non-Anthropic probe will fail as unreachable"
        )


class TestA200DoesNotAlwaysMeanAuthenticated:
    """Apollo's health route answers 200 for any key at all.

    Verified live: `{"healthy":true,"is_logged_in":false}` with HTTP 200 and a
    deliberately invalid key. A status-only check marked garbage as `valid`,
    which would satisfy the setup gate — the precise failure the gate exists to
    prevent, reached through the gate's own verification step.
    """

    def _spec(self):
        from app.services.provider_catalogue import BY_KEY

        return BY_KEY["apollo"].probe

    def test_a_200_saying_not_signed_in_is_a_rejection(self):
        result = probes._classify(
            200,
            label="Apollo.io",
            url="https://x",
            spec=self._spec(),
            body='{"healthy":true,"is_logged_in":false}',
        )
        assert not result.ok
        assert result.code == "rejected"

    def test_a_200_saying_signed_in_is_accepted(self):
        result = probes._classify(
            200,
            label="Apollo.io",
            url="https://x",
            spec=self._spec(),
            body='{"healthy":true,"is_logged_in":true}',
        )
        assert result.ok

    def test_the_body_is_parsed_not_substring_matched(self):
        """`"is_logged_in":false` contains the field name.

        A substring check would read every rejection as a success — the same
        bug in a slightly better disguise.
        """
        assert not probes._flag_is_true('{"is_logged_in":false}', "is_logged_in")
        assert probes._flag_is_true('{"is_logged_in":true}', "is_logged_in")

    def test_an_unparseable_body_is_not_treated_as_success(self):
        assert not probes._flag_is_true("<html>oops</html>", "is_logged_in")

    def test_a_provider_without_a_success_flag_trusts_its_status(self):
        result = probes._classify(200, label="OpenAI", url="https://x")
        assert result.ok


class TestVendorSpecificRejectionCodes:
    """Google answers 400 for a malformed key, not 401.

    Verified against both a real key (200) and junk (400). Without this the
    probe reports "the key was not tested" for a key that was in fact refused,
    and the reader has no reason to suspect the key.
    """

    def test_gemini_treats_400_as_a_rejection(self):
        from app.services.provider_catalogue import BY_KEY

        result = probes._classify(
            400, label="Google Gemini", url="https://x", spec=BY_KEY["gemini"].probe
        )
        assert result.code == "rejected"

    def test_other_providers_still_read_400_as_our_own_bad_request(self):
        from app.services.provider_catalogue import BY_KEY

        result = probes._classify(
            400, label="OpenAI", url="https://x", spec=BY_KEY["openai"].probe
        )
        assert result.code == "bad_request"
        assert result.inconclusive
