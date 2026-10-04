"""An ICP per service, versioned per service.

The ideal customer for QA outsourcing is not the ideal customer for an AI pack,
and one global ICP can only hold their union — see `docs/10`. The house ICP on
`org_profile` stays: it answers "where do we sell at all" (regions, industries,
exclusions) and is what `scoring_config.industry_multipliers` reads its rows
from. This answers "who, within that, is this service for".

Versioned per service rather than a JSONB column on `service_catalog`, for the
reason `CLAUDE.md` gives: config is versioned and never mutated in place. A
stored strategy — and now an enrichment run — has to stay explainable against
the ICP that produced it, and an edited-in-place column makes "why did we
enrich these contacts?" unanswerable three months later.

`ON DELETE CASCADE` is safe here in a way it would not be for a shared profile:
this ICP belongs to one service and means nothing without it.

Revision ID: b7d4e9a1c260
Revises: a3f7c21d5b90
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "b7d4e9a1c260"
down_revision = "a3f7c21d5b90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "service_icp",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "service_id", UUID(as_uuid=True),
            sa.ForeignKey("service_catalog.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("icp", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        # Every table in this project carries both — see `app/database.Base`.
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("service_id", "version", name="uq_service_icp_version"),
    )
    # Exactly one active row per service — the `llm_config` pattern, enforced by
    # a partial unique index rather than by application code. Two concurrent
    # activations would otherwise both pass a check-then-write and leave the
    # service with two active ICPs and no error.
    op.create_index(
        "uq_service_icp_single_active",
        "service_icp",
        ["service_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_index("ix_service_icp_service", "service_icp", ["service_id"])


def downgrade() -> None:
    op.drop_index("ix_service_icp_service", table_name="service_icp")
    op.drop_index("uq_service_icp_single_active", table_name="service_icp")
    op.drop_table("service_icp")
