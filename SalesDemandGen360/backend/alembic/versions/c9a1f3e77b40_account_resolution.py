"""Tier 0 — resolving an account to a real company.

Researching the wrong company fails *silently*: the evidence, signals, score
and draft all come out well-formed, about a different business, and nothing on
screen says so. A CSV row saying "Acme" is a claim about who to look at, not an
identity, and the cheapest place to catch a wrong one is a rep glancing at a
list before anything is spent.

So resolution is its own step with its own status, and the expensive stages
refuse an account that has not passed it — the same shape as the ICP gate on
enrichment. `needs_review` exists because the useful answer is often "two
plausible companies"; forcing that into a guess is what produces confident
research about the wrong Acme.

`resolution_order` sits on `enrichment_config` rather than in a new table: it
is the same kind of decision the provider order already is — which source to
ask first, changing without a deploy — and it versions alongside it.

Revision ID: c9a1f3e77b40
Revises: d4b28e15a903
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "c9a1f3e77b40"
down_revision = "d4b28e15a903"
branch_labels = None
depends_on = None

#: Apollo first because a domain lookup is the cheapest thing in the system and
#: returns firmographics as a by-product. The LLM fallback runs only when Apollo
#: has nothing — it is the one fallback already proven in this codebase, since
#: the research stages use the same web-search tooling.
DEFAULT_ORDER = '["apollo_org", "llm_web"]'


def upgrade() -> None:
    op.add_column(
        "account",
        sa.Column(
            "resolution_status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'unresolved'"),
        ),
    )
    op.create_check_constraint(
        "resolution_status_valid",
        "account",
        "resolution_status IN ('unresolved','resolved','needs_review','rejected')",
    )
    op.add_column(
        "account",
        sa.Column("resolution_confidence", sa.Numeric(4, 3), nullable=True),
    )
    #: Which source answered, and what it disagreed with. Kept because a wrong
    #: domain accepted six weeks ago needs to be traceable to whoever supplied
    #: it, not just corrected.
    op.add_column("account", sa.Column("resolved_by", sa.Text(), nullable=True))
    op.add_column(
        "account", sa.Column("resolution_note", sa.Text(), nullable=True)
    )
    op.add_column(
        "account",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "account",
        sa.Column("resolution_candidates", JSONB(), nullable=True),
    )
    op.create_index(
        "ix_account_resolution_status", "account", ["resolution_status"]
    )

    op.add_column(
        "enrichment_config",
        sa.Column(
            "resolution_order",
            JSONB(),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_ORDER}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("enrichment_config", "resolution_order")
    op.drop_index("ix_account_resolution_status", table_name="account")
    for col in (
        "resolution_candidates",
        "resolved_at",
        "resolution_note",
        "resolved_by",
        "resolution_confidence",
    ):
        op.drop_column("account", col)
    op.drop_constraint("resolution_status_valid", "account", type_="check")
    op.drop_column("account", "resolution_status")
