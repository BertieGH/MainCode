"""Add country column to articles

Revision ID: 015
Revises: 014
Create Date: 2026-04-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "articles",
        sa.Column("country", sa.String(8), nullable=False, server_default=""),
    )
    op.create_index("ix_articles_country", "articles", ["country"])


def downgrade() -> None:
    op.drop_index("ix_articles_country", table_name="articles")
    op.drop_column("articles", "country")
