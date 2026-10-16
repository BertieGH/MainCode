"""roles and an audit trail

Phase 2 of `docs/17`.

**`role_grid`** says what AIOps, Marketing and DemandGen may do: a level per
module and a set of risky actions. Versioned with one active row, like every
config table, so a past day's permissions are a row rather than a guess.
Version 1 is the grid agreed on 2026-10-15, copied here as a literal rather
than imported from `permissions.DEFAULT_GRID` — a migration that reads live
code rewrites history the day that code changes. Admin is not in it; admin's
rights are computed.

**`audit_log`** is new. CLAUDE.md's invariant 9 already named it, but no table
existed. Append-only; the actor's label is stored beside the id so a row
reads the same after a rename.

Revision ID: c3a9f17e5b24
Revises: b6d2e8f41a07
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c3a9f17e5b24"
down_revision = "b6d2e8f41a07"
branch_labels = None
depends_on = None

GRID_V1 = {
    "actions": {
        "aiops": [
            "paid_research"
        ],
        "demandgen": [
            "approve_send",
            "paid_research",
            "delete_campaign"
        ],
        "marketing": [
            "paid_research"
        ]
    },
    "modules": {
        "aiops": {
            "content": "view",
            "dashboard": "edit",
            "lists": "view",
            "models_prompts": "edit",
            "outreach": "view",
            "prep": "view",
            "queues": "view",
            "rules_cadences": "view",
            "scoring": "edit",
            "sources_signals": "edit"
        },
        "demandgen": {
            "content": "view",
            "dashboard": "view",
            "lists": "edit",
            "models_prompts": "view",
            "outreach": "edit",
            "prep": "edit",
            "queues": "edit",
            "rules_cadences": "edit",
            "scoring": "view",
            "sources_signals": "view"
        },
        "marketing": {
            "content": "edit",
            "dashboard": "view",
            "lists": "edit",
            "models_prompts": "view",
            "outreach": "edit",
            "prep": "edit",
            "queues": "view",
            "rules_cadences": "view",
            "scoring": "edit",
            "sources_signals": "view"
        }
    }
}


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "role_grid",
        *_base_columns(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("grid", postgresql.JSONB(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_user.id", name="fk_role_grid_created_by_id_app_user"),
            nullable=True,
        ),
        sa.UniqueConstraint("version", name="uq_role_grid_version"),
    )
    op.execute("CREATE UNIQUE INDEX uq_role_grid_single_active ON role_grid ((true)) WHERE is_active")
    op.execute(
        sa.text("INSERT INTO role_grid (version, grid, is_active) VALUES (1, CAST(:g AS jsonb), true)")
        .bindparams(g=json.dumps(GRID_V1, sort_keys=True))
    )

    op.create_table(
        "audit_log",
        *_base_columns(),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_user.id", name="fk_audit_log_actor_id_app_user"),
            nullable=True,
        ),
        sa.Column("actor_label", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("subject_type", sa.Text(), nullable=True),
        sa.Column("subject_id", sa.Text(), nullable=True),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
    )
    op.create_index("ix_audit_log_subject", "audit_log", ["subject_type", "subject_id"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("role_grid")
