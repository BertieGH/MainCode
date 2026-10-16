"""Application settings.

Everything configurable lives here and is read from the environment. Nothing in
this module has a default that would work against a real database by accident —
a missing DATABASE_URL is a startup failure, not a silent fallback to SQLite.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- app ---
    app_name: str = "Sales Demand Gen360"
    environment: Literal["local", "ci", "staging", "production"] = "local"
    debug: bool = False

    # --- database ---
    # No default. An unset DATABASE_URL must fail loudly at startup rather than
    # quietly connecting somewhere unintended.
    database_url: PostgresDsn = Field(..., alias="DATABASE_URL")
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # --- security ---
    # Encryption key for stored credentials. A change to this value makes every
    # stored credential undecryptable, which is why rotation needs a re-entry
    # step rather than a redeploy.
    secret_key: str = Field(..., alias="SECRET_KEY", min_length=16)

    #: Whether every route needs a signed-in user. **On.** The UI has had a
    #: sign-in page since phase 3 of `docs/17`. The test suite turns it off
    #: (`tests/conftest.py`) so the hundreds of tests written before sign-in
    #: existed keep exercising their routes, and the ones about sign-in turn
    #: it back on.
    auth_required: bool = Field(default=True, alias="AUTH_REQUIRED")

    #: The protected super admin: always an admin, and no other admin can
    #: deactivate, delete, demote or reset the password of this account. Set in
    #: `.env` rather than in code because the repository is public — an address
    #: here is harmless, a password would not be. Unset means no super admin.
    superadmin_email: str | None = Field(default=None, alias="SUPERADMIN_EMAIL")

    # --- Claude ---
    # Optional at this phase; required from Phase 3 onward.
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    claude_model: str = "claude-opus-5"

    @field_validator("database_url")
    @classmethod
    def _require_async_driver(cls, v: PostgresDsn) -> PostgresDsn:
        """SQLAlchemy needs an async driver in the URL scheme.

        A plain ``postgresql://`` URL works with psql and with sync SQLAlchemy,
        so this mistake surfaces only as a confusing greenlet error deep in the
        first query. Catch it at startup instead.
        """
        if v.scheme not in ("postgresql+psycopg", "postgresql+asyncpg"):
            raise ValueError(
                f"DATABASE_URL must use an async driver, got scheme {v.scheme!r}. "
                "Use postgresql+psycopg://…"
            )
        return v

    @property
    def sync_database_url(self) -> str:
        """The URL Alembic and psycopg use synchronously.

        psycopg3 is both a sync and an async driver, so ``+psycopg`` is kept
        rather than stripped. Stripping it leaves a bare ``postgresql://``,
        which SQLAlchemy resolves to psycopg2 — a different, uninstalled
        package, and the resulting ModuleNotFoundError names psycopg2 rather
        than the URL that asked for it.

        asyncpg has no sync mode, so that one is swapped for psycopg.
        """
        return str(self.database_url).replace("+asyncpg", "+psycopg")

    @property
    def psycopg_dsn(self) -> str:
        """A libpq DSN for ``psycopg.connect()`` directly.

        Distinct from ``sync_database_url`` because the two consumers disagree:
        SQLAlchemy needs the ``+psycopg`` dialect suffix to pick a driver, and
        libpq rejects it as a malformed keyword. Same database, two spellings.
        """
        return str(self.database_url).replace("+psycopg", "").replace("+asyncpg", "")


@lru_cache
def get_settings() -> Settings:
    """Cached so the .env file is read once per process."""
    return Settings()  # type: ignore[call-arg]
