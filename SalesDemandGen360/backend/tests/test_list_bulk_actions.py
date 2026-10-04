"""The three bulk actions on the account table, against the real schema.

Each one has a failure that would not show up as an error:

* **Remove** must take membership and nothing else. `evidence.account_id`
  cascades, so a remove that reached the account row would delete research —
  and invariant 2 says evidence is never deleted.
* **Add to queue** must survive one bad id. A stale id used to reach the INSERT,
  fail on the foreign key, and abort the transaction — so one account deleted
  since the screen loaded turned a forty-account add into a 500 that added
  nothing. Found by a live run, not by reading.
* **Research on a selection** must stay scoped to the list, or an id from
  anywhere could ride in on a list's route.
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
    """Two lists sharing one account, so "kept" has something to be kept on.

    `alpha` is resolved and on both lists; `beta` is unresolved and on the
    main list only.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.models.account import Account, AccountList, AccountListMember

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async with maker() as seed:
        alpha = Account(name="Alpha", domain="alpha.example", resolution_status="resolved")
        beta = Account(name="Beta", domain="beta.example", resolution_status="unresolved")
        main = AccountList(label="main", source="csv", created_by="tests")
        other = AccountList(label="other", source="csv", created_by="tests")
        seed.add_all([alpha, beta, main, other])
        await seed.flush()
        seed.add_all(
            [
                AccountListMember(list_id=main.id, account_id=alpha.id, added_by="tests"),
                AccountListMember(list_id=main.id, account_id=beta.id, added_by="tests"),
                AccountListMember(list_id=other.id, account_id=alpha.id, added_by="tests"),
            ]
        )
        await seed.commit()
        ids = {"alpha": alpha.id, "beta": beta.id, "main": main.id, "other": other.id}

    app = create_app()

    async def _session():
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.ids = ids  # type: ignore[attr-defined]
        c.maker = maker  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


async def _members(api, list_key: str) -> set[str]:
    rows = (await api.get(f"/api/lists/{api.ids[list_key]}/accounts")).json()
    return {r["id"] for r in rows}


class TestRemoveTakesMembershipOnly:
    async def test_the_accounts_leave_this_list(self, api):
        r = await api.post(
            f"/api/lists/{api.ids['main']}/accounts/remove",
            json={"account_ids": [str(api.ids["alpha"]), str(api.ids["beta"])]},
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"removed": 2, "not_members": 0, "dormant": 1}
        assert await _members(api, "main") == set()

    async def test_the_accounts_themselves_are_kept(self, api):
        """A list is a selection, not an owner. Alpha is still on `other`."""
        await api.post(
            f"/api/lists/{api.ids['main']}/accounts/remove",
            json={"account_ids": [str(api.ids["alpha"])]},
        )
        assert str(api.ids["alpha"]) in await _members(api, "other")

    async def test_an_account_on_no_list_still_exists(self, api):
        """Beta was only on `main`. Removing it must orphan it, not delete it —
        its row still holds the domain index a re-import will match against."""
        from app.models.account import Account

        await api.post(
            f"/api/lists/{api.ids['main']}/accounts/remove",
            json={"account_ids": [str(api.ids["beta"])]},
        )
        async with api.maker() as s:
            assert await s.get(Account, api.ids["beta"]) is not None

    async def test_a_stale_id_is_reported_not_counted(self, api):
        r = await api.post(
            f"/api/lists/{api.ids['main']}/accounts/remove",
            json={"account_ids": [str(api.ids["alpha"]), str(uuid.uuid4())]},
        )
        assert r.json() == {"removed": 1, "not_members": 1, "dormant": 0}

    async def test_an_empty_selection_is_refused(self, api):
        r = await api.post(
            f"/api/lists/{api.ids['main']}/accounts/remove", json={"account_ids": []}
        )
        assert r.status_code == 422

    async def test_a_missing_list_is_404(self, api):
        r = await api.post(
            f"/api/lists/{uuid.uuid4()}/accounts/remove",
            json={"account_ids": [str(api.ids["alpha"])]},
        )
        assert r.status_code == 404


class TestAddToQueueRunsOnWhatItCan:
    async def _queue(self, api) -> str:
        r = await api.post("/api/queues", json={"label": "bulk-test"})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    async def test_an_eligible_selection_is_added(self, api):
        qid = await self._queue(api)
        r = await api.post(
            f"/api/queues/{qid}/members/bulk",
            json={
                "account_ids": [str(api.ids["alpha"])],
                "source_list_id": str(api.ids["main"]),
            },
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"added": 1, "already": 0, "refused": []}

    async def test_one_stale_id_does_not_cost_the_others(self, api):
        """The live bug. The unknown id is refused; the real one is still added."""
        qid = await self._queue(api)
        r = await api.post(
            f"/api/queues/{qid}/members/bulk",
            json={"account_ids": [str(api.ids["alpha"]), str(uuid.uuid4())]},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["added"] == 1
        assert [x["reason"] for x in body["refused"]] == ["account no longer exists"]

    async def test_adding_again_is_not_double_counted(self, api):
        qid = await self._queue(api)
        payload = {"account_ids": [str(api.ids["alpha"])]}
        await api.post(f"/api/queues/{qid}/members/bulk", json=payload)
        again = (await api.post(f"/api/queues/{qid}/members/bulk", json=payload)).json()
        assert again == {"added": 0, "already": 1, "refused": []}

    async def test_duplicate_ids_in_one_request_count_once(self, api):
        qid = await self._queue(api)
        a = str(api.ids["alpha"])
        body = (
            await api.post(f"/api/queues/{qid}/members/bulk", json={"account_ids": [a, a]})
        ).json()
        assert body["added"] == 1 and body["already"] == 0


class TestResearchOnASelection:
    """Narrowed without spending: every case here stops before a model call."""

    @pytest.fixture(autouse=True)
    def _llm_allowed(self, monkeypatch):
        async def _ok(*_a, **_k):
            return None

        monkeypatch.setattr("app.services.llm.assert_may_call", _ok)

    async def test_only_the_selection_is_considered(self, api):
        """Beta is unconfirmed, so selecting only Beta attempts nothing — and
        Alpha, confirmed but unselected, must not be researched either."""
        r = await api.post(
            f"/api/lists/{api.ids['main']}/run-research",
            json={"account_ids": [str(api.ids["beta"])]},
        )
        body = r.json()
        assert body["attempted"] == 0
        assert body["skipped_unresolved"] == 1

    async def test_an_id_from_another_list_cannot_ride_in(self, api):
        """Scoped to the list the route names. A foreign id simply matches nothing."""
        r = await api.post(
            f"/api/lists/{api.ids['other']}/run-research",
            json={"account_ids": [str(api.ids["beta"])]},
        )
        body = r.json()
        assert body["attempted"] == 0
        assert body["skipped_unresolved"] == 0


class TestTheServerEnforcesQueueEligibility:
    """The rule was the screen's alone until now.

    `ACCOUNT_ACTIONS.queue` in the web app greys out unconfirmed and
    disqualified accounts — but a script, a second client or a hand-built
    request went straight past it. These hold the server to the same rule, so it
    refuses for the reasons the screen gives.
    """

    async def _queue(self, api) -> str:
        return (await api.post("/api/queues", json={"label": "eligibility"})).json()["id"]

    async def test_bulk_refuses_the_unconfirmed_and_adds_the_rest(self, api):
        """Runs on what it can: Beta is refused by name, Alpha still goes in."""
        qid = await self._queue(api)
        r = await api.post(
            f"/api/queues/{qid}/members/bulk",
            json={"account_ids": [str(api.ids["alpha"]), str(api.ids["beta"])]},
        )
        body = r.json()
        assert body["added"] == 1
        assert body["refused"] == [
            {
                "account_id": str(api.ids["beta"]),
                "reason": "identity not confirmed (unresolved)",
            }
        ]

    async def test_single_add_of_an_unconfirmed_account_is_409(self, api):
        """A state problem, not a missing thing — 409, never 404."""
        qid = await self._queue(api)
        r = await api.post(
            f"/api/queues/{qid}/members", json={"account_id": str(api.ids["beta"])}
        )
        assert r.status_code == 409
        assert "identity not confirmed" in r.json()["detail"]

    async def test_a_disqualified_account_is_refused_even_when_confirmed(self, api):
        from app.models.account import Account

        async with api.maker() as s:
            alpha = await s.get(Account, api.ids["alpha"])
            alpha.status = "disqualified"
            # The schema will not take a disqualification without a reason
            # (`ck_account_disqualified_needs_a_reason`), and nor should a test.
            alpha.disqualified_reason = "outside the ICP"
            await s.commit()

        qid = await self._queue(api)
        r = await api.post(
            f"/api/queues/{qid}/members/bulk",
            json={"account_ids": [str(api.ids["alpha"])]},
        )
        body = r.json()
        assert body["added"] == 0
        assert body["refused"][0]["reason"] == "account is disqualified"

    async def test_nothing_is_written_for_a_refused_account(self, api):
        """Refused means absent from the queue, not added-and-flagged."""
        qid = await self._queue(api)
        await api.post(
            f"/api/queues/{qid}/members/bulk",
            json={"account_ids": [str(api.ids["beta"])]},
        )
        members = (await api.get(f"/api/queues/{qid}/members")).json()
        assert members == []
