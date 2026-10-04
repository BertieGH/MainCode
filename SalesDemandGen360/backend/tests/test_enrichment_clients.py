"""The ContactOut client.

Two halves with very different standing, and the tests say which is which.

**The routes and the auth are confirmed** — probed live with a deliberately
invalid key. `/v1/people/linkedin` and `/v1/people/enrich` answer 401, so they
exist; `/v1/people/email`, `/v1/email/decode` and `/v1/verify/email` answer
404, and all three were plausible guesses.

**The response shape is not**, because reading a body needs a working key. That
is the dangerous half: a wrong route fails loudly with a 404, while a wrong
field name returns nothing — or the wrong address, which is a bounce against a
sending domain. So the parser tries several candidate shapes and *reports* an
unrecognised one instead of reading it as "nobody found".
"""

from __future__ import annotations

import pytest

from app.services.enrichment_clients import (
    CONTACTOUT_BASE,
    ContactOutProvider,
    _first_value,
)
from app.services.providers import Provider, ProviderError


class _Response:
    def __init__(self, status_code: int, payload=None, text="{}"):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class TestRoutingByWhatWeKnow:
    """A LinkedIn URL identifies one person; a name and a domain identify
    everyone at a company who shares that name."""

    def test_the_base_url_is_the_confirmed_one(self):
        assert CONTACTOUT_BASE == "https://api.contactout.com/v1"

    def test_the_key_goes_in_a_bare_authorization_header(self):
        # Confirmed by probe: a bearer prefix returns 401 for a good key.
        headers = ContactOutProvider("k")._headers()
        assert headers["authorization"] == "k"
        assert "Bearer" not in headers["authorization"]

    async def test_a_linkedin_url_uses_the_profile_route(self, monkeypatch):
        client = ContactOutProvider("k")
        seen = {}

        async def fake_get(path, *, params):
            seen["path"], seen["params"] = path, params
            return {"profile": {"work_email": "dana@northwind.example"}}

        monkeypatch.setattr(client, "_get", fake_get)
        record = await client.enrich(
            full_name="Dana Reyes",
            company_domain="northwind.example",
            linkedin_url="https://linkedin.com/in/dana-reyes",
        )
        assert seen["path"] == "/people/linkedin"
        assert seen["params"] == {"profile": "https://linkedin.com/in/dana-reyes"}
        assert record.email == "dana@northwind.example"

    async def test_a_name_and_domain_use_the_enrich_route(self, monkeypatch):
        client = ContactOutProvider("k")
        seen = {}

        async def fake_post(path, *, body):
            seen["path"], seen["body"] = path, body
            return {"email": "dana@northwind.example"}

        monkeypatch.setattr(client, "_post", fake_post)
        await client.enrich(
            full_name="Dana Reyes", company_domain="northwind.example", linkedin_url=None
        )
        # GET on this route returns 405 — it is POST-only.
        assert seen["path"] == "/people/enrich"
        assert seen["body"] == {"name": "Dana Reyes", "domain": "northwind.example"}

    async def test_a_bare_name_asks_nobody(self):
        """It identifies nobody, and asking spends a metered call to learn so."""
        client = ContactOutProvider("k")
        assert await client.enrich(
            full_name="Dana Reyes", company_domain=None, linkedin_url=None
        ) is None


class TestReadingAResponse:
    def _client(self):
        return ContactOutProvider("k")

    @pytest.mark.parametrize(
        "payload",
        [
            {"profile": {"work_email": "dana@northwind.example"}},
            {"profile": {"email": "dana@northwind.example"}},
            {"work_email": "dana@northwind.example"},
            {"email": "dana@northwind.example"},
            {"data": {"email": "dana@northwind.example"}},
        ],
    )
    def test_an_email_is_found_at_any_known_shape(self, payload):
        # Several candidates because the shape is unconfirmed — one guess
        # would make a correct key look like an empty database.
        record = self._client()._to_record("Dana Reyes", payload)
        assert record.email == "dana@northwind.example"

    def test_a_list_of_emails_is_reduced_to_one(self):
        record = self._client()._to_record(
            "Dana Reyes", {"profile": {"email": ["dana@northwind.example", "d@x.com"]}}
        )
        assert record.email == "dana@northwind.example"

    def test_an_unrecognised_body_is_reported_not_read_as_empty(self, caplog):
        """The failure mode this design exists for.

        Silently returning None would make a wrong mapping look like a list
        that enriches to nothing, and nothing on screen would say why.
        """
        with caplog.at_level("WARNING"):
            record = self._client()._to_record(
                "Dana Reyes", {"unexpected": {"address": "dana@northwind.example"}}
            )
        assert record is None
        assert "contactout.unrecognised_response" in caplog.text
        # And it names what actually arrived, so the mapping is fixed from
        # evidence rather than from another guess.
        assert "unexpected" in caplog.text

    def test_the_source_is_recorded_on_the_field(self):
        record = self._client()._to_record("Dana Reyes", {"email": "dana@x.com"})
        # Provenance: a bad source has to be traceable later without
        # distrusting every contact on the list.
        assert record.sources["email"] == Provider.CONTACTOUT.value

    def test_an_empty_payload_is_nobody_found(self):
        assert self._client()._to_record("Dana Reyes", None) is None

    def test_first_value_ignores_blanks(self):
        assert _first_value({"a": "   ", "b": "x"}, (("a",), ("b",))) == "x"


class TestStatusHandling:
    def _body(self, status, payload=None):
        return ContactOutProvider("k")._body(_Response(status, payload), "/people/enrich")

    def test_404_on_an_enrichment_route_is_a_finding_not_a_fault(self):
        """Raising would mark the whole pass unavailable and stop the waterfall
        trying the next provider for somebody it might actually have."""
        assert self._body(404) is None

    def test_401_is_a_provider_error(self):
        with pytest.raises(ProviderError, match="rejected this key"):
            self._body(401)

    def test_no_provider_text_is_echoed_back(self):
        """A rejection body can quote the key that was sent."""
        try:
            self._body(401)
        except ProviderError as exc:
            assert "k" not in str(exc).replace("key", "")

    def test_a_rate_limit_is_named(self):
        with pytest.raises(ProviderError, match="rate limit"):
            self._body(429)

    def test_a_server_error_names_the_status(self):
        with pytest.raises(ProviderError, match="503"):
            self._body(503)

    def test_a_non_json_body_is_reported_as_such(self):
        with pytest.raises(ProviderError, match="non-JSON"):
            self._body(200, None)

    def test_a_good_response_comes_back_whole(self):
        assert self._body(200, {"email": "x@y.com"}) == {"email": "x@y.com"}
