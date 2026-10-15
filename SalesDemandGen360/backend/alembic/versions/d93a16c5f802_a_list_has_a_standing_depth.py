"""a list has a standing depth

A default tier per list, because a list is the unit of intent. A cold Apollo
import of two hundred is a light list; a shortlist a rep is working is a deep
one. Without this the tier dialog asks the same question once per account, and
a question asked two hundred times is a question nobody reads.

**`standard`, not `light`.** A new list gets what a run would have cost before
tiers existed, minus the two sources measured at fifteen times the cost per
signal of the cheapest paid ones. Defaulting to light would be the cheapest
answer and the wrong default: a list nobody has thought about should not
quietly stop buying sources its ICPs name.

The dialog still opens on every run and the list's value only pre-selects it —
a default that could not be overridden per run would be a setting, not a
default.

Revision ID: d93a16c5f802
Revises: c8f20d47b19e
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d93a16c5f802"
down_revision = "c8f20d47b19e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "account_list",
        sa.Column(
            "research_tier",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'standard'"),
        ),
    )
    op.create_check_constraint(
        "ck_account_list_research_tier_valid",
        "account_list",
        "research_tier IN ('light', 'standard', 'deep')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_account_list_research_tier_valid", "account_list", type_="check"
    )
    op.drop_column("account_list", "research_tier")
