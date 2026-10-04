"""What an account list is being worked for, and why it is two choices.

Services first, then the ICPs reachable from them. That order is the decision
this file records: a rep thinks in terms of what they are selling, and picking
the service narrows the ICP list to something short enough to read. The
alternative — pick ICPs and infer the services — is one choice instead of two,
but it offers a list that grows with every profile in the system and hides the
question the rep actually has an answer to.

The rule that has to hold either way: **an ICP the chosen services do not sell
to is refused, not filtered.** Quietly dropping it would leave the list
enriching for fewer profiles than the screen showed, and nothing would say so
until somebody wondered why half the contacts were missing.

Against the real test database — the whole subject is link tables.
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
    """A client on the test database, with two services and two ICPs.

    `qa` sells to both profiles; `eia` sells only to `Broad`. That asymmetry is
    the point — it is what makes "reachable from the chosen services" mean
    something rather than being trivially true.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.models.account import AccountList
    from app.models.config import (
        IcpProfile,
        IcpProfileVersion,
        ServiceCatalog,
        service_icp_link,
    )

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async with maker() as seed:
        qa = ServiceCatalog(code="qa", name="QA", description="QA")
        eia = ServiceCatalog(code="eia", name="EIA", description="EIA")
        broad = IcpProfile(name="Broad")
        narrow = IcpProfile(name="Narrow")
        lst = AccountList(label="targeting", source="csv", created_by="tests")
        seed.add_all([qa, eia, broad, narrow, lst])
        await seed.flush()
        seed.add_all(
            [
                IcpProfileVersion(
                    icp_profile_id=broad.id, definition={}, version=1, is_active=True
                ),
                IcpProfileVersion(
                    icp_profile_id=narrow.id, definition={}, version=1, is_active=True
                ),
            ]
        )
        for sid, pid in (
            (qa.id, broad.id),
            (qa.id, narrow.id),
            (eia.id, broad.id),
        ):
            await seed.execute(
                service_icp_link.insert().values(service_id=sid, icp_profile_id=pid)
            )
        await seed.commit()
        ids = {
            "qa": qa.id,
            "eia": eia.id,
            "broad": broad.id,
            "narrow": narrow.id,
            "list": lst.id,
        }

    app = create_app()

    async def _session():
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        c.ids = ids  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


def _url(api) -> str:
    return f"/api/lists/{api.ids['list']}/targeting"


class TestPickingServicesThenIcps:
    async def test_a_new_list_targets_nothing(self, api):
        r = await api.get(_url(api))
        assert r.status_code == 200
        assert r.json() == {
            "service_ids": [],
            "icp_profile_ids": [],
            "available_icps": [],
        }

    async def test_the_available_icps_follow_the_chosen_services(self, api):
        """The picker never works this out itself, so it cannot drift.

        `eia` sells only to Broad. Choosing it must not offer Narrow, even
        though Narrow is a perfectly good profile that `qa` sells to.
        """
        await api.put(
            _url(api),
            json={
                "service_ids": [str(api.ids["eia"])],
                "icp_profile_ids": [str(api.ids["broad"])],
            },
        )
        body = (await api.get(_url(api))).json()
        assert body["available_icps"] == [str(api.ids["broad"])]

    async def test_targeting_round_trips(self, api):
        r = await api.put(
            _url(api),
            json={
                "service_ids": [str(api.ids["qa"])],
                "icp_profile_ids": [
                    str(api.ids["broad"]),
                    str(api.ids["narrow"]),
                ],
            },
        )
        assert r.status_code == 200, r.text
        body = (await api.get(_url(api))).json()
        assert sorted(body["icp_profile_ids"]) == sorted(
            [str(api.ids["broad"]), str(api.ids["narrow"])]
        )

    async def test_choosing_again_replaces_rather_than_accumulates(self, api):
        """Otherwise a list quietly widens every time somebody edits it."""
        await api.put(
            _url(api),
            json={
                "service_ids": [str(api.ids["qa"])],
                "icp_profile_ids": [str(api.ids["broad"]), str(api.ids["narrow"])],
            },
        )
        await api.put(
            _url(api),
            json={
                "service_ids": [str(api.ids["qa"])],
                "icp_profile_ids": [str(api.ids["narrow"])],
            },
        )
        body = (await api.get(_url(api))).json()
        assert body["icp_profile_ids"] == [str(api.ids["narrow"])]


class TestWhatIsRefused:
    async def test_an_icp_the_service_does_not_sell_to_is_refused(self, api):
        """Refused, not filtered — the difference is the whole point.

        Filtering would leave the list enriching for one profile while the
        screen showed two, and nothing would report the discrepancy.
        """
        r = await api.put(
            _url(api),
            json={
                "service_ids": [str(api.ids["eia"])],
                "icp_profile_ids": [str(api.ids["narrow"])],
            },
        )
        assert r.status_code == 422
        assert (await api.get(_url(api))).json()["icp_profile_ids"] == []

    async def test_an_unknown_icp_is_refused(self, api):
        r = await api.put(
            _url(api),
            json={
                "service_ids": [str(api.ids["qa"])],
                "icp_profile_ids": [str(uuid.uuid4())],
            },
        )
        assert r.status_code == 422

    async def test_an_unknown_service_is_refused(self, api):
        r = await api.put(
            _url(api),
            json={
                "service_ids": [str(uuid.uuid4())],
                "icp_profile_ids": [str(api.ids["broad"])],
            },
        )
        assert r.status_code == 422

    @pytest.mark.parametrize("field", ["service_ids", "icp_profile_ids"])
    async def test_neither_side_may_be_empty(self, api, field):
        payload = {
            "service_ids": [str(api.ids["qa"])],
            "icp_profile_ids": [str(api.ids["broad"])],
        }
        payload[field] = []
        assert (await api.put(_url(api), json=payload)).status_code == 422

    async def test_a_missing_list_is_404(self, api):
        r = await api.get(f"/api/lists/{uuid.uuid4()}/targeting")
        assert r.status_code == 404
