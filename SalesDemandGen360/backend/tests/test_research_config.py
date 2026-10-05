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


SOURCES = "/api/config/research-sources"


class TestResumingASourceClearsWhyItWasStopped:
    """`status_reason` answers "why is this not active?".

    Found by `scripts/audit_sources.py`: `linkedin_serp` was resumed and kept
    the reason it had been paused for — "No SERP API credential is configured"
    — so the registry showed a running source carrying a live-looking warning.
    A stale reason is worse than none, because the screen puts it next to the
    status as though the two agree.
    """

    async def _pause(self, key: str, reason: str) -> None:
        # No endpoint sets `status_reason`; a migration or the pause path does.
        # Writing it directly is what reproduces the state that was found.
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE research_source SET status='paused', status_reason=:r "
                    "WHERE key=:k"
                ).bindparams(r=reason, k=key)
            )
        await engine.dispose()

    async def test_going_back_to_active_drops_the_reason(self, api):
        await self._pause("trade_press", "measured dead for this book")
        before = next(s for s in (await api.get(SOURCES)).json() if s["key"] == "trade_press")
        assert before["status"] == "paused"
        assert before["status_reason"] == "measured dead for this book"

        r = await api.patch(f"{SOURCES}/trade_press", json={"status": "active"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "active"
        assert r.json()["status_reason"] is None

    async def test_pausing_again_keeps_whatever_reason_is_there(self, api):
        """Only the return to active clears it. Pausing must not wipe a reason
        a migration wrote to explain the pause."""
        await self._pause("trade_press", "still being measured")
        r = await api.patch(f"{SOURCES}/trade_press", json={"status": "paused"})
        assert r.status_code == 200, r.text
        assert r.json()["status_reason"] == "still being measured"

    async def test_any_real_edit_returns_the_row_rather_than_500ing(self, api):
        """The bug underneath the stale reason, and the worse half of it.

        `updated_at` is mapped `onupdate=func.now()`. That is a SQL expression,
        so a flush expires the attribute and the next read is IO — inside a
        synchronous comprehension, which raised `MissingGreenlet`. The commit
        had already happened, so the write landed and the caller got a 500: the
        database and the screen disagreed, with the database right.

        A patch that changes nothing flushes nothing and never saw it, which is
        how this survived. So the assertion is on a patch that genuinely
        changes a value.
        """
        r = await api.patch(f"{SOURCES}/trade_press", json={"label": "Trade press"})
        assert r.status_code == 200, r.text
        assert r.json()["label"] == "Trade press"
        assert r.json()["key"] == "trade_press"
