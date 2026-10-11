"""the ledger records grounding

`llm_call` recorded tokens and duration, which is most of a call and almost
none of its cost. Grounding is billed per request, not per token, and on this
installation it is roughly four fifths of what a research run costs — and
nothing anywhere recorded whether a call used it.

That gap is why a monthly spend cap arrived as a surprise rather than as a
number climbing on a screen. Tokens were visible and cheap; the expensive
thing was invisible.

One boolean. The adapter already knows — it attaches `googleSearch` only when
the stage's prefix carries tools — so this is recording a decision that was
already being made rather than inferring one afterwards.

Revision ID: f1c8d5a93e27
Revises: d4a7c3e18b25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f1c8d5a93e27"
down_revision = "d4a7c3e18b25"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_call",
        sa.Column(
            "grounded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # Rows written before this column existed are left `false` rather than
    # guessed at from the scenario. A guess would make the first weeks of the
    # cost chart confidently wrong, which is worse than a chart that starts
    # where the measurement does.


def downgrade() -> None:
    op.drop_column("llm_call", "grounded")
