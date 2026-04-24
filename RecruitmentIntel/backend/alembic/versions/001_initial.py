"""Initial tables

Revision ID: 001
Revises: None
Create Date: 2026-04-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "signal_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("industry", sa.String(100), nullable=False),
        sa.Column("funding_round", sa.String(50), nullable=False),
        sa.Column("amount", sa.BigInteger, default=0),
        sa.Column("location", sa.String(255), default=""),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("source_url", sa.String(2048), unique=True, nullable=False),
        sa.Column("source_title", sa.String(512), default=""),
        sa.Column("raw_text", sa.Text, default=""),
        sa.Column("extraction_status", sa.String(20), default="complete"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "prospect_lists",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(1024), default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "prospects",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("list_id", UUID(as_uuid=True), sa.ForeignKey("prospect_lists.id", ondelete="CASCADE"), nullable=False),
        sa.Column("signal_id", UUID(as_uuid=True), sa.ForeignKey("signal_log.id"), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("industry", sa.String(100), nullable=False),
        sa.Column("funding_round", sa.String(50), nullable=False),
        sa.Column("amount", sa.BigInteger, default=0),
        sa.Column("location", sa.String(255), default=""),
        sa.Column("website", sa.String(2048), nullable=True),
        sa.Column("linkedin_url", sa.String(2048), nullable=True),
        sa.Column("careers_url", sa.String(2048), nullable=True),
        sa.Column("enrichment_status", sa.String(20), default="not_started"),
        sa.Column("job_crawl_status", sa.String(20), default="not_started"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("prospect_id", UUID(as_uuid=True), sa.ForeignKey("prospects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("list_id", UUID(as_uuid=True), sa.ForeignKey("prospect_lists.id", ondelete="CASCADE"), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("department", sa.String(100), default="Other"),
        sa.Column("seniority", sa.String(50), default="Unknown"),
        sa.Column("job_type", sa.String(50), default="Full-time"),
        sa.Column("location", sa.String(255), default=""),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("skills", JSON, default=[]),
        sa.Column("discovered_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "feed_sources",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("feed_type", sa.String(50), nullable=False),
        sa.Column("keywords", JSON, default=[]),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("last_fetched", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_failures", sa.Integer, default=0),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("jobs")
    op.drop_table("prospects")
    op.drop_table("prospect_lists")
    op.drop_table("signal_log")
    op.drop_table("feed_sources")
