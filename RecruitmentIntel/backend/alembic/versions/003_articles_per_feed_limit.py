"""Add articles_per_feed_limit to app_settings

Revision ID: 003
Revises: 002
Create Date: 2026-04-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("articles_per_feed_limit", sa.Integer, nullable=False, server_default="20"),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "articles_per_feed_limit")
