"""Saving paid-for people as Apollo contacts, and reading them back before paying. No network."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services import apollo_contacts, apollo_people
from app.services.apollo_people import SavedContact
from app.services.providers import ProviderError
from tests.test_apollo_people import FakeHttp, FakeResponse


def saved(**kw) -> SavedContact:
    base = dict(
        id="c1", person_id=None, first_name=None, last_name=None, name=None, email=None,
        email_status=None, linkedin_url=None, title=None, organization_name=None,
    )
    base.update(kw)
    return SavedContact(**base)


class TestTheClient:
    async def test_saving_is_deduplicated_labelled_and_batched_by_a_hundred(self):
        created = {"created_contacts": [{"id": "c1", "email": "a@x.com", "first_name": "A"}],
                   "existing_contacts": [{"id": "c0", "email": "b@x.com", "person_id": "p9"}]}
        http = FakeHttp([FakeResponse(200, created), FakeResponse(200, {"created_contacts": []})])
        people = apollo_people.ApolloPeople("k", client_factory=lambda: http)
        result = await people.save_contacts([{"first_name": f"P{i}"} for i in range(101)])
        assert [c["url"].rsplit("/", 2)[-2:] for c in http.calls] == [["contacts", "bulk_create"]] * 2
        body = http.calls[0]["json"]
        assert len(body["contacts"]) == 100 and len(http.calls[1]["json"]["contacts"]) == 1
        assert body["run_dedupe"] is True and body["append_label_names"] == ["Gen360"]
        assert [(s.id, s.person_id) for s in result] == [("c1", None), ("c0", "p9")]

    async def test_searching_saved_contacts_reads_the_contacts_list(self):
        http = FakeHttp([FakeResponse(200, {"contacts": [
            {"id": "c1", "person_id": "p1", "email": "seth@bluewave.net", "email_status": "verified",
             "linkedin_url": "http://www.linkedin.com/in/seth-penland", "organization_name": "BlueWave"},
            {"no": "id"},
        ]})])
        people = apollo_people.ApolloPeople("k", client_factory=lambda: http)
        found = await people.find_saved(keywords="BlueWave", per_page=500)
        assert http.calls[0]["url"].endswith("/contacts/search")
        assert http.calls[0]["json"] == {"q_keywords": "BlueWave", "page": 1, "per_page": 100}
        assert [(s.id, s.person_id, s.email_status) for s in found] == [("c1", "p1", "verified")]


class FakeSession:
    def __init__(self, accounts):
        self.accounts = accounts

    async def get(self, model, key):
        return self.accounts.get(key)


class FakePeople:
    def __init__(self, *, saved_contacts=(), fail=None):
        self.saved_contacts = list(saved_contacts)
        self.fail = fail
        self.saves: list[list[dict]] = []
        self.searches: list[str] = []

    async def save_contacts(self, bodies):
        if self.fail:
            raise ProviderError(self.fail)
        self.saves.append(bodies)
        return [
            saved(id=f"c-{i}", email=b.get("email"), first_name=b.get("first_name"),
                  last_name=b.get("last_name"), organization_name=b.get("organization_name"))
            for i, b in enumerate(bodies)
        ]

    async def find_saved(self, *, keywords, per_page=25):
        if self.fail:
            raise ProviderError(self.fail)
        self.searches.append(keywords)
        return [s for s in self.saved_contacts
                if keywords.casefold() in {(s.email or "").casefold(), (s.organization_name or "").casefold()}]


def contact(**kw):
    base = dict(id=uuid.uuid4(), account_id="acc", full_name="Seth Penland", title="CEO",
                email="seth@bluewave.net", linkedin_url=None, apollo_contact_id=None,
                apollo_saved_at=None, email_status="verified", email_verified_at=None)
    base.update(kw)
    return SimpleNamespace(**base)


class TestSaving:
    def test_the_payload_splits_the_name_and_leaves_out_what_is_empty(self):
        body = apollo_contacts.payload(contact(title=None), SimpleNamespace(name="BlueWave"))
        assert body == {"first_name": "Seth", "last_name": "Penland", "email": "seth@bluewave.net",
                        "organization_name": "BlueWave"}

    async def test_saved_contacts_are_marked_with_apollos_id(self):
        seth, dana = contact(), contact(full_name="Dana Reid", email=None,
                                        linkedin_url="https://www.linkedin.com/in/danareid")
        already = contact(full_name="Kept", apollo_contact_id="old")
        people = FakePeople()
        count, error = await apollo_contacts.save(
            FakeSession({"acc": SimpleNamespace(name="BlueWave")}), people, [seth, dana, already]
        )
        assert (count, error) == (2, None)
        assert len(people.saves[0]) == 2, "one already saved is not sent again"
        assert seth.apollo_contact_id == "c-0" and dana.apollo_contact_id == "c-1"
        assert seth.apollo_saved_at is not None

    async def test_a_refusal_is_reported_not_raised(self):
        seth = contact()
        count, error = await apollo_contacts.save(
            FakeSession({"acc": SimpleNamespace(name="BlueWave")}), FakePeople(fail="no access"), [seth]
        )
        assert (count, error) == (0, "no access") and seth.apollo_contact_id is None


class TestReconfirmingForFree:
    async def test_a_saved_contact_apollo_still_grades_verified_settles_the_recheck(self):
        old = datetime.now(UTC) - timedelta(days=120)
        seth = contact(email_verified_at=old)
        people = FakePeople(saved_contacts=[saved(id="c9", email="Seth@BlueWave.net", email_status="verified")])
        done = await apollo_contacts.reconfirm_stale([seth], people)
        assert done == {seth.id}
        assert seth.email_verified_at > old and seth.apollo_contact_id == "c9"

    @pytest.mark.parametrize("status", ["unverified", "likely to engage", None])
    async def test_anything_short_of_verified_is_left_for_the_paid_check(self, status):
        seth = contact(email_verified_at=datetime(2026, 1, 1, tzinfo=UTC))
        people = FakePeople(saved_contacts=[saved(email="seth@bluewave.net", email_status=status)])
        assert await apollo_contacts.reconfirm_stale([seth], people) == set()
        assert seth.email_verified_at == datetime(2026, 1, 1, tzinfo=UTC)

    async def test_a_refusal_stops_instead_of_repeating(self):
        people = FakePeople(fail="rate limit")
        assert await apollo_contacts.reconfirm_stale([contact(), contact()], people) == set()
