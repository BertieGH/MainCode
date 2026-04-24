"""Add job-targeting settings + Job.match_target

Revision ID: 012
Revises: 011
Create Date: 2026-04-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("job_target_titles", sa.JSON(), nullable=True),
    )
    op.add_column(
        "app_settings",
        sa.Column("job_max_listing_pages", sa.Integer(), nullable=False, server_default="4"),
    )
    op.add_column(
        "app_settings",
        sa.Column("job_max_subcategory_pages", sa.Integer(), nullable=False, server_default="6"),
    )
    op.add_column(
        "jobs",
        sa.Column("match_target", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("jobs", "match_target")
    op.drop_column("app_settings", "job_max_subcategory_pages")
    op.drop_column("app_settings", "job_max_listing_pages")
    op.drop_column("app_settings", "job_target_titles")
