"""A minimum priority band to join a queue.

The score ranked the book and gated nothing: a queue took any account with a
confirmed identity. That is the right default — nothing thin can reach a send
anyway, since it has no threads to approve — but a rep working a large book
wants the weak ones kept out of the queue rather than filtered by eye.

`low` means no restriction, and is the default so behaviour does not change
until somebody raises it. Above `low`, an account with no qualification at all
is refused too: "not qualified yet" is a different instruction from "too weak",
and both are better than silently queueing something nobody has judged.

It lives on `scoring_config` because it is expressed in bands, and the bands
are defined there — raise a cut-off and this moves with it.

Revision ID: d1f4b7a92c60
Revises: c7e2a9b4d153
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d1f4b7a92c60"
down_revision = "c7e2a9b4d153"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scoring_config",
        sa.Column(
            "min_queue_band", sa.Text(), nullable=False, server_default=sa.text("'low'")
        ),
    )
    op.create_check_constraint(
        "min_queue_band_valid", "scoring_config", "min_queue_band IN ('low','medium','high')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_scoring_config_min_queue_band_valid", "scoring_config", type_="check")
    op.drop_column("scoring_config", "min_queue_band")
