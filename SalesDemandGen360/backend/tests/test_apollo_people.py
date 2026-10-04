"""Search-first enrichment, without a network or a database.

Payload shapes are trimmed copies of live responses: the People API Search
result for bluewave.net (Seth, `Founder & CEO`), and a `people/bulk_match`
body as Apollo's reference documents it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import apollo_people, company_check, contact_suggestions
from app.services.apollo_people import Found
from app.services.company_check import Option, Website
from app.services.contact_suggestions import PersonaQuery

SEARCH = {
    "total_entries": 2,
    "people": [
        {
            "id": "66f1a0c2e1",
            "first_name": "Seth",
            "last_name_obfuscated": "Pe***d",
            "title": "Founder & CEO",
            "last_refreshed_at": "2026-08-01T10:00:00.000+00:00",
            "has_email": True,
            "has_city": True,
            "has_state": True,
            "has_country": True,
            "has_direct_phone": "Yes",
            "organization": {"name": "BlueWave", "has_industry": True},
        },
        {"first_name": "No id", "title": "CTO"},
    ],
}


class TestReadingTheSearch:
    def test_people_are_read_without_anything_that_identifies_them(self):
        [seth] = apollo_people.parse_search(SEARCH)
        assert seth.apollo_id == "66f1a0c2e1"
        assert (seth.first_name, seth.last_name_hint, seth.title) == ("Seth", "Pe***d", "Founder & CEO")
        assert seth.has_email and seth.has_location and seth.has_direct_phone
        assert seth.refreshed_at.year == 2026

    @pytest.mark.parametrize("payload", [None, {}, {"people": "nope"}, []])
    def test_an_odd_body_is_nobody(self, payload):
        assert apollo_people.parse_search(payload) == []


class TestReadingTheReveal:
    def test_matches_are_filed_under_their_own_id(self):
        payload = {"matches": [{"id": "b", "name": "Bea"}, {"id": "a", "name": "Al"}], "credits_consumed": 2}
        found, credits = apollo_people.parse_reveal(["a", "b"], payload)
        assert found["a"]["name"] == "Al" and found["b"]["name"] == "Bea"
        assert credits == 2

    def test_nobody_found_is_a_null_in_its_place(self):
        found, credits = apollo_people.parse_reveal(["a", "b"], {"matches": [None, {"id": "b"}]})
        assert list(found) == ["b"]
        assert credits is None

    def test_an_id_nobody_asked_about_is_not_filed_anywhere(self):
        found, _ = apollo_people.parse_reveal(["a"], {"matches": [{"id": "zzz", "name": "Stranger"}]})
        assert found == {}


class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class FakeHttp:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def post(self, url, *, headers, json=None, params=None):
        self.calls.append({"url": url, "json": json, "params": params, "headers": headers})
        return self.responses.pop(0)


class TestTheClient:
    async def test_search_is_one_domain_with_similar_titles(self):
        http = FakeHttp([FakeResponse(200, SEARCH)])
        people = apollo_people.ApolloPeople("k", client_factory=lambda: http)
        found = await people.search(domain="bluewave.net", titles=("CEO",), per_page=500)
        body = http.calls[0]["json"]
        assert http.calls[0]["url"].endswith("/mixed_people/api_search")
        assert body["q_organization_domains_list"] == ["bluewave.net"]
        assert body["person_titles"] == ["CEO"] and body["include_similar_titles"] is True
        assert body["per_page"] == 100, "Apollo's page ceiling"
        assert "person_seniorities" not in body
        assert len(found) == 1

    async def test_reveal_never_asks_for_personal_email_or_phone_and_batches_by_ten(self):
        ids = [f"p{i}" for i in range(12)]
        http = FakeHttp([
            FakeResponse(200, {"matches": [{"id": i} for i in ids[:10]], "credits_consumed": 10}),
            FakeResponse(200, {"matches": [{"id": "p10"}, None]}),
        ])
        people = apollo_people.ApolloPeople("k", client_factory=lambda: http)
        found, credits = await people.reveal(ids)
        assert [len(c["json"]["details"]) for c in http.calls] == [10, 2]
        for call in http.calls:
            assert call["json"]["reveal_personal_emails"] is False
            assert call["json"]["reveal_phone_number"] is False
        assert len(found) == 11 and credits == 11

    async def test_a_rejected_key_says_so_without_the_body(self):
        from app.services.providers import ProviderError

        http = FakeHttp([FakeResponse(403, {"error": "key sk-secret is not allowed"})])
        people = apollo_people.ApolloPeople("sk-secret", client_factory=lambda: http)
        with pytest.raises(ProviderError) as err:
            await people.search(domain="x.com", titles=("CEO",))
        assert "sk-secret" not in str(err.value)

    async def test_an_organisation_apollo_does_not_know_is_none(self):
        http = FakeHttp([FakeResponse(404, {})])
        people = apollo_people.ApolloPeople("k", client_factory=lambda: http)
        assert await people.organization("gone.example") is None
        assert http.calls[0]["params"] == {"domain": "gone.example"}


class TestPersonaQueries:
    def test_titles_search_by_title_and_a_bare_role_by_seniority(self):
        queries, skipped = contact_suggestions.persona_queries({
            "personas": [
                {"buying_role": "technical_buyer", "titles": ["CTO", "IT head"]},
                {"buying_role": "economic_buyer", "titles": []},
                {"buying_role": "blocker", "titles": []},
            ]
        })
        assert queries[0] == PersonaQuery("technical buyer", "technical_buyer", ("CTO", "IT head"), ())
        assert queries[1].seniorities == ("owner", "founder", "c_suite", "partner")
        assert skipped == ["blocker"], "no titles and no seniority to search on"

    def test_the_same_persona_in_two_icps_is_searched_once(self):
        icp = {"personas": [{"buying_role": "economic_buyer", "titles": ["CEO"]}]}
        queries, _ = contact_suggestions.persona_queries(icp, icp)
        assert len(queries) == 1

    def test_an_older_bare_string_role_is_read_as_a_role(self):
        queries, _ = contact_suggestions.persona_queries({"personas": ["economic_buyer"]})
        assert queries[0].buying_role == "economic_buyer" and queries[0].seniorities


def found(**kw) -> Found:
    base = dict(
        apollo_id="p1", first_name="Seth", last_name_hint="Pe***d", title="Founder & CEO",
        has_email=True, has_location=True, has_direct_phone=False, refreshed_at=None,
    )
    base.update(kw)
    return Found(**base)


class TestWhoIsAlreadyOnTheList:
    @pytest.mark.parametrize(
        ("last", "hint", "fits"),
        [
            ("Penland", "Pe***d", True),
            ("Burke", "Pe***d", False),
            ("Pe", "Pe***d", False),
            ("Núñez", "Nu***z", True),
            ("Lee", "Lee", True),
            ("Lee", "***", False),
        ],
    )
    def test_the_visible_letters_of_the_surname(self, last, hint, fits):
        assert contact_suggestions.last_name_fits(last, hint) is fits

    def contact(self, name, **kw):
        return SimpleNamespace(id=name, full_name=name, apollo_person_id=kw.get("apollo"))

    def test_by_first_name_and_surname_hint(self):
        seth = self.contact("Seth Penland")
        assert contact_suggestions.match_contact(found(), [self.contact("Kevin Burke"), seth]) is seth

    def test_by_apollo_id_whatever_the_name(self):
        renamed = self.contact("S. Penland-Rivera", apollo="p1")
        assert contact_suggestions.match_contact(found(), [renamed]) is renamed

    def test_two_people_who_fit_are_neither(self):
        twins = [self.contact("Seth Penland"), self.contact("Seth Pennyfeld")]
        assert contact_suggestions.match_contact(found(), twins) is None


class TestFitsThePersona:
    QUERY = PersonaQuery("economic buyer", "economic_buyer", ("CEO", "CTO"), ())

    @pytest.mark.parametrize(
        ("title", "fits"),
        [
            ("Founder & CEO", True),
            ("Chief Executive Officer", True),
            # Live on apollo.io: similar titles returns this for a CEO search.
            ("Chief of Staff to the CEO", False),
            ("Executive Assistant to the CEO", False),
            ("Senior Technology Advisor", False),
            (None, False),
        ],
    )
    def test_titles_are_read_again(self, title, fits):
        assert contact_suggestions.fits(found(title=title), self.QUERY) is fits

    @pytest.mark.parametrize(
        ("title", "fits"),
        [
            ("Owner", True),
            ("President", True),
            # Live at BlueWave, found by seniority and read on rank alone.
            ("Chief Legal Officer", False),
            ("FP&A Director", False),
            ("Vice President, Controller", False),
            ("SVP Corporate Development", False),
        ],
    )
    def test_a_result_found_by_seniority_must_name_the_job(self, title, fits):
        assert contact_suggestions.fits(found(title=title), self.QUERY, strict=True) is fits

    def test_a_seniority_search_takes_apollos_word_for_rank(self):
        query = PersonaQuery("economic buyer", "economic_buyer", (), ("owner",))
        assert contact_suggestions.fits(found(title="Owner"), query) is True


class TestTheCompanyCheck:
    APOLLO = {
        "found": True, "name": "BlueWave", "domain": "bluewave.net", "country": "United States",
        "state": "Georgia", "linkedin_url": "https://linkedin.com/company/bluewavetg",
    }
    EMPTY = {"hq_country": None, "hq_region": None, "linkedin_url": None}

    def test_what_agrees_is_filled(self):
        site = Website(True, company_pages=["https://www.linkedin.com/company/bluewavetg/"])
        d = company_check.decide("bluewave.net", self.EMPTY, site, self.APOLLO)
        assert d.fills == {
            "hq_country": Option("United States", "apollo"),
            "hq_region": Option("Georgia", "apollo"),
            "linkedin_url": Option("https://linkedin.com/company/bluewavetg", "website and apollo"),
        }
        assert d.conflicts == []

    def test_two_pages_on_the_site_are_settled_by_apollo(self):
        site = Website(True, company_pages=[
            "https://linkedin.com/company/bluewave", "https://linkedin.com/company/bluewavetg",
        ])
        d = company_check.decide("bluewave.net", self.EMPTY, site, self.APOLLO)
        assert d.fills["linkedin_url"].value == "https://linkedin.com/company/bluewavetg"

    def test_two_pages_and_no_apollo_are_a_question(self):
        site = Website(True, company_pages=[
            "https://linkedin.com/company/bluewave", "https://linkedin.com/company/bluewavetg",
        ])
        d = company_check.decide("bluewave.net", self.EMPTY, site, None)
        [conflict] = d.conflicts
        assert conflict.field == "linkedin_url" and len(conflict.options) == 2
        assert "linkedin_url" not in d.fills

    def test_a_redirect_is_a_question_about_the_domain(self):
        site = Website(True, redirects_to="argylesg.com")
        d = company_check.decide("vanguardtech.com", self.EMPTY, site, None)
        [conflict] = d.conflicts
        assert conflict.field == "domain"
        assert conflict.options == [Option("argylesg.com", "website redirect")]

    def test_apollo_filed_under_another_domain_is_not_used_for_country(self):
        parent = {**self.APOLLO, "domain": "bluewave-holdings.com", "country": "Canada"}
        d = company_check.decide("bluewave.net", self.EMPTY, Website(True), parent)
        assert "hq_country" not in d.fills
        assert d.conflicts[0].field == "domain"

    def test_a_different_country_on_record_is_asked_not_overwritten(self):
        d = company_check.decide(
            "zenithcp.com", {**self.EMPTY, "hq_country": "USA"}, Website(True),
            {**self.APOLLO, "domain": "zenithcp.com", "country": "China"},
        )
        assert "hq_country" not in d.fills
        assert d.conflicts[0].field == "hq_country"

    def test_the_same_country_spelled_differently_is_not_a_conflict(self):
        d = company_check.decide(
            "bluewave.net", {**self.EMPTY, "hq_country": "USA"}, Website(True), self.APOLLO
        )
        assert not [c for c in d.conflicts if c.field == "hq_country"]

    def test_a_dead_site_is_said(self):
        d = company_check.decide("gone.example", self.EMPTY, Website(False), None)
        assert d.conflicts[0].field == "domain" and "does not answer" in d.conflicts[0].note

    def test_a_settled_answer_is_not_asked_again(self):
        d = company_check.decide(
            "gone.example", self.EMPTY, Website(False), None, settled={"domain": "gone.example"}
        )
        assert d.conflicts == []

    def test_settling_uses_the_value_and_remembers_it(self):
        account = SimpleNamespace(
            domain="bluewave.net", linkedin_url=None, hq_country=None,
            company_check={"conflicts": [{"field": "linkedin_url", "current": None, "options": [], "note": ""}]},
        )
        company_check.settle(account, "linkedin_url", "https://www.linkedin.com/company/bluewavetg/")
        assert account.linkedin_url == "https://linkedin.com/company/bluewavetg"
        assert account.company_check["conflicts"] == []
        assert account.company_check["settled"][0]["value"] == account.linkedin_url

    @pytest.mark.parametrize(
        ("field", "value"),
        [("linkedin_url", "https://www.linkedin.com/in/seth-penland"), ("domain", "BlueWave"), ("industry", "x")],
    )
    def test_settling_refuses_the_wrong_kind_of_value(self, field, value):
        account = SimpleNamespace(domain="bluewave.net", linkedin_url=None, hq_country=None, company_check={})
        with pytest.raises(ValueError):
            company_check.settle(account, field, value)


class TestApolloSaysWhy:
    async def test_no_credits_is_said_plainly_and_nothing_else_leaks(self):
        """Live: a reveal answered 422 and the screen said only "HTTP 422"."""
        from app.services.providers import ProviderError

        body = {"error": "You have insufficient credits! <a href='https://app.apollo.io'>Upgrade your plan</a> sk-secret"}
        http = FakeHttp([FakeResponse(422, body)])
        people = apollo_people.ApolloPeople("sk-secret", client_factory=lambda: http)
        with pytest.raises(ProviderError) as err:
            await people.reveal(["p1"])
        said = str(err.value)
        assert "no credits left" in said and "nothing was revealed or charged" in said
        assert "sk-secret" not in said and "<a" not in said

    async def test_another_refusal_carries_apollos_words_without_markup_or_key(self):
        from app.services.providers import ProviderError

        http = FakeHttp([FakeResponse(422, {"error": "Invalid <b>details</b> for sk-secret"})])
        people = apollo_people.ApolloPeople("sk-secret", client_factory=lambda: http)
        with pytest.raises(ProviderError) as err:
            await people.search(domain="x.com", titles=("CEO",))
        said = str(err.value)
        assert "Invalid details for ***" in said and "sk-secret" not in said and "<b>" not in said


class TestSpendingTheCreditsThatAreLeft:
    async def test_a_batch_refused_for_credits_is_retried_one_at_a_time(self):
        """Live: ten people against seven credits revealed nobody."""
        from app.services.apollo_people import OutOfCredits

        no_credits = FakeResponse(422, {"error": "You have insufficient credits!"})
        http = FakeHttp([
            no_credits,
            FakeResponse(200, {"matches": [{"id": "p0"}], "credits_consumed": 1}),
            FakeResponse(200, {"matches": [{"id": "p1"}], "credits_consumed": 1}),
            no_credits,
        ])
        people = apollo_people.ApolloPeople("k", client_factory=lambda: http)
        with pytest.raises(OutOfCredits) as err:
            await people.reveal(["p0", "p1", "p2"])
        assert set(err.value.revealed) == {"p0", "p1"} and err.value.credits == 2
        assert [len(c["json"]["details"]) for c in http.calls] == [3, 1, 1, 1]

    async def test_enough_credits_is_one_call_per_ten(self):
        http = FakeHttp([FakeResponse(200, {"matches": [{"id": "a"}, {"id": "b"}], "credits_consumed": 2})])
        people = apollo_people.ApolloPeople("k", client_factory=lambda: http)
        found, credits = await people.reveal(["a", "b"])
        assert set(found) == {"a", "b"} and credits == 2 and len(http.calls) == 1
