"""Add keyword_hits to articles

Revision ID: 009
Revises: 008
Create Date: 2026-04-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "articles",
        sa.Column("keyword_hits", JSON, nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("articles", "keyword_hits")
