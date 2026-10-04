"""Lists are workspaces: what happens to an account no list or queue holds.

An account is anchored while it is on a list or in a campaign queue. Losing
its last anchor makes it dormant when there is work behind it, and deletes it
only when a whole list goes and nothing was ever done with it. Joining a list
brings it back. Real rows; nothing reaches a vendor.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_session
from app.main import create_app
from app.services import verification

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"),
]


@pytest.fixture
async def api():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    maker = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app()

    async def _session():
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.maker = maker  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


async def make_list(api, *, accounts=1, label=None):
    from app.models.account import Account, AccountList, AccountListMember

    tag = uuid.uuid4().hex[:8]
    async with api.maker() as s:
        lst = AccountList(label=label or f"list-{tag}", source="csv", created_by="tests")
        s.add(lst)
        await s.flush()
        ids = []
        for i in range(accounts):
            acc = Account(name=f"Acme {tag} {i}", domain=f"acme-{tag}-{i}.example")
            s.add(acc)
            await s.flush()
            s.add(AccountListMember(list_id=lst.id, account_id=acc.id))
            ids.append(acc.id)
        await s.commit()
        return lst.id, ids


async def add_evidence(api, account_id):
    from app.models.signal import Evidence

    async with api.maker() as s:
        s.add(
            Evidence(
                account_id=account_id, source_type="news", source_url="https://example.com/a",
                excerpt="something that was found", source_hash=uuid.uuid4().hex,
                excerpt_hash=uuid.uuid4().hex, raw_ref=f"snapshot/{uuid.uuid4().hex}",
            )
        )
        await s.commit()


async def queue_with(api, *account_ids, list_id=None):
    from app.models.campaign import CampaignQueue, CampaignQueueMember

    async with api.maker() as s:
        queue = CampaignQueue(label=f"q-{uuid.uuid4().hex[:6]}")
        s.add(queue)
        await s.flush()
        for account_id in account_ids:
            s.add(CampaignQueueMember(queue_id=queue.id, account_id=account_id, source_list_id=list_id))
        await s.commit()
        return queue.id


async def on_another_list(api, account_id):
    from app.models.account import AccountList, AccountListMember

    async with api.maker() as s:
        other = AccountList(label=f"other-{uuid.uuid4().hex[:6]}", source="csv", created_by="tests")
        s.add(other)
        await s.flush()
        s.add(AccountListMember(list_id=other.id, account_id=account_id))
        await s.commit()
        return other.id


async def account(api, account_id):
    from app.models.account import Account

    async with api.maker() as s:
        return await s.get(Account, account_id)


class TestDeletingAList:
    async def test_the_preview_and_the_delete_agree(self, api):
        list_id, (shared, queued, worked, untouched) = await make_list(api, accounts=4)
        await on_another_list(api, shared)
        await queue_with(api, queued, list_id=list_id)
        await add_evidence(api, worked)

        preview = await api.get(f"/api/lists/{list_id}/delete-preview")
        assert preview.status_code == 200, preview.text
        assert preview.json() == {
            "accounts": 4, "on_other_lists": 1, "in_queues": 1, "dormant": 1, "deleted": 1,
        }
        assert (await api.get(f"/api/lists/{list_id}")).status_code == 200, "a preview writes nothing"

        r = await api.delete(f"/api/lists/{list_id}")
        assert r.status_code == 200, r.text
        assert r.json() == {"accounts_deleted": 1, "accounts_kept": 2, "accounts_dormant": 1}

        assert (await account(api, shared)).dormant_at is None
        assert (await account(api, queued)).dormant_at is None
        dormant = await account(api, worked)
        assert dormant.dormant_at is not None and "was deleted" in dormant.dormant_reason
        assert await account(api, untouched) is None

    async def test_the_evidence_of_a_dormant_account_is_all_still_there(self, api):
        from sqlalchemy import func, select

        from app.models.signal import Evidence

        list_id, (worked,) = await make_list(api)
        await add_evidence(api, worked)
        await api.delete(f"/api/lists/{list_id}")
        async with api.maker() as s:
            held = await s.scalar(select(func.count()).select_from(Evidence).where(Evidence.account_id == worked))
        assert held == 1

    async def test_undecided_suggestions_go_decided_ones_outlive_the_list(self, api):
        from sqlalchemy import select

        from app.models.account import ContactSuggestion

        list_id, (worked,) = await make_list(api)
        await add_evidence(api, worked)
        async with api.maker() as s:
            for pid, status in (("p1", "proposed"), ("p2", "rejected"), ("p3", "revealed")):
                s.add(ContactSuggestion(list_id=list_id, account_id=worked, apollo_person_id=pid, status=status))
            await s.commit()

        await api.delete(f"/api/lists/{list_id}")
        async with api.maker() as s:
            rows = (await s.execute(select(ContactSuggestion.apollo_person_id, ContactSuggestion.list_id))).all()
        assert sorted(rows) == [("p2", None), ("p3", None)]


class TestOtherWaysToLoseAnAnchor:
    async def test_removing_from_a_list_makes_dormant_and_deletes_nothing(self, api):
        list_id, (never_worked,) = await make_list(api)
        r = await api.post(f"/api/lists/{list_id}/accounts/remove", json={"account_ids": [str(never_worked)]})
        assert r.json() == {"removed": 1, "not_members": 0, "dormant": 1}
        kept = await account(api, never_worked)
        assert kept is not None and kept.dormant_at is not None

    async def test_removing_from_a_list_while_queued_changes_nothing(self, api):
        list_id, (queued,) = await make_list(api)
        await queue_with(api, queued, list_id=list_id)
        r = await api.post(f"/api/lists/{list_id}/accounts/remove", json={"account_ids": [str(queued)]})
        assert r.json()["dormant"] == 0
        assert (await account(api, queued)).dormant_at is None

    async def test_leaving_the_last_queue_makes_a_listless_account_dormant(self, api):
        list_id, (queued,) = await make_list(api)
        queue_id = await queue_with(api, queued, list_id=list_id)
        await api.delete(f"/api/lists/{list_id}")
        assert (await account(api, queued)).dormant_at is None, "the queue still holds it"

        r = await api.delete(f"/api/queues/{queue_id}/members/{queued}")
        assert r.status_code == 204, r.text
        assert (await account(api, queued)).dormant_at is not None

    async def test_deleting_a_draft_queue_makes_its_listless_accounts_dormant(self, api):
        list_id, (queued, listed) = await make_list(api, accounts=2)
        queue_id = await queue_with(api, queued, listed, list_id=list_id)
        await api.post(f"/api/lists/{list_id}/accounts/remove", json={"account_ids": [str(queued)]})

        r = await api.delete(f"/api/queues/{queue_id}")
        assert r.status_code == 204, r.text
        assert (await account(api, queued)).dormant_at is not None
        assert (await account(api, listed)).dormant_at is None, "still on the list"


class TestComingBack:
    async def dormant_account(self, api):
        list_id, (worked,) = await make_list(api)
        await add_evidence(api, worked)
        await api.delete(f"/api/lists/{list_id}")
        return worked

    async def test_add_to_list_brings_it_back(self, api):
        worked = await self.dormant_account(api)
        new_list, _ = await make_list(api, accounts=0)
        r = await api.post(
            f"/api/lists/{new_list}/accounts/add",
            json={"account_ids": [str(worked), str(uuid.uuid4())]},
        )
        assert r.json() == {"added": 1, "already": 0, "revived": 1, "not_found": 1}
        back = await account(api, worked)
        assert back.dormant_at is None and back.dormant_reason is None

    async def test_an_import_with_its_domain_brings_it_back(self, api):
        from app.services import csv_import

        worked = await self.dormant_account(api)
        domain = (await account(api, worked)).domain
        new_list, _ = await make_list(api, accounts=0)
        headers = ["Company", "Domain"]
        rows = [{"Company": "Acme again", "Domain": domain}]
        async with api.maker() as s:
            report = await csv_import.run_import(
                s, list_id=new_list, rows=rows, mapping=csv_import.suggest_mapping(headers),
                added_by="tests", dry_run=False,
            )
        assert report.revived == 1
        assert "dormant" in report.rows[0].detail
        assert (await account(api, worked)).dormant_at is None

    async def test_dormant_accounts_are_hidden_unless_asked_for(self, api):
        worked = await self.dormant_account(api)
        name = (await account(api, worked)).name
        hidden = (await api.get("/api/accounts", params={"q": name})).json()
        only = (await api.get("/api/accounts", params={"q": name, "dormant": "only"})).json()
        assert hidden == []
        assert [a["id"] for a in only] == [str(worked)]
        assert only[0]["dormant_at"] is not None


class TestAVerifiedAddressIsCheckedAgain:
    @pytest.mark.parametrize(
        ("status", "age", "due"),
        [("verified", 91, True), ("verified", 89, False), ("risky", 400, False), ("verified", None, False)],
    )
    def test_after_ninety_days(self, status, age, due):
        now = datetime(2026, 9, 13, tzinfo=UTC)
        contact = SimpleNamespace(
            email_status=status, email_verified_at=None if age is None else now - timedelta(days=age)
        )
        assert verification.needs_recheck(contact, now) is due

    async def test_a_stale_address_is_offered_to_enrichment_again_and_flagged(self, api):
        from app.models.account import Contact

        list_id, (acc,) = await make_list(api)
        now = datetime.now(UTC)
        async with api.maker() as s:
            s.add_all([
                Contact(account_id=acc, full_name="Old Check", email="old@x.example",
                        email_status="verified", email_verified_at=now - timedelta(days=120)),
                Contact(account_id=acc, full_name="Fresh Check", email="new@x.example",
                        email_status="verified", email_verified_at=now - timedelta(days=5)),
            ])
            await s.commit()
            due = await verification.unverified_contacts(s, list_id=list_id)
        assert [c.full_name for c in due] == ["Old Check"]

        contacts = {c["full_name"]: c for c in (await api.get(f"/api/lists/{list_id}/contacts")).json()}
        assert contacts["Old Check"]["email_recheck"] is True
        assert contacts["Fresh Check"]["email_recheck"] is False
