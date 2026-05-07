"""One-shot SQLite -> Postgres data migration for RecruitmentIntel.

Pre-conditions
--------------
1. Postgres is up and reachable (check with `docker compose ps db`).
2. `alembic upgrade head` has run against Postgres so the schema exists.
3. RI_DATABASE_URL_SYNC in .env points at Postgres OR pass --pg explicitly.
4. The SQLite file `backend/recruitmentintel.db` still exists (unmodified).

What it does
------------
- Opens both engines (SQLite source, Postgres target).
- Walks `Base.metadata.sorted_tables` in FK-respecting order.
- For each table: SELECT * from SQLite, INSERT into Postgres in batches of
  500 with `ON CONFLICT (id) DO NOTHING` so re-runs are safe.
- Logs row counts per table.

Run
---
    cd backend
    python scripts/migrate_sqlite_to_postgres.py

Optional flags
--------------
    --sqlite path/to/source.db        (default: backend/recruitmentintel.db)
    --pg postgresql://user:pass@host:port/db   (default: $RI_DATABASE_URL_SYNC or .env)
    --batch 500                       (insert batch size)
    --dry-run                         (count rows on both sides, do nothing)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Make `from app...` imports work when run from backend/ or anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import Base

# Force-load every model so Base.metadata is fully populated. The order
# here doesn't matter — sorted_tables resolves FK dependencies later.
import app.models.signal           # noqa: F401
import app.models.prospect_list    # noqa: F401
import app.models.prospect         # noqa: F401
import app.models.job              # noqa: F401
import app.models.feed_source      # noqa: F401
import app.models.app_setting      # noqa: F401
import app.models.ingestion_run    # noqa: F401
import app.models.article          # noqa: F401
import app.models.extraction_profile  # noqa: F401
import app.models.job_prompt_profile  # noqa: F401
import app.models.backfill_run     # noqa: F401
import app.models.extraction_run   # noqa: F401


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sqlite", default="backend/recruitmentintel.db")
    p.add_argument("--pg", default=os.environ.get("RI_DATABASE_URL_SYNC", ""))
    p.add_argument("--batch", type=int, default=500)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    sqlite_path = Path(args.sqlite).resolve()
    if not sqlite_path.exists():
        print(f"ERROR: SQLite source not found: {sqlite_path}", file=sys.stderr)
        return 1

    if not args.pg or not args.pg.startswith(("postgresql://", "postgresql+")):
        print(
            "ERROR: Postgres URL not provided. Set RI_DATABASE_URL_SYNC in "
            ".env or pass --pg postgresql://user:pass@host:port/db",
            file=sys.stderr,
        )
        return 2

    sqlite_url = f"sqlite:///{sqlite_path}"
    print(f"SOURCE: {sqlite_url}")
    print(f"TARGET: {args.pg}")
    print()

    sqlite_engine = create_engine(sqlite_url)
    pg_engine = create_engine(args.pg)

    # FK-respecting order — parents before children.
    tables = list(Base.metadata.sorted_tables)
    print(f"Tables ({len(tables)}, in FK order):")
    for t in tables:
        print(f"  - {t.name}")
    print()

    grand_src, grand_dst = 0, 0

    with sqlite_engine.connect() as src, pg_engine.begin() as dst:
        # Disable FK + trigger enforcement during bulk load. SQLite doesn't
        # enforce FKs by default, so dev DBs typically have dangling refs
        # (e.g. articles.signal_id pointing at deleted signals). On Postgres
        # those would fail the load; replication-role=replica is the
        # standard way to bypass for a one-shot import. Resets at session end.
        from sqlalchemy import text as _sql_text
        dst.execute(_sql_text("SET session_replication_role = 'replica'"))

        for table in tables:
            src_rows = src.execute(select(table)).mappings().all()
            src_count = len(src_rows)
            grand_src += src_count
            if src_count == 0:
                print(f"  {table.name:30s} 0 rows — skipping")
                continue

            if args.dry_run:
                print(f"  {table.name:30s} {src_count:>6d} rows (dry run)")
                continue

            inserted = 0
            for i in range(0, src_count, args.batch):
                batch = [dict(r) for r in src_rows[i : i + args.batch]]
                stmt = pg_insert(table).values(batch)
                # Idempotent: skip rows whose id already exists. Allows re-runs
                # without crashing on UNIQUE violations.
                pk_cols = [c.name for c in table.primary_key.columns]
                if pk_cols:
                    stmt = stmt.on_conflict_do_nothing(index_elements=pk_cols)
                dst.execute(stmt)
                inserted += len(batch)

            # Verify destination count
            dst_count = dst.execute(select(table)).rowcount  # type: ignore[arg-type]
            # rowcount is unreliable for SELECT — re-count properly:
            dst_count = dst.execute(
                table.select().with_only_columns(*table.primary_key.columns)
            ).rowcount
            grand_dst += dst_count
            print(f"  {table.name:30s} src={src_count:>6d}  inserted={inserted:>6d}")

    print()
    print(f"Source rows total: {grand_src}")
    if not args.dry_run:
        print(f"Target rows total: {grand_dst}")
        if grand_src != grand_dst:
            print(
                "  WARN: row counts differ — likely pre-existing rows on the "
                "target with conflicting ids (ON CONFLICT DO NOTHING skipped them)."
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
