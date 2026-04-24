"""Add gemini_paid_api_key + gemini_tier to app_settings

Revision ID: 013
Revises: 012
Create Date: 2026-04-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("gemini_paid_api_key", sa.String(512), nullable=False, server_default=""),
    )
    op.add_column(
        "app_settings",
        sa.Column("gemini_tier", sa.String(10), nullable=False, server_default="free"),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "gemini_tier")
    op.drop_column("app_settings", "gemini_paid_api_key")
