"""Add articles table for News Log

Revision ID: 005
Revises: 004
Create Date: 2026-04-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "articles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("ingestion_run_id", UUID(as_uuid=True), sa.ForeignKey("ingestion_runs.id", ondelete="CASCADE"), nullable=True),
        sa.Column("feed_source_id", UUID(as_uuid=True), sa.ForeignKey("feed_sources.id", ondelete="SET NULL"), nullable=True),
        sa.Column("feed_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("title", sa.String(1024), nullable=False, server_default=""),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("published", sa.String(255), nullable=True),
        sa.Column("verdict", sa.String(32), nullable=False, server_default="error"),
        sa.Column("llm_response", sa.Text, nullable=True),
        sa.Column("signal_id", UUID(as_uuid=True), sa.ForeignKey("signal_log.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_articles_created_at", "articles", ["created_at"])
    op.create_index("ix_articles_run_id", "articles", ["ingestion_run_id"])
    op.create_index("ix_articles_verdict", "articles", ["verdict"])


def downgrade() -> None:
    op.drop_index("ix_articles_verdict", table_name="articles")
    op.drop_index("ix_articles_run_id", table_name="articles")
    op.drop_index("ix_articles_created_at", table_name="articles")
    op.drop_table("articles")
