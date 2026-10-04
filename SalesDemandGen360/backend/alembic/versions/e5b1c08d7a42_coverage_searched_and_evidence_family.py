"""Coverage keeps what it searched for; evidence keeps which family found it.

Two gaps a rep hit on the coverage tab. An `empty` family said "nothing found"
and nothing more — not what had been looked for, which is the part that makes
an empty result worth trusting. And a family that `ran` could not be opened to
see what it found: evidence recorded its run, never its family.

Both additive. `evidence.family` is nullable and is not backfilled. Evidence is
immutable (`docs/01` invariant 2), and a row stored before this revision
genuinely does not know which family found it — the screen says so rather than
guessing.

Revision ID: e5b1c08d7a42
Revises: c9a1f3e77b40
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "e5b1c08d7a42"
down_revision = "c9a1f3e77b40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "research_coverage",
        sa.Column(
            "not_found",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column("evidence", sa.Column("family", sa.Text(), nullable=True))
    op.create_index("evidence_by_run_family", "evidence", ["run_id", "family"])


def downgrade() -> None:
    op.drop_index("evidence_by_run_family", table_name="evidence")
    op.drop_column("evidence", "family")
    op.drop_column("research_coverage", "not_found")
