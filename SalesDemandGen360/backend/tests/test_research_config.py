"""The research reuse window, as a setting.

Versioned like every other config table: saving writes a new active row, and
the old ones stay readable. Reading never 404s — no row means the default
applies, which is a working state rather than a missing one.
"""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_session
from app.main import create_app

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.getenv("TEST_DATABASE_URL"),
        reason="TEST_DATABASE_URL not set — these write real config rows",
    ),
]

URL = "/api/config/research-settings"


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
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


class TestTheReuseWindowSetting:
    async def test_it_is_thirty_days_before_anyone_sets_it(self, api):
        r = await api.get(URL)
        assert r.status_code == 200
        assert (r.json()["freshness_days"], r.json()["version"]) == (30, 0)

    async def test_saving_writes_a_new_version(self, api):
        first = await api.put(URL, json={"freshness_days": 45})
        assert first.status_code == 201, first.text
        second = await api.put(URL, json={"freshness_days": 60})
        assert second.json()["version"] == first.json()["version"] + 1
        assert (await api.get(URL)).json()["freshness_days"] == 60

    @pytest.mark.parametrize("days", [0, -1, 366])
    async def test_a_window_outside_a_day_to_a_year_is_refused(self, api, days):
        """Zero would mean "never reuse" — that is what Rerun research is for."""
        assert (await api.put(URL, json={"freshness_days": days})).status_code == 422
