"""Phase 0 acceptance: the app boots, both health endpoints behave, and the
settings guard rejects a configuration that would fail confusingly later.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


class TestHealth:
    async def test_liveness_is_ok(self, client):
        r = await client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["app"] == "Sales Demand Gen360"

    async def test_liveness_does_not_touch_the_database(self, client_db_down):
        """Liveness must stay green when the database is down.

        If it did not, one database blip would pull every instance out of the
        load balancer and turn a degraded service into an outage.
        """
        r = await client_db_down.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    async def test_readiness_reports_up(self, client):
        r = await client.get("/api/health/ready")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ready"
        assert body["database"] == "up"
        assert body["latency_ms"] >= 0

    async def test_readiness_reports_503_when_database_is_down(self, client_db_down):
        r = await client_db_down.get("/api/health/ready")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "degraded"
        assert body["database"] == "down"

    async def test_readiness_detail_does_not_leak_the_connection_string(
        self, client_db_down
    ):
        """The failure detail is the exception type, never its message.

        A psycopg connection error message contains the DSN, and therefore the
        password. This endpoint is typically unauthenticated.
        """
        body = (await client_db_down.get("/api/health/ready")).json()
        assert body["detail"] == "ConnectionRefusedError"
        assert "://" not in body["detail"]
        assert "unused" not in body["detail"]


class TestSettingsGuards:
    def test_rejects_a_url_without_an_async_driver(self):
        """postgresql:// works for psql and sync SQLAlchemy but not for us.

        Left unguarded it surfaces as a greenlet error on the first query,
        which is a long way from the actual mistake.
        """
        with pytest.raises(ValidationError) as exc:
            Settings(DATABASE_URL="postgresql://u:p@localhost:5432/db")
        assert "async driver" in str(exc.value)

    def test_accepts_psycopg_driver(self):
        s = Settings(DATABASE_URL="postgresql+psycopg://u:p@localhost:5432/db")
        assert s.database_url.scheme == "postgresql+psycopg"

    def test_sync_url_keeps_psycopg_for_alembic(self):
        """psycopg3 is both sync and async, so it is kept, not stripped.

        A bare postgresql:// URL resolves to psycopg2 — a different package
        that is not installed — and the error names psycopg2 rather than the
        URL that asked for it.
        """
        s = Settings(DATABASE_URL="postgresql+psycopg://u:p@localhost:5432/db")
        assert s.sync_database_url.startswith("postgresql+psycopg://")

    def test_sync_url_swaps_asyncpg_which_has_no_sync_mode(self):
        s = Settings(DATABASE_URL="postgresql+asyncpg://u:p@localhost:5432/db")
        assert s.sync_database_url.startswith("postgresql+psycopg://")

    def test_psycopg_dsn_drops_the_dialect_suffix_for_libpq(self):
        """libpq rejects '+psycopg' as a malformed keyword.

        SQLAlchemy needs it to pick a driver; psycopg.connect() needs it gone.
        Same database, two spellings, so both are named explicitly.
        """
        s = Settings(DATABASE_URL="postgresql+psycopg://u:p@localhost:5432/db")
        assert s.psycopg_dsn == "postgresql://u:p@localhost:5432/db"

    def test_missing_database_url_is_a_startup_failure(self, monkeypatch):
        """No silent fallback. An unset DATABASE_URL must not quietly work."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(ValidationError):
            Settings(_env_file=None)
