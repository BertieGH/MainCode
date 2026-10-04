"""A signal type can say what to look for, and types can share a search.

Research ran a closed set of query families defined in code, and a signal type
reached a search only by claiming one. Adding "budget cycle disclosed" meant
adding a family, which meant a deploy — and an unrunnable family reports as a
permanent coverage gap, which is why the set was closed in the first place.

`search_instruction` moves the instruction onto the type, where the person who
knows what they want to find can write it. `search_group` is what stops that
costing a call per type: types that read the same sources share one search.

Neither replaces `produced_by`. A family is still how a *non-search* source is
named — the company-site fetch, Apollo's waterfall, a rep's keyboard — and how
several types share an existing search.

Revision ID: f2a7c91b4e08
Revises: d1f4b7a92c60
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f2a7c91b4e08"
down_revision = "d1f4b7a92c60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("signal_type", sa.Column("search_instruction", sa.Text(), nullable=True))
    op.add_column("signal_type", sa.Column("search_group", sa.Text(), nullable=True))
    op.create_index(
        "ix_signal_type_search_group", "signal_type", ["search_group"],
        postgresql_where=sa.text("search_group IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_signal_type_search_group", table_name="signal_type")
    op.drop_column("signal_type", "search_group")
    op.drop_column("signal_type", "search_instruction")
