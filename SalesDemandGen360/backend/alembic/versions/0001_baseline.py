"""baseline — establish the migration chain

Deliberately empty of tables. Phase 0 proves the migration machinery works
against a real database; Phase 1 adds the configuration domain on top.

It does check one thing: that ``gen_random_uuid()`` resolves. Every table in
this project uses it as a server default, and it is built in from PostgreSQL 13
onward — but on an older server it fails at the first INSERT rather than at
migration time, which is a much worse place to discover it.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    version = conn.execute(sa.text("SHOW server_version_num")).scalar()
    if int(version) < 130000:
        raise RuntimeError(
            f"PostgreSQL 13+ required for gen_random_uuid(); server reports {version}."
        )

    # Fail here, loudly, rather than on a future INSERT.
    conn.execute(sa.text("SELECT gen_random_uuid()"))


def downgrade() -> None:
    pass
