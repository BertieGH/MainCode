"""one default depth for the installation

A list could say how deep its research goes; nothing could say it for the
installation, so four lists meant four places to change one decision.

`research_config.default_tier` is that one place. It sits beside
`freshness_days`, which is the same kind of fact — how research spends — and
is versioned for the same reason: a run from last month must still be
explicable after the figure changes.

**`account_list.research_tier` becomes nullable, and null means inherit.**
Without that there is no way for a list to say "whatever the installation
says": every list would hold a frozen copy of the default from the day it was
made, and changing the installation's answer would change nothing.

The existing `standard` rows are set to null. Nobody chose `standard` on them
— the column default did, one day ago — and leaving them set would make the
new app-wide setting appear broken on every list that already exists. The one
list explicitly set to `light` keeps it.

Revision ID: f4c7e0a92b31
Revises: d93a16c5f802
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f4c7e0a92b31"
down_revision = "d93a16c5f802"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "research_config",
        sa.Column(
            "default_tier", sa.Text(), nullable=False, server_default=sa.text("'standard'")
        ),
    )
    op.create_check_constraint(
        "ck_research_config_default_tier_valid",
        "research_config",
        "default_tier IN ('light', 'standard', 'deep')",
    )

    op.alter_column("account_list", "research_tier", nullable=True)
    op.alter_column("account_list", "research_tier", server_default=None)
    # Null is "inherit". See the note above: these were never chosen.
    op.execute("UPDATE account_list SET research_tier = NULL WHERE research_tier = 'standard'")


def downgrade() -> None:
    op.execute("UPDATE account_list SET research_tier = 'standard' WHERE research_tier IS NULL")
    op.alter_column(
        "account_list",
        "research_tier",
        nullable=False,
        server_default=sa.text("'standard'"),
    )
    op.drop_constraint(
        "ck_research_config_default_tier_valid", "research_config", type_="check"
    )
    op.drop_column("research_config", "default_tier")
