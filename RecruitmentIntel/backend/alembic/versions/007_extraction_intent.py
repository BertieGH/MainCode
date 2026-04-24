"""Add extraction_prompt and global_scrape_keywords settings

Revision ID: 007
Revises: 006
Create Date: 2026-04-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("global_scrape_keywords", JSON, nullable=False, server_default="[]"),
    )
    op.add_column(
        "app_settings",
        sa.Column("extraction_prompt", sa.Text, nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "extraction_prompt")
    op.drop_column("app_settings", "global_scrape_keywords")
