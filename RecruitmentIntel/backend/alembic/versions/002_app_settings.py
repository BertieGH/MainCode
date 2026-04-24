"""Add app_settings singleton table

Revision ID: 002
Revises: 001
Create Date: 2026-04-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("llm_provider", sa.String(20), nullable=False, server_default="gemini"),
        sa.Column("gemini_api_key", sa.String(512), nullable=False, server_default=""),
        sa.Column("gemini_model", sa.String(100), nullable=False, server_default="gemini-2.0-flash"),
        sa.Column("ollama_host", sa.String(512), nullable=False, server_default="http://localhost:11434"),
        sa.Column("ollama_model", sa.String(100), nullable=False, server_default="llama3"),
        sa.Column("fetch_interval_hours", sa.Integer, nullable=False, server_default="2"),
        sa.Column("career_patterns", JSON, nullable=False, server_default="[]"),
        sa.Column("fallback_google", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("fallback_linkedin", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("ats_detection", JSON, nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
