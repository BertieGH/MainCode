"""Deleting a list, and what it does to the accounts on it.

A list is a workspace, not what decides whether an account's data lives, so a
list can always be deleted. Its accounts are assessed as though it were gone:
still on another list or in a campaign queue — untouched; on nothing else with
work behind them — dormant, nothing deleted; never worked on — deleted, which
is how a bad import is undone. `test_dormant_accounts.py` covers the rest.
"""

from __future__ import annotations

import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_session
from app.main import create_app

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.getenv("TEST_DATABASE_URL"),
        reason="TEST_DATABASE_URL not set — these write real rows",
    ),
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
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        c.maker = maker  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


async def make_list(api, *, accounts=1, label=None):
    """A list with its own accounts, named uniquely so runs do not collide."""
    from app.models.account import Account, AccountList, AccountListMember

    tag = uuid.uuid4().hex[:8]
    async with api.maker() as s:
        lst = AccountList(
            label=label or f"list-{tag}", source="csv", created_by="tests"
        )
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


async def account_exists(api, account_id) -> bool:
    from app.models.account import Account

    async with api.maker() as s:
        return await s.get(Account, account_id) is not None


class TestAMisImportCanBeUndone:
    async def test_a_list_with_accounts_can_be_deleted(self, api):
        """The case the old rule stranded."""
        list_id, accounts = await make_list(api, accounts=3)
        r = await api.delete(f"/api/lists/{list_id}")
        assert r.status_code == 200, r.text
        assert r.json()["accounts_deleted"] == 3

    async def test_its_orphaned_accounts_go_with_it(self, api):
        """Left behind they are invisible and still hold the domain index,
        so the same companies could never be re-imported."""
        list_id, accounts = await make_list(api, accounts=2)
        await api.delete(f"/api/lists/{list_id}")
        for account_id in accounts:
            assert not await account_exists(api, account_id)

    async def test_an_empty_list_still_deletes(self, api):
        list_id, _ = await make_list(api, accounts=0)
        r = await api.delete(f"/api/lists/{list_id}")
        assert r.status_code == 200
        assert r.json() == {"accounts_deleted": 0, "accounts_kept": 0, "accounts_dormant": 0}

    async def test_a_missing_list_is_404(self, api):
        assert (await api.delete(f"/api/lists/{uuid.uuid4()}")).status_code == 404


class TestAnAccountOnAnotherListIsKept:
    async def test_a_shared_account_survives(self, api):
        """A list is a selection, not an owner. The same company legitimately
        appears on several, and deleting one must not empty the others."""
        from app.models.account import AccountList, AccountListMember

        list_id, accounts = await make_list(api, accounts=2)
        shared = accounts[0]

        async with api.maker() as s:
            other = AccountList(label=f"other-{uuid.uuid4().hex[:6]}",
                                source="csv", created_by="tests")
            s.add(other)
            await s.flush()
            s.add(AccountListMember(list_id=other.id, account_id=shared))
            await s.commit()

        r = await api.delete(f"/api/lists/{list_id}")
        assert r.json() == {"accounts_deleted": 1, "accounts_kept": 1, "accounts_dormant": 0}
        assert await account_exists(api, shared), "emptied another list"
        assert not await account_exists(api, accounts[1])


class TestNothingStopsIt:
    async def test_evidence_makes_the_account_dormant_not_the_list_permanent(self, api):
        """Invariant 2 still holds — the evidence stays — but the list goes."""
        from app.models.account import Account
        from app.models.signal import Evidence

        list_id, accounts = await make_list(api, accounts=1)
        async with api.maker() as s:
            s.add(
                Evidence(
                    account_id=accounts[0],
                    source_type="news",
                    source_url="https://example.com/a",
                    excerpt="something that was found",
                    source_hash=uuid.uuid4().hex,
                    excerpt_hash=uuid.uuid4().hex,
                    raw_ref=f"snapshot/{uuid.uuid4().hex}",
                )
            )
            await s.commit()

        r = await api.delete(f"/api/lists/{list_id}")
        assert r.status_code == 200, r.text
        assert r.json()["accounts_dormant"] == 1
        async with api.maker() as s:
            assert (await s.get(Account, accounts[0])).dormant_at is not None

    async def test_a_queued_account_stays_live(self, api):
        """Whatever went to a campaign stays; the queue anchors it."""
        from app.models.account import Account
        from app.models.campaign import CampaignQueue, CampaignQueueMember

        list_id, accounts = await make_list(api, accounts=1)
        async with api.maker() as s:
            queue = CampaignQueue(label=f"q-{uuid.uuid4().hex[:6]}")
            s.add(queue)
            await s.flush()
            s.add(CampaignQueueMember(queue_id=queue.id, account_id=accounts[0], source_list_id=list_id))
            await s.commit()

        r = await api.delete(f"/api/lists/{list_id}")
        assert r.status_code == 200, r.text
        assert r.json() == {"accounts_deleted": 0, "accounts_kept": 1, "accounts_dormant": 0}
        async with api.maker() as s:
            assert (await s.get(Account, accounts[0])).dormant_at is None
