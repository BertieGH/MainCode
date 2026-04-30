"""Add backfill_runs table

Revision ID: 016
Revises: 015
Create Date: 2026-04-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "backfill_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False, server_default="country"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("processed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated", sa.Integer, nullable=False, server_default="0"),
        sa.Column("still_unknown", sa.Integer, nullable=False, server_default="0"),
        sa.Column("via_location", sa.Integer, nullable=False, server_default="0"),
        sa.Column("via_llm", sa.Integer, nullable=False, server_default="0"),
        sa.Column("message", sa.String(2048), nullable=True),
        sa.Column("trigger", sa.String(20), nullable=False, server_default="manual"),
    )
    op.create_index("ix_backfill_runs_started_at", "backfill_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_backfill_runs_started_at", table_name="backfill_runs")
    op.drop_table("backfill_runs")
