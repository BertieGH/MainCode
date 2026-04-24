"""Add enrichment/job_crawl diagnostic columns on prospects

Revision ID: 010
Revises: 009
Create Date: 2026-04-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("prospects", sa.Column("enrichment_strategy", sa.String(50), nullable=True))
    op.add_column("prospects", sa.Column("enrichment_error", sa.Text, nullable=True))
    op.add_column("prospects", sa.Column("job_crawl_strategy", sa.String(50), nullable=True))
    op.add_column("prospects", sa.Column("job_crawl_raw_count", sa.Integer, nullable=False, server_default="0"))
    op.add_column("prospects", sa.Column("job_crawl_error", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("prospects", "job_crawl_error")
    op.drop_column("prospects", "job_crawl_raw_count")
    op.drop_column("prospects", "job_crawl_strategy")
    op.drop_column("prospects", "enrichment_error")
    op.drop_column("prospects", "enrichment_strategy")
