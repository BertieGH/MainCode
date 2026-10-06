"""The research reuse window, as a setting.

Versioned like every other config table: saving writes a new active row, and
the old ones stay readable. Reading never 404s — no row means the default
applies, which is a working state rather than a missing one.
"""

from __future__ import annotations

import json
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


class TestASignalTypeThatCannotFireSaysSo:
    """A type missing from the active ICP's `signals_that_matter` cannot produce
    a signal, however well it is configured.

    That list is what `ListPlan.type_keys` returns and it is what extraction is
    restricted to — deliberately, and already tested in
    `test_research_route.py`. The defect was never the gate; it was that nothing
    said the list had fallen behind the registry. Eight of fifteen types were in
    that state, including all seven Enterprise IT types added for this book, and
    they reported only as "never produced anything".
    """

    TYPES = "/api/config/signal-types"

    async def _icp(self, names: list[str] | None) -> None:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
        async with engine.begin() as conn:
            profile = (
                await conn.execute(text("SELECT id FROM icp_profile LIMIT 1"))
            ).scalar_one_or_none()
            if profile is None:
                profile = (
                    await conn.execute(
                        text(
                            "INSERT INTO icp_profile (name, description) "
                            "VALUES ('T', 'T') RETURNING id"
                        )
                    )
                ).scalar_one()
            await conn.execute(
                text("DELETE FROM icp_profile_version WHERE icp_profile_id = :p")
                .bindparams(p=profile)
            )
            definition = {} if names is None else {"signals_that_matter": names}
            await conn.execute(
                text(
                    "INSERT INTO icp_profile_version "
                    "(icp_profile_id, definition, version, is_active) "
                    "VALUES (:p, CAST(:d AS jsonb), 1, true)"
                ).bindparams(p=profile, d=json.dumps(definition))
            )
        await engine.dispose()

    async def _types(self, *keys: str) -> None:
        """Signal types are not seeded into the test database, so make them."""
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
        async with engine.begin() as conn:
            for key in keys:
                await conn.execute(
                    text(
                        "INSERT INTO signal_type "
                        "(key, label, description, scope, default_ttl_days, weight, "
                        " produced_by, kind, status) "
                        "VALUES (:k, :k, 'what lives there', 'company', 90, 1.0, "
                        "        ARRAY['company_site'], 'event', 'active') "
                        "ON CONFLICT (key) DO NOTHING"
                    ).bindparams(k=key)
                )
        await engine.dispose()

    async def test_a_type_the_icp_does_not_name_is_flagged(self, api):
        await self._types("named_by_the_icp", "left_out_of_the_icp")
        await self._icp(["named_by_the_icp"])

        by_key = {r["key"]: r for r in (await api.get(self.TYPES)).json()}
        assert by_key["named_by_the_icp"]["extractable"] is True
        assert by_key["left_out_of_the_icp"]["extractable"] is False, (
            "a type the ICP leaves out should say it cannot fire"
        )

    async def test_an_icp_naming_no_signals_narrows_nothing(self, api):
        """None is not the empty set. An ICP that has accepted no list does not
        restrict extraction, so reporting every type as unreachable would be the
        opposite of the truth."""
        await self._types("named_by_the_icp", "left_out_of_the_icp")
        await self._icp(None)
        rows = (await api.get(self.TYPES)).json()
        assert rows and all(r["extractable"] is True for r in rows)


class TestAnExclusionCannotStrandASignal:
    """Excluding a source is the one way to say "this place is wrong for *this*
    book" — reading a technology directory is worth paying for at a software
    company and worthless at a twenty-person broker, and the signal list cannot
    express that.

    What it must not do is switch off the last place a chosen signal has. That
    is §80 reintroduced per ICP and invisible: a type configured, selected, and
    unable to produce anything. Refused rather than warned, because the state
    has no use — if the signal is unwanted here, the signal is what to drop,
    and then its sources are not derived at all.
    """

    ICPS = "/api/config/icp-profiles"

    async def _setup(self, *, produced_by: dict[str, list[str]]) -> str:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
        async with engine.begin() as conn:
            for key, sources in produced_by.items():
                await conn.execute(
                    text(
                        "INSERT INTO signal_type (key, label, description, scope, "
                        " default_ttl_days, weight, produced_by, kind, status) "
                        "VALUES (:k, :k, 'x', 'company', 90, 1.0, :p, 'event', 'active') "
                        "ON CONFLICT (key) DO UPDATE SET produced_by = EXCLUDED.produced_by"
                    ).bindparams(k=key, p=sources)
                )
            profile = (
                await conn.execute(text("SELECT id FROM icp_profile LIMIT 1"))
            ).scalar_one_or_none() or (
                await conn.execute(
                    text(
                        "INSERT INTO icp_profile (name, description) "
                        "VALUES ('T','T') RETURNING id"
                    )
                )
            ).scalar_one()
        await engine.dispose()
        return str(profile)

    async def test_the_last_live_source_cannot_be_switched_off(self, api):
        profile = await self._setup(produced_by={"only_one_place": ["company_site"]})
        r = await api.put(
            f"{self.ICPS}/{profile}",
            json={"definition": {
                "signals_that_matter": ["only_one_place"],
                "sources_excluded": ["company_site"],
            }},
        )
        assert r.status_code == 422, r.text
        assert "only_one_place" in r.json()["detail"]
        assert "could never fire" in r.json()["detail"]

    async def test_a_source_the_signal_can_do_without_is_allowed(self):
        """The whole point of keeping exclusions. A type with somewhere else to
        look loses a place it was not getting value from, and keeps firing."""
        # Exercised through the service rather than the fixture's client so the
        # two signal types below cannot collide with another test's registry.
        from app.api.config import _stranded_by_exclusions
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        await self._setup(produced_by={"two_places": ["company_site", "trade_press"]})
        engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            stranded = await _stranded_by_exclusions(
                session,
                {"signals_that_matter": ["two_places"], "sources_excluded": ["company_site"]},
            )
        await engine.dispose()
        assert stranded == set()

    async def test_a_paused_remainder_does_not_count_as_somewhere_to_look(self):
        """A type whose only other source is paused is stranded just as surely
        as one with none left — so the check reads live sources, not claimed."""
        from app.api.config import _stranded_by_exclusions
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        await self._setup(produced_by={"other_is_paused": ["company_site", "ats_boards"]})
        engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE research_source SET status='paused' WHERE key='ats_boards'")
            )
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            stranded = await _stranded_by_exclusions(
                session,
                {
                    "signals_that_matter": ["other_is_paused"],
                    "sources_excluded": ["company_site"],
                },
            )
        await engine.dispose()
        assert stranded == {"other_is_paused"}
