"""Research reuse window: results younger than this are reused, not re-bought.

Research is several model calls per account, and a second list working the
same company used to pay for all of it again — for company facts that had not
changed since last week. The window says how old an answer may be and still
count. Versioned like every other config table; seeded at 30 days.

Revision ID: b3e9d7c41a58
Revises: a8d3f5c27e19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "b3e9d7c41a58"
down_revision = "a8d3f5c27e19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_config",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "freshness_days", sa.Integer(), nullable=False, server_default=sa.text("30")
        ),
        sa.UniqueConstraint("version", name="uq_research_config_version"),
        sa.CheckConstraint(
            "freshness_days BETWEEN 1 AND 365", name="freshness_is_a_day_to_a_year"
        ),
    )
    op.create_index(
        "uq_research_config_single_active",
        "research_config",
        [sa.text("(true)")],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.execute(
        "INSERT INTO research_config (version, is_active, freshness_days) VALUES (1, true, 30)"
    )


def downgrade() -> None:
    op.drop_index("uq_research_config_single_active", table_name="research_config")
    op.drop_table("research_config")
