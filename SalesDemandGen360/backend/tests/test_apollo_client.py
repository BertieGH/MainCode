"""Apollo's response, read the way Apollo means it.

The mapping under test is not "did we find the field" — it is "did we keep the
provider's own confidence". Apollo returns guessed addresses next to confirmed
ones and labels which is which. Every test here is about that label surviving
the trip into a contact row, because the one place it must not be lost is the
gate that decides whether an address is safe to send to.

Payloads are trimmed copies of a real `POST /api/v1/people/match` response.
"""

from __future__ import annotations

import pytest

from app.services.enrichment_clients import (
    APOLLO_LOCKED_EMAIL,
    ApolloProvider,
    _split_name,
)
from app.services.providers import ContactRecord, Provider, ProviderError, enrich


def person(**overrides):
    """A match response, shaped like the live one."""
    body = {
        "name": "Shannon M",
        "title": "Technical Recruiter",
        "seniority": "entry",
        "email": "someone@example.com",
        "email_status": "verified",
        "linkedin_url": None,
        "departments": ["master_human_resources"],
        "organization": {"name": "Example", "primary_domain": "example.com"},
    }
    body.update(overrides)
    return {"person": body}


def echoed_person(name="Nobody Whoisnotreal"):
    """What Apollo returns for a name it has never seen.

    Copied from a live response. Every field here came out of our own request
    or was resolved from the domain — note that `id` and `organization` are
    both present, which is exactly why neither can be used as proof of a match.
    """
    first, _, last = name.partition(" ")
    return {
        "person": {
            "id": "6a9e60aac85764001c11fda8",
            "name": name,
            "first_name": first,
            "last_name": last,
            "title": None,
            "seniority": None,
            "email": None,
            "email_status": None,
            "linkedin_url": None,
            "photo_url": None,
            "headline": None,
            "city": None,
            "departments": [],
            "organization_id": "556d2055736964126c4f9600",
            "organization": {"name": "Example", "primary_domain": "example.com"},
        }
    }


class StubResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class StubClient:
    """Stands in for httpx, and records what was sent."""

    def __init__(self, response: StubResponse | Exception):
        self._response = response
        self.calls: list[tuple[str, dict, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, *, headers, json):
        self.calls.append((url, headers, json))
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


@pytest.fixture
def patched(monkeypatch):
    """Swap the module's client factory for a stub, and hand it back."""

    def _install(response):
        stub = StubClient(response)
        monkeypatch.setattr(
            "app.services.enrichment_clients._client", lambda *a, **k: stub
        )
        return stub

    return _install


class TestGradeSurvives:
    @pytest.mark.asyncio
    async def test_a_verified_address_stays_verified(self, patched):
        patched(StubResponse(200, person(email_status="verified")))
        record = await ApolloProvider("k").enrich(
            full_name="Shannon M", company_domain="example.com", linkedin_url=None
        )
        assert record.email == "someone@example.com"
        assert record.email_status == "verified"

    @pytest.mark.asyncio
    async def test_a_guess_is_risky_not_verified(self, patched):
        """The whole reason `email_status` exists on `ContactRecord`.

        Before this, any address a provider returned was written as verified.
        An Apollo guess is a pattern applied to a name — plausible, unconfirmed,
        and charged to the sending domain when it is wrong.
        """
        patched(StubResponse(200, person(email_status="guessed")))
        record = await ApolloProvider("k").enrich(
            full_name="Shannon M", company_domain="example.com", linkedin_url=None
        )
        assert record.email == "someone@example.com"
        assert record.email_status == "risky"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("raw", ["unavailable", "bounced"])
    async def test_a_dead_address_is_invalid(self, patched, raw):
        patched(StubResponse(200, person(email_status=raw)))
        record = await ApolloProvider("k").enrich(
            full_name="Shannon M", company_domain="example.com", linkedin_url=None
        )
        assert record.email_status == "invalid"

    @pytest.mark.asyncio
    async def test_an_unknown_grade_falls_to_unverified_and_is_logged(
        self, patched, caplog
    ):
        """Apollo may add a grade tomorrow. The cautious side is the default."""
        patched(StubResponse(200, person(email_status="brand_new_grade")))
        with caplog.at_level("WARNING"):
            record = await ApolloProvider("k").enrich(
                full_name="Shannon M", company_domain="example.com", linkedin_url=None
            )
        assert record.email_status == "unverified"
        assert "unmapped_email_status" in caplog.text

    @pytest.mark.asyncio
    async def test_no_grade_at_all_is_unverified(self, patched):
        """What the live call actually returned when handed a known address."""
        patched(StubResponse(200, person(email_status=None)))
        record = await ApolloProvider("k").enrich(
            full_name="Shannon M", company_domain="example.com", linkedin_url=None
        )
        assert record.email_status == "unverified"


class TestApolloCannotSayNo:
    """`people/match` answers 200 with a person for a name it invented.

    This is the failure that would not have shown up in any stub test written
    from the documentation, and it is silent: a list of names Apollo has never
    heard of would import, "enrich", and report a clean pass.
    """

    @pytest.mark.asyncio
    async def test_an_echoed_person_is_not_a_match(self, patched):
        patched(StubResponse(200, echoed_person()))
        record = await ApolloProvider("k").enrich(
            full_name="Nobody Whoisnotreal",
            company_domain="example.com",
            linkedin_url=None,
        )
        assert record is None

    @pytest.mark.asyncio
    async def test_an_organisation_is_not_proof_of_a_person(self, patched):
        """The org is resolved from the domain, so it is present either way."""
        payload = echoed_person()
        assert payload["person"]["organization"] is not None
        assert payload["person"]["id"]
        patched(StubResponse(200, payload))
        record = await ApolloProvider("k").enrich(
            full_name="Nobody Whoisnotreal",
            company_domain="example.com",
            linkedin_url=None,
        )
        assert record is None, "an id and an org were read as a person"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "field,value",
        [
            ("title", "Chairman and CEO"),
            ("seniority", "c_suite"),
            ("email", "someone@example.com"),
            ("linkedin_url", "https://www.linkedin.com/in/someone"),
            ("headline", "Chairman and CEO at Example"),
        ],
    )
    async def test_one_thing_apollo_could_only_know_makes_it_a_match(
        self, patched, field, value
    ):
        payload = echoed_person()
        payload["person"][field] = value
        patched(StubResponse(200, payload))
        record = await ApolloProvider("k").enrich(
            full_name="Nobody Whoisnotreal",
            company_domain="example.com",
            linkedin_url=None,
        )
        assert record is not None

    @pytest.mark.asyncio
    async def test_a_known_person_with_no_address_is_still_a_match(self, patched):
        """Found, unreachable, and worth recording as found.

        Apollo knows the title and seniority; it has no email. That is a real
        result — the title feeds qualification — and it must not be confused
        with "this person does not exist".
        """
        payload = echoed_person("Dana Reid")
        payload["person"]["title"] = "Head of Operations"
        payload["person"]["seniority"] = "director"
        patched(StubResponse(200, payload))
        record = await ApolloProvider("k").enrich(
            full_name="Dana Reid", company_domain="example.com", linkedin_url=None
        )
        assert record is not None
        assert record.title == "Head of Operations"
        assert record.email is None
        assert record.email_status == "unverified"


class TestLockedEmail:
    @pytest.mark.asyncio
    async def test_the_placeholder_never_becomes_a_contact_address(self, patched):
        """Apollo's paywall marker is a literal string, not an address.

        Stored unchecked, an import of two hundred people produces two hundred
        contacts sharing one fake address — and every one of them looks
        enriched.
        """
        patched(
            StubResponse(200, person(email=APOLLO_LOCKED_EMAIL, email_status="verified"))
        )
        record = await ApolloProvider("k").enrich(
            full_name="Shannon M", company_domain="example.com", linkedin_url=None
        )
        assert record.email is None
        assert record.email_status == "unverified"

    @pytest.mark.asyncio
    async def test_an_absent_email_cannot_be_verified(self, patched):
        patched(StubResponse(200, person(email=None, email_status="verified")))
        record = await ApolloProvider("k").enrich(
            full_name="Shannon M", company_domain="example.com", linkedin_url=None
        )
        assert record.email is None
        assert record.email_status == "unverified"


class TestApolloHasNoPhone:
    """Confirmed live, and the near-miss is worse than the gap.

    `reveal_phone_number` returns HTTP 400 without a `webhook_url` — Apollo
    delivers phone results asynchronously — so there is no number to read. The
    response does carry one, at `organization.phone`, and it is the company
    switchboard: Microsoft's came back as +1 800-285-7772. Reading it would give
    every contact at an account the same main line, labelled as their direct
    number, and it would look like the integration was working.
    """

    def test_apollo_does_not_claim_to_supply_a_phone(self):
        assert "phone" not in ApolloProvider("k").supplies

    @pytest.mark.asyncio
    async def test_the_company_switchboard_is_not_read_as_a_contacts_number(
        self, patched
    ):
        payload = person(email_status="verified")
        payload["person"]["organization"] = {
            "name": "Example",
            "primary_domain": "example.com",
            "phone": "+1 800-285-7772",
            "sanitized_phone": "+18002857772",
            "primary_phone": {"number": "+1 800-285-7772"},
        }
        patched(StubResponse(200, payload))

        record = await ApolloProvider("k").enrich(
            full_name="Shannon M", company_domain="example.com", linkedin_url=None
        )

        assert record.phone is None, "the switchboard became a contact's number"

    @pytest.mark.asyncio
    async def test_a_real_personal_number_would_still_be_read(self, patched):
        """The gap is Apollo's, not the parser's — if a number ever arrives on
        the person it is used, in E.164.

        `sanitized_number` wins over `raw_number` deliberately: the sanitized
        form is what a dialler and a deduplication key both want, and the raw
        form's spacing varies by whoever typed it in.
        """
        payload = person()
        payload["person"]["phone_numbers"] = [
            {"raw_number": "+1 555 0100", "sanitized_number": "+15550100"}
        ]
        patched(StubResponse(200, payload))

        record = await ApolloProvider("k").enrich(
            full_name="Shannon M", company_domain="example.com", linkedin_url=None
        )

        assert record.phone == "+15550100"


class TestWhatGetsAsked:
    @pytest.mark.asyncio
    async def test_a_bare_name_is_not_worth_a_credit(self, patched):
        stub = patched(StubResponse(200, person()))
        record = await ApolloProvider("k").enrich(
            full_name="Shannon M", company_domain=None, linkedin_url=None
        )
        assert record is None
        assert stub.calls == [], "asked Apollo about a name with no company"

    @pytest.mark.asyncio
    async def test_the_linkedin_url_is_sent_when_we_have_one(self, patched):
        stub = patched(StubResponse(200, person()))
        await ApolloProvider("k").enrich(
            full_name="Dana Reid",
            company_domain="northwind.example",
            linkedin_url="https://www.linkedin.com/in/danareid",
        )
        _, headers, body = stub.calls[0]
        assert body["linkedin_url"] == "https://www.linkedin.com/in/danareid"
        assert body["first_name"] == "Dana"
        assert body["last_name"] == "Reid"
        assert headers["x-api-key"] == "k"

    @pytest.mark.asyncio
    async def test_personal_emails_are_not_revealed_unless_asked(self, patched):
        """Each reveal is a credit, spent before anyone knows if it is usable."""
        stub = patched(StubResponse(200, person()))
        await ApolloProvider("k").enrich(
            full_name="Dana Reid", company_domain="northwind.example", linkedin_url=None
        )
        assert stub.calls[0][2]["reveal_personal_emails"] is False

    def test_a_multi_part_surname_keeps_its_given_names(self):
        assert _split_name("Maria del Carmen Ruiz") == ("Maria del Carmen", "Ruiz")
        assert _split_name("Cher") == ("Cher", "")


class TestFailuresAreToldApart:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [404, 422])
    async def test_no_match_is_a_finding_not_a_fault(self, patched, status):
        """The waterfall must move to the next provider, not stop.

        A raised error here marks the pass unavailable, and a contact the
        fallback could have resolved is written off instead.
        """
        patched(StubResponse(status))
        record = await ApolloProvider("k").enrich(
            full_name="Dana Reid", company_domain="northwind.example", linkedin_url=None
        )
        assert record is None

    @pytest.mark.asyncio
    async def test_a_200_with_no_person_is_no_match(self, patched):
        patched(StubResponse(200, {"person": None}))
        record = await ApolloProvider("k").enrich(
            full_name="Dana Reid", company_domain="northwind.example", linkedin_url=None
        )
        assert record is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [401, 403, 429, 500])
    async def test_a_real_failure_raises(self, patched, status):
        patched(StubResponse(status))
        with pytest.raises(ProviderError):
            await ApolloProvider("k").enrich(
                full_name="Dana Reid",
                company_domain="northwind.example",
                linkedin_url=None,
            )

    @pytest.mark.asyncio
    async def test_a_rejection_never_quotes_the_key(self, patched):
        """Invariant 9. A 401 body can echo the credential that was sent."""
        patched(StubResponse(401, {"error": "bad key sk-secret-value"}))
        with pytest.raises(ProviderError) as caught:
            await ApolloProvider("sk-secret-value").enrich(
                full_name="Dana Reid",
                company_domain="northwind.example",
                linkedin_url=None,
            )
        assert "sk-secret-value" not in str(caught.value)


class TestThroughTheWaterfall:
    @pytest.mark.asyncio
    async def test_the_fallbacks_grade_travels_with_its_address(self):
        """The merge takes the email from whoever supplied it — and the grade.

        Keeping Apollo's default grade while taking ContactOut's address would
        promote an unverified address on the strength of a field nobody sent.
        """

        class Empty:
            name = Provider.APOLLO

            async def enrich(self, **_):
                return ContactRecord(
                    full_name="Dana Reid", title="Head of Ops", email=None
                )

        class Risky:
            name = Provider.CONTACTOUT

            async def enrich(self, **_):
                return ContactRecord(
                    full_name="Dana Reid",
                    email="dana@northwind.example",
                    email_status="risky",
                )

        outcome = await enrich(
            full_name="Dana Reid",
            company_domain="northwind.example",
            providers=[Empty(), Risky()],
        )
        assert outcome.contact.email == "dana@northwind.example"
        assert outcome.contact.email_status == "risky"
