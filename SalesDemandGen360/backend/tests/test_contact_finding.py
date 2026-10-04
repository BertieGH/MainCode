"""Company check, suggested contacts and the reveal, on real rows. Apollo is faked.

The fake stands where `apollo_people.from_credentials` would hand back a
client, so the routes' own decisions — who is searched, what is kept, what is
revealed and written where — are what these observe.
"""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.deps import get_session
from app.main import create_app
from app.services.apollo_people import Found
from app.services.company_check import Website

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"),
]

ICP = {"personas": [{"buying_role": "economic_buyer", "titles": ["CEO"]}]}


def person(pid, first, hint, title):
    return Found(
        apollo_id=pid, first_name=first, last_name_hint=hint, title=title,
        has_email=True, has_location=True, has_direct_phone=False, refreshed_at=None,
    )


class FakePeople:
    def __init__(self):
        self.searched: list[dict] = []
        self.revealed: list[list[str]] = []
        self.orgs: list[str] = []
        self.saved_contacts: list = []
        self.saves: list[list[dict]] = []
        self.save_error: str | None = None
        self.results = [
            person("p1", "Seth", "Pe***d", "Founder & CEO"),
            person("p2", "Amy", "Ro***s", "Chief of Staff to the CEO"),
            person("p3", "Anna", "Gr***y", "CEO"),
            person("p4", "Bob", "Ki***g", "Co-CEO"),
        ]
        self.records = {
            "p1": {
                "id": "p1", "name": "Seth Penland", "title": "Founder & CEO",
                "email": "seth@bluewave.net", "email_status": "verified",
                "linkedin_url": "http://www.linkedin.com/in/seth-penland", "city": "Atlanta",
                "country": "United States",
                "organization": {
                    "primary_domain": "bluewave.net", "country": "United States",
                    "linkedin_url": "http://www.linkedin.com/company/bluewavetg",
                },
            },
            "p3": {
                "id": "p3", "name": "Anna Grey", "title": "CEO", "email": "anna@bluewave.net",
                "email_status": "guessed", "linkedin_url": None, "seniority": "c_suite",
                "organization": {"primary_domain": "bluewave.net"},
            },
        }
        self.org = {
            "name": "BlueWave", "primary_domain": "bluewave.net", "country": "United States",
            "state": "Georgia", "linkedin_url": "https://www.linkedin.com/company/bluewavetg",
        }

    async def search(self, *, domain, titles=(), seniorities=(), per_page=25):
        self.searched.append({"domain": domain, "titles": titles, "per_page": per_page})
        return list(self.results)

    async def reveal(self, ids):
        self.revealed.append(list(ids))
        found = {i: self.records[i] for i in ids if i in self.records}
        return found, len(found)

    async def organization(self, domain):
        self.orgs.append(domain)
        return self.org

    async def find_saved(self, *, keywords, per_page=25):
        wanted = keywords.casefold()
        return [c for c in self.saved_contacts
                if wanted in {(c.organization_name or "").casefold(), (c.email or "").casefold()}]

    async def save_contacts(self, bodies):
        from app.services.apollo_people import SavedContact
        from app.services.providers import ProviderError

        if self.save_error:
            raise ProviderError(self.save_error)
        self.saves.append(list(bodies))
        return [
            SavedContact(
                id=f"saved-{i}", person_id=None, first_name=b.get("first_name"),
                last_name=b.get("last_name"), name=None, email=b.get("email"), email_status=None,
                linkedin_url=b.get("linkedin_url"), title=b.get("title"),
                organization_name=b.get("organization_name"),
            )
            for i, b in enumerate(bodies)
        ]


@pytest.fixture
async def api(monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.models.account import Account, AccountList, AccountListMember, Contact
    from app.models.config import (
        EnrichmentConfig,
        IcpProfile,
        IcpProfileVersion,
        ServiceCatalog,
        service_icp_link,
    )
    from app.services import apollo_people, company_check, readiness

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as seed:
        service = ServiceCatalog(code="eia", name="EIA", description="EIA")
        profile = IcpProfile(name="Default")
        lst = AccountList(label="apollo", source="csv", created_by="tests")
        bluewave = Account(name="BlueWave", domain="bluewave.net", resolution_status="resolved")
        unconfirmed = Account(name="Never Looked", domain="never.example", resolution_status="unresolved")
        seed.add_all([service, profile, lst, bluewave, unconfirmed])
        await seed.flush()
        seed.add(IcpProfileVersion(icp_profile_id=profile.id, definition=ICP, version=1, is_active=True))
        await seed.execute(service_icp_link.insert().values(service_id=service.id, icp_profile_id=profile.id))
        seed.add_all([
            AccountListMember(list_id=lst.id, account_id=bluewave.id),
            AccountListMember(list_id=lst.id, account_id=unconfirmed.id),
            EnrichmentConfig(provider_order=["apollo"], suggestions_per_persona=2, version=1, is_active=True),
        ])
        seth = Contact(account_id=bluewave.id, full_name="Seth Penland", title="Founder & CEO")
        seed.add(seth)
        await seed.commit()
        ids = {"list": lst.id, "service": service.id, "bluewave": bluewave.id, "seth": seth.id,
               "profile": profile.id}

    fake = FakePeople()

    async def credentials(session):
        return fake

    async def ready(*a, **k):
        return None

    monkeypatch.setattr(apollo_people, "from_credentials", credentials)
    monkeypatch.setattr(readiness, "require_ready", ready)

    app = create_app()

    async def _session():
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.ids = ids  # type: ignore[attr-defined]
        c.maker = maker  # type: ignore[attr-defined]
        c.fake = fake  # type: ignore[attr-defined]
        c.monkeypatch = monkeypatch  # type: ignore[attr-defined]
        c.company_check = company_check  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


async def find(api):
    return await api.post(
        f"/api/lists/{api.ids['list']}/find-contacts", params={"service_id": str(api.ids["service"])}
    )


async def suggestions(api, *status):
    params = {"status": list(status)} if status else None
    response = await api.get(f"/api/lists/{api.ids['list']}/suggestions", params=params)
    assert response.status_code == 200, response.text
    return {s["first_name"]: s for s in response.json()}


class TestFindingPeople:
    async def test_confirmed_accounts_only_capped_per_persona_and_titles_read_again(self, api):
        response = await find(api)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ran"] and body["per_persona"] == 2
        assert [s["domain"] for s in api.fake.searched] == ["bluewave.net"]
        assert api.fake.searched[0]["titles"] == ("CEO",)
        assert (body["proposed"], body["on_list"], body["filtered"]) == (2, 1, 1)

        rows = await suggestions(api)
        assert set(rows) == {"Seth", "Anna"}, "the chief of staff is filtered, Bob is past the cap"
        assert rows["Seth"]["contact_name"] == "Seth Penland"
        assert rows["Anna"]["contact_name"] is None
        assert rows["Seth"]["last_name_hint"] == "Pe***d"

    async def test_when_titles_leave_room_the_roles_seniorities_are_searched_too(self, api):
        """Live at apexsoftware.com: the senior people are an Owner and a
        President, and a CEO title search returned neither."""
        calls = []

        async def search(*, domain, titles=(), seniorities=(), per_page=25):
            calls.append((titles, seniorities))
            if titles:
                return []
            return [person("o1", "Olga", "Ow***r", "Owner"), person("o2", "Vic", "Pr***t", "VP of Sales")]

        api.fake.search = search
        body = (await find(api)).json()
        assert calls == [(("CEO",), ()), ((), ("owner", "founder", "c_suite", "partner"))]
        assert (body["proposed"], body["filtered"], body["searches"]) == (1, 1, 2)
        assert set(await suggestions(api)) == {"Olga"}, "a VP of Sales does not run the company"

    async def test_a_re_search_drops_undecided_suggestions_it_no_longer_keeps(self, api):
        await find(api)
        api.fake.results = [person("p1", "Seth", "Pe***d", "Founder & CEO")]
        body = (await find(api)).json()
        assert body["dropped"] == 1
        assert set(await suggestions(api)) == {"Seth"}

    async def test_a_second_search_refreshes_and_leaves_decisions_alone(self, api):
        await find(api)
        rows = await suggestions(api)
        await api.post(
            f"/api/lists/{api.ids['list']}/suggestions/decide",
            json={"ids": [rows["Anna"]["id"]], "status": "rejected"},
        )
        body = (await find(api)).json()
        assert (body["proposed"], body["refreshed"], body["already_decided"]) == (0, 1, 1)
        assert (await suggestions(api))["Anna"]["status"] == "rejected"

    async def test_no_key_is_a_search_that_did_not_run(self, api):
        from app.services import apollo_people

        async def none(session):
            return None

        api.monkeypatch.setattr(apollo_people, "from_credentials", none)
        body = (await find(api)).json()
        assert body["ran"] is False and "Apollo key" in body["blocked"]

    async def test_an_icp_with_no_personas_is_refused(self, api):
        from sqlalchemy import update

        from app.models.config import IcpProfileVersion

        async with api.maker() as s:
            await s.execute(update(IcpProfileVersion).values(definition={}))
            await s.commit()
        response = await find(api)
        assert response.status_code == 409


class TestRevealing:
    async def test_only_accepted_people_are_revealed_and_written_onto_contacts(self, api):
        from app.models.account import Account, Contact, ContactSuggestion

        await find(api)
        rows = await suggestions(api)
        decide = await api.post(
            f"/api/lists/{api.ids['list']}/suggestions/decide",
            json={"ids": [rows["Seth"]["id"]], "status": "accepted"},
        )
        assert decide.json() == {"changed": 1}

        response = await api.post(f"/api/lists/{api.ids['list']}/suggestions/reveal")
        assert response.status_code == 200, response.text
        body = response.json()
        assert api.fake.revealed == [["p1"]], "Anna was not accepted"
        assert (body["revealed"], body["updated"], body["created"]) == (1, 1, 0)
        assert (body["verified"], body["linkedin"], body["credits"]) == (1, 1, 1)
        assert (body["company_country"], body["company_linkedin"]) == (1, 1)

        async with api.maker() as s:
            seth = await s.get(Contact, api.ids["seth"])
            assert (seth.email, seth.email_status, seth.email_provider) == (
                "seth@bluewave.net", "verified", "apollo",
            )
            assert seth.linkedin_url == "https://www.linkedin.com/in/seth-penland"
            assert (seth.city, seth.country, seth.apollo_person_id) == ("Atlanta", "United States", "p1")
            assert seth.phone is None
            account = await s.get(Account, api.ids["bluewave"])
            assert account.hq_country == "United States"
            assert account.linkedin_url == "https://linkedin.com/company/bluewavetg"
            statuses = dict(
                (await s.execute(select(ContactSuggestion.first_name, ContactSuggestion.status))).all()
            )
            assert statuses == {"Seth": "revealed", "Anna": "proposed"}

    async def test_a_new_person_is_created_classified_and_graded_by_apollo(self, api):
        from app.models.account import Contact

        await find(api)
        rows = await suggestions(api)
        await api.post(
            f"/api/lists/{api.ids['list']}/suggestions/decide",
            json={"ids": [rows["Anna"]["id"]], "status": "accepted"},
        )
        body = (await api.post(f"/api/lists/{api.ids['list']}/suggestions/reveal")).json()
        assert (body["created"], body["risky"]) == (1, 1)
        async with api.maker() as s:
            anna = (await s.execute(select(Contact).where(Contact.full_name == "Anna Grey"))).scalar_one()
            assert anna.email_status == "risky", "Apollo's guess is not a verified address"
            assert anna.seniority == "c_level" and anna.buying_role == "economic_buyer"

    async def test_nobody_apollo_can_find_is_marked_and_not_charged(self, api):
        await find(api)
        rows = await suggestions(api)
        api.fake.records.clear()
        await api.post(
            f"/api/lists/{api.ids['list']}/suggestions/decide",
            json={"ids": [rows["Seth"]["id"], rows["Anna"]["id"]], "status": "accepted"},
        )
        body = (await api.post(f"/api/lists/{api.ids['list']}/suggestions/reveal")).json()
        assert (body["not_found"], body["credits"]) == (2, 0)
        assert {r["status"] for r in (await suggestions(api)).values()} == {"not_found"}


class TestCheckingTheCompany:
    def website(self, api, site: Website):
        async def read(domain, *, http=None):
            return site

        api.monkeypatch.setattr(api.company_check, "read_website", read)

    async def check(self, api):
        response = await api.post(f"/api/lists/{api.ids['list']}/check-companies")
        assert response.status_code == 200, response.text
        return response.json()

    async def test_what_agrees_is_filled_and_apollo_is_not_paid_twice(self, api):
        self.website(api, Website(True, company_pages=[
            "https://www.linkedin.com/company/bluewave", "https://www.linkedin.com/company/bluewavetg",
        ]))
        body = await self.check(api)
        assert body["checked"] == 1, "only the confirmed account"
        assert (body["filled"], body["conflicts"], body["apollo_credits"]) == (3, 0, 1)
        again = await self.check(api)
        assert again["apollo_credits"] == 0 and api.fake.orgs == ["bluewave.net"]

    async def test_a_conflict_waits_for_a_rep_and_stays_settled(self, api):
        self.website(api, Website(True, redirects_to="argylesg.com"))
        await self.check(api)
        open_ = (await api.get(f"/api/lists/{api.ids['list']}/company-conflicts")).json()
        [account] = open_
        assert [c["field"] for c in account["conflicts"]] == ["domain"]

        settled = await api.post(
            f"/api/accounts/{api.ids['bluewave']}/company-check/settle", json={"field": "domain"}
        )
        assert settled.status_code == 200 and settled.json()["conflicts"] == []
        await self.check(api)
        assert (await api.get(f"/api/lists/{api.ids['list']}/company-conflicts")).json() == []

    async def test_a_domain_another_account_has_is_refused(self, api):
        from app.models.account import Account

        async with api.maker() as s:
            s.add(Account(name="Argyle", domain="argylesg.com", resolution_status="resolved"))
            await s.commit()
        response = await api.post(
            f"/api/accounts/{api.ids['bluewave']}/company-check/settle",
            json={"field": "domain", "value": "argylesg.com"},
        )
        assert response.status_code == 409


class TestTheSetting:
    async def test_suggestions_per_persona_is_versioned_config(self, api):
        saved = await api.put(
            "/api/config/enrichment", json={"provider_order": ["apollo"], "suggestions_per_persona": 7}
        )
        assert saved.status_code == 201, saved.text
        assert saved.json()["suggestions_per_persona"] == 7 and saved.json()["version"] == 2
        refused = await api.put(
            "/api/config/enrichment", json={"provider_order": ["apollo"], "suggestions_per_persona": 0}
        )
        assert refused.status_code == 422


class TestTheLinkedInColumn:
    async def test_a_revealed_person_carries_their_profile(self, api):
        await find(api)
        rows = await suggestions(api)
        await api.post(
            f"/api/lists/{api.ids['list']}/suggestions/decide",
            json={"ids": [rows["Seth"]["id"]], "status": "accepted"},
        )
        await api.post(f"/api/lists/{api.ids['list']}/suggestions/reveal")
        after = await suggestions(api)
        assert after["Seth"]["linkedin_url"] == "https://www.linkedin.com/in/seth-penland"
        assert after["Anna"]["linkedin_url"] is None, "nothing is known before a reveal"


class TestNobodyIsPaidForTwice:
    async def test_a_person_already_revealed_is_not_sent_to_apollo_again(self, api):
        """A reveal writes the Apollo person id onto the contact; a later reveal of
        the same person reads that instead of spending another credit."""
        from sqlalchemy import update

        from app.models.account import Contact

        await find(api)
        async with api.maker() as s:
            await s.execute(
                update(Contact)
                .where(Contact.id == api.ids["seth"])
                .values(apollo_person_id="p1", email="seth@bluewave.net", email_status="verified",
                        email_provider="apollo", linkedin_url="https://www.linkedin.com/in/seth-penland")
            )
            await s.commit()
        rows = await suggestions(api)
        await api.post(
            f"/api/lists/{api.ids['list']}/suggestions/decide",
            json={"ids": [rows["Seth"]["id"], rows["Anna"]["id"]], "status": "accepted"},
        )
        body = (await api.post(f"/api/lists/{api.ids['list']}/suggestions/reveal")).json()
        assert api.fake.revealed == [["p3"]], "Seth was paid for already"
        assert (body["reused"], body["revealed"], body["credits"]) == (1, 2, 1)
        after = await suggestions(api)
        assert after["Seth"]["status"] == "revealed"
        assert "no credit" in after["Seth"]["note"]


class TestSavedInApollo:
    async def accept_and_reveal(self, api, *names):
        await find(api)
        rows = await suggestions(api)
        await api.post(
            f"/api/lists/{api.ids['list']}/suggestions/decide",
            json={"ids": [rows[n]["id"] for n in names], "status": "accepted"},
        )
        response = await api.post(f"/api/lists/{api.ids['list']}/suggestions/reveal")
        assert response.status_code == 200, response.text
        return response.json()

    async def test_revealed_people_are_saved_to_apollo(self, api):
        from app.models.account import Contact

        body = await self.accept_and_reveal(api, "Seth")
        assert (body["saved_to_apollo"], body["save_error"]) == (1, None)
        assert api.fake.saves == [[{
            "first_name": "Seth", "last_name": "Penland", "title": "Founder & CEO",
            "email": "seth@bluewave.net", "organization_name": "BlueWave",
            "linkedin_url": "https://www.linkedin.com/in/seth-penland",
        }]]
        async with api.maker() as s:
            seth = await s.get(Contact, api.ids["seth"])
        assert seth.apollo_contact_id == "saved-0" and seth.apollo_saved_at is not None

    async def test_a_person_saved_in_apollo_is_not_bought(self, api):
        from app.services.apollo_people import SavedContact

        api.fake.saved_contacts = [SavedContact(
            id="c-anna", person_id="p3", first_name="Anna", last_name="Grey", name="Anna Grey",
            email="anna@bluewave.net", email_status="verified", linkedin_url=None, title="CEO",
            organization_name="BlueWave",
        )]
        body = await self.accept_and_reveal(api, "Anna")
        assert api.fake.revealed == [], "Apollo was not asked, so nothing was charged"
        assert (body["reused"], body["credits"], body["created"], body["verified"]) == (1, 0, 1, 1)
        after = await suggestions(api)
        assert after["Anna"]["status"] == "revealed" and "no credit" in after["Anna"]["note"]

    async def test_a_refusal_to_save_does_not_undo_a_paid_reveal(self, api):
        api.fake.save_error = "this key cannot write contacts"
        body = await self.accept_and_reveal(api, "Seth")
        assert body["revealed"] == 1 and body["saved_to_apollo"] == 0
        assert body["save_error"] == "this key cannot write contacts"
        assert (await suggestions(api))["Seth"]["status"] == "revealed"


class TestRevealingASelection:
    async def accept(self, api, *names):
        await find(api)
        rows = await suggestions(api)
        await api.post(
            f"/api/lists/{api.ids['list']}/suggestions/decide",
            json={"ids": [rows[n]["id"] for n in names], "status": "accepted"},
        )
        return rows

    async def test_only_the_selected_people_are_sent_to_apollo(self, api):
        rows = await self.accept(api, "Seth", "Anna")
        body = (await api.post(
            f"/api/lists/{api.ids['list']}/suggestions/reveal", json={"ids": [rows["Anna"]["id"]]}
        )).json()
        assert api.fake.revealed == [["p3"]], "Seth was accepted but not selected"
        assert body["asked"] == 1
        assert (await suggestions(api))["Seth"]["status"] == "accepted"

    async def test_running_out_part_way_keeps_what_was_bought_and_the_rest_accepted(self, api):
        from app.services.apollo_people import OutOfCredits

        await self.accept(api, "Seth", "Anna")
        records = api.fake.records

        async def partial(ids):
            api.fake.revealed.append(list(ids))
            raise OutOfCredits("Apollo has no credits left on this plan.", revealed={"p1": records["p1"]}, credits=1)

        api.fake.reveal = partial
        response = await api.post(f"/api/lists/{api.ids['list']}/suggestions/reveal")
        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["revealed"], body["credits"]) == (1, 1) and "no credits" in body["stopped"]
        after = await suggestions(api)
        assert after["Seth"]["status"] == "revealed"
        assert after["Anna"]["status"] == "accepted", "not asked for is not 'not found'"

    async def test_no_credits_at_all_still_fails_and_changes_nothing(self, api):
        from app.services.apollo_people import OutOfCredits

        await self.accept(api, "Seth")

        async def none_left(ids):
            raise OutOfCredits("Apollo has no credits left on this plan.")

        api.fake.reveal = none_left
        response = await api.post(f"/api/lists/{api.ids['list']}/suggestions/reveal")
        assert response.status_code == 502
        assert (await suggestions(api))["Seth"]["status"] == "accepted"
