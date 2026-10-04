"""One-shot database setup and verification.

    python setup_db.py

Reads DATABASE_URL from .env, creates the database if missing, runs migrations,
and confirms the app can reach it. Prints what it did and what to do next.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent


def fail(msg: str, hint: str = "") -> None:
    print(f"\n  FAILED  {msg}")
    if hint:
        print(f"          {hint}")
    sys.exit(1)


def main() -> None:
    env_file = HERE / ".env"
    if not env_file.exists():
        fail(
            ".env not found",
            "Copy .env.example to .env and set your PostgreSQL password.",
        )

    if "YOUR_PASSWORD_HERE" in env_file.read_text(encoding="utf-8"):
        fail(
            ".env still contains the placeholder password",
            "Edit backend/.env and replace YOUR_PASSWORD_HERE.",
        )

    try:
        from app.config import get_settings
    except Exception as exc:  # noqa: BLE001
        fail(f"settings did not load: {type(exc).__name__}: {exc}")

    settings = get_settings()
    # PostgresDsn is a MultiHostUrl in pydantic v2 — .hosts() not .host
    host = settings.database_url.hosts()[0]
    dbname = str(settings.database_url.path or "/sdg360").lstrip("/")
    print(f"  target    {host['host']}:{host['port']}/{dbname}")

    # --- create the database if it does not exist -------------------------
    import psycopg

    admin_dsn = settings.psycopg_dsn.rsplit("/", 1)[0] + "/postgres"
    try:
        with psycopg.connect(admin_dsn, connect_timeout=8, autocommit=True) as conn:
            exists = conn.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)
            ).fetchone()
            if exists:
                print(f"  database  {dbname} already exists")
            else:
                conn.execute(f'CREATE DATABASE "{dbname}"')
                print(f"  database  {dbname} created")
    except psycopg.OperationalError as exc:
        fail(
            f"could not connect: {exc}".strip(),
            "Check the password in .env and that the postgresql-x64-17 service is running.",
        )

    # --- migrate ----------------------------------------------------------
    print("  migrate   running alembic upgrade head ...")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=HERE,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        fail("alembic upgrade failed")

    with psycopg.connect(settings.psycopg_dsn, connect_timeout=8) as conn:
        rev = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        print(f"  migrate   at revision {rev[0]}")

    print("\n  OK — database ready.\n")
    print("  Next:")
    print("    ..\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --reload")
    print("    then open http://127.0.0.1:8000/api/health/ready\n")


if __name__ == "__main__":
    main()
