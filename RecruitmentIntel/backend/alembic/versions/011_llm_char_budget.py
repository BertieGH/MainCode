"""Add llm_article_char_budget to app_settings

Revision ID: 011
Revises: 010
Create Date: 2026-04-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("llm_article_char_budget", sa.Integer, nullable=False, server_default="3500"),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "llm_article_char_budget")
