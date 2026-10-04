"""A cadence shape names the LGM audience its campaign runs over.

La Growth Machine has no "enrol this lead" call: a campaign runs over an
audience, and a person is enrolled by being written into it. So a registered
shape needs both halves — the campaign whose steps and timing it describes, and
the audience that campaign reads. Nullable: a shape registered before this
cannot send until somebody fills it in, and saying so is better than guessing a
name.

Revision ID: d5c1a8f3e7b2
Revises: c4f8b2e6a1d7
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "d5c1a8f3e7b2"
down_revision = "c4f8b2e6a1d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cadence_shape", sa.Column("lgm_audience_name", sa.Text(), nullable=True))
    op.add_column("cadence_shape", sa.Column("lgm_audience_id", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("cadence_shape", "lgm_audience_id")
    op.drop_column("cadence_shape", "lgm_audience_name")
