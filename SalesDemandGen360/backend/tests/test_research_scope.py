"""Where a research family is allowed to run.

Found by measuring: three contacts cost 138 model calls and produced three
passages. `job_board` — a company's applicant-tracking board — had run once
per *person*, searching for "Piper Jordan jobs greenhouse" under each of their
names. Its registry row says `scopes: ["company"]`, and the filter honouring
that only applied to families the registry knew. The row was missing, so the
family ran everywhere.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services.research import build_plan

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"),
]


@pytest.fixture
async def session():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
        await s.rollback()
    await engine.dispose()


async def families(session, *, scope: str, sources: list[str]) -> set[str]:
    plan = await build_plan(session, scope=scope, type_keys=None, source_keys=sources)
    return {f.family for f in plan.families}


class TestAFamilyRunsOnlyWhereItsScopeAllows:
    async def test_a_company_source_is_not_planned_for_a_person(self, session):
        await session.execute(text(
            "INSERT INTO research_source (key, label, description, kind, scopes, status) "
            "VALUES ('co_only_test', 'Company only', 'd', 'search', '[\"company\"]'::jsonb, 'active') "
            "ON CONFLICT (key) DO NOTHING"
        ))
        await session.flush()
        assert "co_only_test" in await families(session, scope="company", sources=["co_only_test"])
        assert "co_only_test" not in await families(session, scope="contact", sources=["co_only_test"])

    async def test_a_source_the_registry_does_not_know_is_company_scoped(self, session):
        """The permissive reading is what let `job_board` run per person. An
        unknown family is a company family until something says otherwise."""
        assert "ghost_family" in await families(session, scope="company", sources=["ghost_family"])
        assert "ghost_family" not in await families(session, scope="contact", sources=["ghost_family"])

    async def test_a_contact_source_still_runs_for_a_person(self, session):
        await session.execute(text(
            "INSERT INTO research_source (key, label, description, kind, scopes, status) "
            "VALUES ('person_only_test', 'Person only', 'd', 'search', '[\"contact\"]'::jsonb, 'active') "
            "ON CONFLICT (key) DO NOTHING"
        ))
        await session.flush()
        assert "person_only_test" in await families(session, scope="contact", sources=["person_only_test"])
        assert "person_only_test" not in await families(session, scope="company", sources=["person_only_test"])
