"""The coverage tab, opened: what each family found, and what it looked for.

Before this, a coverage row was four words — family, status, a count, and
"nothing found". A rep could not open a family that `ran` to check its
passages, and could not tell an `empty` family that searched thoroughly from
one that barely looked. Both are answered here, from rows the pipeline now
keeps: `research_coverage.not_found`, and `evidence.family`.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import get_session
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

    from app.models.account import Account, Run
    from app.models.research import ResearchCoverage
    from app.models.signal import Evidence
    from app.services.evidence import excerpt_hash, source_hash

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    maker = async_sessionmaker(engine, expire_on_commit=False)

    def passage(account_id, run_id, url, text, family, observed=None):
        return Evidence(
            account_id=account_id,
            run_id=run_id,
            family=family,
            source_type="news",
            source_url=url,
            source_name="Example News",
            title="A headline",
            excerpt=text,
            observed_at=observed,
            source_hash=source_hash(url, "A headline"),
            excerpt_hash=excerpt_hash(url, text),
            raw_status="unavailable",
            reliability=0.7,
        )

    async with maker() as seed:
        acc = Account(name="BlueWave", domain="bluewave.net", resolution_status="resolved")
        seed.add(acc)
        await seed.flush()
        run = Run(
            account_id=acc.id, stage="signals", status="succeeded",
            triggered_by="rep", started_at=datetime.now(UTC),
        )
        seed.add(run)
        await seed.flush()
        seed.add_all([
            ResearchCoverage(run_id=run.id, account_id=acc.id, family="hiring",
                             status="ran", evidence_count=2, not_found=["salary bands"]),
            ResearchCoverage(run_id=run.id, account_id=acc.id, family="funding",
                             status="empty", evidence_count=0,
                             not_found=["BlueWave funding rounds", "bluewave.net investors"]),
            passage(acc.id, run.id, "https://example.com/older", "Hiring two SREs.",
                    "hiring", date(2026, 3, 1)),
            passage(acc.id, run.id, "https://example.com/newer", "Opened six QA roles.",
                    "hiring", date(2026, 8, 1)),
            # Stored before evidence kept its family.
            passage(acc.id, run.id, "https://example.com/legacy", "A new CTO joined.", None),
        ])
        await seed.commit()
        account_id = acc.id

    app = create_app()

    async def _session():
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.account_id = account_id  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


async def coverage(api) -> tuple[dict, dict]:
    body = (await api.get(f"/api/accounts/{api.account_id}/intelligence")).json()
    return {c["family"]: c for c in body["coverage"]}, body


class TestAFamilyCanBeOpened:
    async def test_a_family_that_ran_carries_the_passages_it_found(self, api):
        rows, _ = await coverage(api)
        found = rows["hiring"]["evidence"]
        assert [e["excerpt"] for e in found] == ["Opened six QA roles.", "Hiring two SREs."], (
            "newest fact first"
        )
        assert found[0]["source_url"] == "https://example.com/newer"
        assert found[0]["reliability"] == 0.7
        assert len(found) == rows["hiring"]["evidence_count"], "the count and the list agree"

    async def test_an_empty_family_says_what_it_searched_for(self, api):
        rows, _ = await coverage(api)
        assert rows["funding"]["evidence"] == []
        assert rows["funding"]["not_found"] == [
            "BlueWave funding rounds", "bluewave.net investors",
        ]

    async def test_a_family_that_ran_also_says_what_it_could_not_establish(self, api):
        rows, _ = await coverage(api)
        assert rows["hiring"]["not_found"] == ["salary bands"]


class TestOlderPassagesAreNotGuessedIntoAFamily:
    async def test_a_passage_with_no_family_is_listed_on_its_own(self, api):
        """Evidence is immutable and was stored before families were recorded.
        Filing it under a family would claim a search found it that may not
        have."""
        rows, body = await coverage(api)
        assert [e["excerpt"] for e in body["unattributed_evidence"]] == ["A new CTO joined."]
        assert all(
            e["excerpt"] != "A new CTO joined." for r in rows.values() for e in r["evidence"]
        )
