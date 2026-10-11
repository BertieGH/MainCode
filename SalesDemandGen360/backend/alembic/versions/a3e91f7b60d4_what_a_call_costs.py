"""what a call costs

Two tables, for the two halves of a bill nothing could add up.

`model_price` is a versioned config like every other: one active row holding a
price per model. Prices change, and hard-coding them puts a number on screen
that goes quietly wrong — which is worse than no number, because nobody
re-checks a figure that looks authoritative. Versioned so that last month's
total is still explicable after a price rise.

`serp_call` records what a search provider charged. Searlo returns its credit
cost on every response; it was read, written to a log line, and dropped. A
balance alone cannot say which run spent what, so a run that quietly costs ten
times its neighbours is invisible until the credits are gone.

Together with `llm_call.grounded`, added separately, these are what the
Monitoring screen needs to stop estimating the expensive half of a research
run.

Revision ID: a3e91f7b60d4
Revises: f1c8d5a93e27
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a3e91f7b60d4"
down_revision = "f1c8d5a93e27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_price",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        # {model: {input_per_m, output_per_m, grounded_per_call}}. One row per
        # version holding every model, rather than a row per model: a price
        # change is a moment in time across the sheet, and versioning the
        # sheet is what makes "why was March cheaper" answerable.
        sa.Column("prices", postgresql.JSONB(), nullable=False),
        sa.Column(
            "currency", sa.Text(), nullable=False, server_default=sa.text("'USD'")
        ),
        sa.Column("note", sa.Text()),
    )
    # The same guarantee every other config table has: exactly one active row.
    op.create_index(
        "uq_model_price_active",
        "model_price",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "serp_call",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("provider", sa.Text(), nullable=False),
        # Both nullable: a trial from the settings screen belongs to no run and
        # no account, and refusing to record it would hide the searches a
        # person makes while tuning a source.
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("run.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("account.id", ondelete="SET NULL"),
        ),
        sa.Column("family", sa.Text()),
        sa.Column("queries", sa.Integer(), nullable=False, server_default="0"),
        # What the provider said it charged, not what we think it should have.
        sa.Column("credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("error", sa.Text()),
    )
    op.create_index("ix_serp_call_created", "serp_call", [sa.text("created_at DESC")])
    op.create_index("ix_serp_call_run", "serp_call", ["run_id"])


def downgrade() -> None:
    op.drop_table("serp_call")
    op.drop_index("uq_model_price_active", table_name="model_price")
    op.drop_table("model_price")
