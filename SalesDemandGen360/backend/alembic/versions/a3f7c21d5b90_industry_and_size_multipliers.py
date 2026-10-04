"""Replace archetype with industry + derived size band.

`archetype` held two taxonomies in one column — business model (`saas`,
`agency`, `ecommerce`) and size (`enterprise`, `smb`, `startup`) — so a SaaS
startup could only be stored as one of the two things it plainly was, and the
multipliers for the other could never apply. Sector, which is what the ICP
actually names, had nowhere to go at all.

The business-model half becomes `industry`, keyed on a normalised form of
`account.industry` so a spreadsheet's "FinTech" and an ICP's "Fintech" reach the
same multiplier row. The size half becomes a band derived from `employee_count`
at read time — a fact rather than a judgement, needing no classifier, no
confidence score and no `unknown` sentinel stored on the row.

**This drops rather than deprecates**, which is a deliberate exception to the
project's usual rule and was authorised once, explicitly, while the database
held nothing but throwaway test data. `reasons["_archetype"]` on existing
qualifications is not migrated because no real qualification exists to protect.
Once real ones do, deprecation is the only correct move — see `docs/09`.

Revision ID: a3f7c21d5b90
Revises: 08c80c172beb
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "a3f7c21d5b90"
down_revision = "08c80c172beb"
branch_labels = None
depends_on = None

EMPTY = sa.text("'{}'::jsonb")


def upgrade() -> None:
    op.add_column(
        "scoring_config",
        sa.Column("industry_multipliers", JSONB, nullable=False, server_default=EMPTY),
    )
    op.add_column(
        "scoring_config",
        sa.Column("size_multipliers", JSONB, nullable=False, server_default=EMPTY),
    )
    op.drop_column("scoring_config", "archetype_multipliers")

    op.add_column("account", sa.Column("industry_key", sa.Text(), nullable=True))
    # Backfill with the same normalisation `scoring.normalise_industry` applies:
    # trimmed, internal whitespace collapsed, case-folded. Done in SQL so the
    # existing rows match what new writes will produce, rather than only
    # matching after something touches them.
    op.execute(
        """
        UPDATE account
           SET industry_key = lower(regexp_replace(btrim(industry), '\\s+', ' ', 'g'))
         WHERE industry IS NOT NULL AND btrim(industry) <> ''
        """
    )
    op.create_index("ix_account_industry_key", "account", ["industry_key"])

    op.drop_constraint("archetype_valid", "account", type_="check")
    op.drop_column("account", "archetype_confidence")
    op.drop_column("account", "archetype")


def downgrade() -> None:
    op.add_column(
        "account",
        sa.Column(
            "archetype", sa.Text(), nullable=False, server_default=sa.text("'unknown'")
        ),
    )
    op.add_column("account", sa.Column("archetype_confidence", sa.Numeric(4, 3), nullable=True))
    op.create_check_constraint(
        "archetype_valid",
        "account",
        "archetype IN ('saas','agency','ecommerce','enterprise','smb','startup','unknown')",
    )

    op.drop_index("ix_account_industry_key", table_name="account")
    op.drop_column("account", "industry_key")

    op.add_column(
        "scoring_config",
        sa.Column("archetype_multipliers", JSONB, nullable=False, server_default=EMPTY),
    )
    op.drop_column("scoring_config", "size_multipliers")
    op.drop_column("scoring_config", "industry_multipliers")
