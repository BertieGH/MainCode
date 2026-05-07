"""Add extraction_runs table

Revision ID: 018
Revises: 017
Create Date: 2026-05-06

The ExtractionRun model was introduced in commit 0bae75a
(feat(news-log): batched LLM extraction) but only got created on SQLite
via Base.metadata.create_all() — not via alembic. Anyone running
`alembic upgrade head` against a fresh Postgres before this migration
will be missing the table, breaking POST /articles/extract.

This migration is idempotent on Postgres via `IF NOT EXISTS` so it's
safe even if the table was already created out-of-band (as it was on
the dev DB during the SQLite→Postgres data migration).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "018"
down_revision: Union[str, None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.has_table(bind, "extraction_runs"):
        # Already created out-of-band (Base.metadata.create_all or earlier
        # patch). Skip rather than crash with "relation already exists".
        return

    op.create_table(
        "extraction_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("processed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("funding", sa.Integer, nullable=False, server_default="0"),
        sa.Column("not_funding", sa.Integer, nullable=False, server_default="0"),
        sa.Column("parse_failed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("validation_failed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("service_unavailable", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Integer, nullable=False, server_default="0"),
        sa.Column("message", sa.String(2048), nullable=True),
        sa.Column("trigger", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("force", sa.Boolean, nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_table("extraction_runs")
