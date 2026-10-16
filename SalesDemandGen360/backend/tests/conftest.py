"""Test fixtures.

Tests are split by what they need:

- Most tests need no database. They override ``get_session`` so the whole suite
  runs in CI without Postgres.
- Tests marked ``@pytest.mark.db`` need a live database and are skipped when
  ``TEST_DATABASE_URL`` is unset, rather than failing.

That split matters: a suite that cannot run without a database stops being run.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

# Load .env into the process environment before anything reads it.
# pydantic-settings reads the file for Settings, but plain os.getenv does not —
# so TEST_DATABASE_URL would be invisible and every db-marked test would skip
# while appearing to pass.
_ENV = Path(__file__).resolve().parents[1] / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _, _v = _line.partition("=")
        os.environ.setdefault(_k.strip(), _v.strip())

# Settings are constructed at import time, so the environment must be complete
# before app modules load.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://unused:unused@localhost:5432/unused"
)
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-16-chars")
# Sign-in is enforced by default. Most of this suite predates it and tests a
# route, not a session; the auth and permission tests switch it back on.
os.environ.setdefault("AUTH_REQUIRED", "false")

import app as _app_package  # noqa: E402,F401  — import sets the Windows event-loop policy
from app.database import get_session  # noqa: E402
from app.main import create_app  # noqa: E402


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "db: requires a live PostgreSQL database")


class _StubResult:
    def scalar(self) -> int:
        return 1


class _StubSession:
    """Stands in for AsyncSession where the test only needs the round-trip."""

    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail

    async def execute(self, *args, **kwargs):
        if self._fail:
            raise ConnectionRefusedError("stub: database unreachable")
        return _StubResult()

    async def rollback(self) -> None:
        return None


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """Client with a healthy stub session."""

    async def _session():
        yield _StubSession()

    app.dependency_overrides[get_session] = _session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
async def client_db_down(app) -> AsyncGenerator[AsyncClient, None]:
    """Client whose database round-trip raises."""

    async def _session():
        yield _StubSession(fail=True)

    app.dependency_overrides[get_session] = _session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Database fixtures
#
# TEST_DATABASE_URL points at a *separate* database, migrated by alembic so it
# is structurally identical to development rather than built from
# metadata.create_all — which would silently skip anything a migration does by
# hand and let a broken migration pass the suite.
#
# Isolation is by TRUNCATE before each test rather than a rolled-back
# transaction, because the concurrency test needs two sessions to really commit.
# ---------------------------------------------------------------------------
TEST_DB = os.getenv("TEST_DATABASE_URL")


@pytest.fixture(autouse=True)
async def _clean_database(request):
    """Empty every table before any test marked ``db``."""
    # The role grid is cached for a few seconds; a grid saved by one test
    # must not outlive the truncate that removes it.
    from app.services.access import forget_cached_grid

    forget_cached_grid()
    if "db" not in request.keywords or not TEST_DB:
        yield
        return

    from sqlalchemy import text as _text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(TEST_DB)
    async with engine.begin() as conn:
        tables = (
            await conn.execute(
                _text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname='public' AND tablename <> 'alembic_version'"
                )
            )
        ).scalars().all()
        if tables:
            joined = ", ".join(f'"{t}"' for t in tables)
            # RESTART IDENTITY so version counters start from 1 in every test.
            await conn.execute(_text(f"TRUNCATE {joined} RESTART IDENTITY CASCADE"))
        await _seed_builtin_sources(conn)
        await _seed_prompt_templates(conn)
    await engine.dispose()
    yield


async def _seed_prompt_templates(conn) -> None:
    """Put v1 of every stage prompt back after the truncate.

    Same reason as the research sources: a migration seeds these, so every real
    database has one active row per scenario and no test should have to know
    that. Truncating them away leaves `load_prefix` resolving nothing, falling
    back to the shipped text, and quietly not exercising the stored-prompt path
    at all — a test suite that passes while the feature is bypassed.
    """
    from sqlalchemy import text as _text

    from app.services.instructions import STAGE

    for scenario, body in sorted(STAGE.items()):
        await conn.execute(
            _text(
                "INSERT INTO prompt_template (scenario, body, version, is_active) "
                "VALUES (:scenario, :body, 1, true) ON CONFLICT DO NOTHING"
            ),
            {"scenario": scenario, "body": body.strip()},
        )


async def _seed_builtin_sources(conn) -> None:
    """Put the shipped research sources back after the truncate.

    They arrive with a migration, so every real database has them and no test
    should have to know that. Truncating them away would make a test pass
    against a registry production never has — and the first thing that breaks
    is `produced_by` validation, silently, by accepting every key.

    Seeded from `query_families`, which is now the definition of what ships
    rather than the set of what is allowed. The migration keeps its own frozen
    copy on purpose: a migration has to keep producing the same rows after the
    code it came from has moved on.
    """
    from sqlalchemy import text as _text

    from app.services.query_families import QUERY_FAMILIES

    for f in QUERY_FAMILIES:
        await conn.execute(
            _text(
                "INSERT INTO research_source "
                "(key, label, description, kind, scopes, support_only, builtin, status) "
                "VALUES (:key, :label, :description, :kind, CAST(:scopes AS jsonb), "
                ":support_only, true, 'active') ON CONFLICT (key) DO NOTHING"
            ),
            {
                "key": f.key, "label": f.label, "description": f.description,
                "kind": f.runner, "scopes": json.dumps(list(f.scopes)),
                "support_only": f.support_only,
            },
        )


# --------------------------------------------------------------------------
# Fake sessions and the durability lookup
# --------------------------------------------------------------------------
class LongLivedSignalType:
    """An active signal type with a durability window wide enough to ignore.

    `store_found` derives a staleness cutoff from the active signal types, so
    every fake session that reaches it has to answer that query. A fake that
    replies with its one canned list instead handed `durability_of` whatever it
    held — a hash string, an ORM row of another kind — and the resulting
    `AttributeError` says nothing about the fake being at fault.

    Shared so there is one place to change when the lookup changes again, and
    deliberately long: a test about deduplication or about where a date lands
    should not also be a test of the staleness gate. `test_durability.py` owns
    that, against a real database.
    """

    default_ttl_days = 3650
    durability_days = None


def is_signal_type_query(stmt) -> bool:
    """Whether this statement is the durability lookup.

    Matched on the table name in the rendered SQL, following
    `test_llm_call_sites.FakeSession`: a compiled statement renders
    `FROM signal_type`, never `SignalType`, and matching the class name
    silently matches nothing.
    """
    return "FROM signal_type" in str(stmt)
