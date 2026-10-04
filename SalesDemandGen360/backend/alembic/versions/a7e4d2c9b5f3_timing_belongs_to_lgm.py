"""Timing belongs to La Growth Machine, not here.

Two fields were inventing a schedule Gen360 has no authority over:

* `cadence_shape.span_days` was typed by a rep at registration, because LGM's
  API does not expose step timing anywhere — `/campaigns/:id` carries none,
  `/campaigns/:id/settings` is a 404, and `/campaigns/:id/messages` gives
  order and channel but no delay. A number entered to satisfy a NOT NULL is
  not a fact about the sequence.
* `touch.day_offset` was **authored by the model**: the drafting schema asked
  for a day per touch, and the arc was then validated against that typed span.
  Two guesses checking each other. Invariant 6 says Gen360 never authors a
  cadence, and a schedule is part of one.

Both become nullable rather than dropped. Rows written before this knew no
better, but the numbers they hold are real history — a touch that already sent
on day 3 sent on day 3 — and evidence is never deleted (invariant 2). New rows
leave them NULL, which reads as "LGM decides", and the screens say so.

Revision ID: a7e4d2c9b5f3
Revises: f3a6c9e2b1d8
"""

from __future__ import annotations

from alembic import op

revision = "a7e4d2c9b5f3"
down_revision = "f3a6c9e2b1d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("cadence_shape", "span_days", nullable=True)
    op.drop_constraint("span_positive", "cadence_shape", type_="check")
    op.create_check_constraint(
        "span_positive", "cadence_shape", "span_days IS NULL OR span_days > 0"
    )

    op.alter_column("touch", "day_offset", nullable=True)
    op.drop_constraint("day_offset_non_negative", "touch", type_="check")
    op.create_check_constraint(
        "day_offset_non_negative", "touch", "day_offset IS NULL OR day_offset >= 0"
    )


def downgrade() -> None:
    # Irreversible in the honest direction: going back means inventing a span
    # for every shape registered since, which is the thing this removed. The
    # columns are restored NOT NULL only if nothing relies on the absence.
    op.drop_constraint("day_offset_non_negative", "touch", type_="check")
    op.create_check_constraint("day_offset_non_negative", "touch", "day_offset >= 0")
    op.alter_column("touch", "day_offset", nullable=False)

    op.drop_constraint("span_positive", "cadence_shape", type_="check")
    op.create_check_constraint("span_positive", "cadence_shape", "span_days > 0")
    op.alter_column("cadence_shape", "span_days", nullable=False)
