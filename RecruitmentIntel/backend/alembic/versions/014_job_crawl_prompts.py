"""Add editable job-crawl prompts + job_prompt_profiles preset table

Revision ID: 014
Revises: 013
Create Date: 2026-04-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("job_extract_prompt", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "app_settings",
        sa.Column("job_match_prompt", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "app_settings",
        sa.Column("job_classify_prompt", sa.Text(), nullable=False, server_default=""),
    )

    op.create_table(
        "job_prompt_profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("extract_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("match_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("classify_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("job_prompt_profiles")
    op.drop_column("app_settings", "job_classify_prompt")
    op.drop_column("app_settings", "job_match_prompt")
    op.drop_column("app_settings", "job_extract_prompt")
