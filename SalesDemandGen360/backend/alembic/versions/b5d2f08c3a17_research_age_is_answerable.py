"""research age is answerable

`account.research_completed_at` was declared beside `research_status` and never
written. Null on all 76 accounts, including 51 marked `complete` — so the sales
prep screen, which opens on research age, would have said nobody had ever
looked at an account researched minutes earlier.

The pipeline now stamps it. This backfills what already happened, from `run`,
which has recorded `finished_at` per account all along. No value is invented:
an account with no finished run stays null, which is the truth — the column
means "when we last looked", and nobody looked.

**Not derived at read time, deliberately.** `max(run.finished_at)` is the same
number, and the prep index would need it per row; but a run belongs to an
account and is never deleted, so the two cannot disagree except by the pipeline
failing to stamp — which a test now covers. The column stays because an account
whose every family came back empty still has a look-time and has no evidence to
derive one from.

Revision ID: b5d2f08c3a17
Revises: e7a4c91b35d8
"""
from __future__ import annotations

from alembic import op

revision = "b5d2f08c3a17"
down_revision = "e7a4c91b35d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Only accounts that have actually finished a run, and only where the
    # column is still empty: a value the pipeline has since written is newer
    # than anything here and must not be overwritten.
    op.execute(
        """
        UPDATE account a
           SET research_completed_at = r.last_finished
          FROM (
                SELECT account_id, max(finished_at) AS last_finished
                  FROM run
                 WHERE finished_at IS NOT NULL
              GROUP BY account_id
               ) r
         WHERE r.account_id = a.id
           AND a.research_completed_at IS NULL
        """
    )


def downgrade() -> None:
    # Clearing the whole column would also discard what the pipeline wrote
    # after this ran, and there is no way to tell the two apart. A backfill
    # from a surviving source is re-runnable, so dropping the values is the
    # worse of the two risks; this reverses nothing on purpose.
    pass
