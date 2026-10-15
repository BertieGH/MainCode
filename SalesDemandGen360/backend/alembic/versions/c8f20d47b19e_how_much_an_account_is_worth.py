"""how much an account is worth

A tier per source, so a rep can say how much a given account deserves
spending on rather than every run buying everything.

**The tiers are measured, not guessed.** Signals produced per source over the
first week, against what each costs a run:

    fast_sweep              67 signals   $0.035   always
    trade_press             58 signals   $0.035   light
    linkedin_index          23 signals   2 credits (SERP)
    company_data_providers  16 signals   $0.035   standard
    company_site            10 signals   free
    ats_boards               6 signals   free
    conference_circuit       4 signals   $0.035   deep
    regulators_and_registers 4 signals   $0.035   deep

Light reaches 85% of the signals for 29% of the cost. The two deep sources
are 15× dearer per signal than the two light paid ones, which is why they
stop being bought by default — they are demoted rather than deprecated,
because they have produced signals and the registry rule protects that.

**A ceiling, not another reducer.** The reuse window, the scan's per-family
plan and the LinkedIn waterfall all subtract from what a run buys; this is
the only thing that sets the maximum. A deep run on a dead account still
costs light money, because the scan gates it.

Revision ID: c8f20d47b19e
Revises: e7b4d2a51c93
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c8f20d47b19e"
down_revision = "e7b4d2a51c93"
branch_labels = None
depends_on = None

#: Everything not named here stays light, which is the safe default: a source
#: nobody has tiered keeps being bought exactly as it was.
_DEMOTED = {
    "standard": ("company_data_providers",),
    "deep": ("conference_and_podcast_circuit", "regulators_and_registers"),
}


def upgrade() -> None:
    op.add_column(
        "research_source",
        sa.Column(
            "tier", sa.Text(), nullable=False, server_default=sa.text("'light'")
        ),
    )
    op.create_check_constraint(
        "ck_research_source_tier_valid",
        "research_source",
        "tier IN ('light', 'standard', 'deep')",
    )
    for tier, keys in _DEMOTED.items():
        op.execute(
            sa.text(
                "UPDATE research_source SET tier = :tier WHERE key = ANY(:keys)"
            ).bindparams(tier=tier, keys=list(keys))
        )


def downgrade() -> None:
    op.drop_constraint(
        "ck_research_source_tier_valid", "research_source", type_="check"
    )
    op.drop_column("research_source", "tier")
