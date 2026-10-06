"""Give the headcount a date, and keep the number it replaced.

`account.employee_count` was a single undated integer, written **once**:

    if best.employee_count and not account.employee_count:
        account.employee_count = int(best.employee_count)

So a second resolution run never refreshed it, nothing recorded when it was
true, and the moment it did change the previous value was gone. Three problems
that no better data source fixes, and together they make a headcount delta —
the signal a growing company emits before it announces anything — impossible to
compute however the number arrives.

Three columns rather than a history table, deliberately. The signal only ever
reads the last two observations ("grew from 30 to 33 since March"), and a table
would add a join to every screen that shows a size band for a series nobody
queries. If a longer series earns its place later, these columns are what it
would be built from.

* `employee_count_as_of` — when the current number was observed. **Ours, not
  theirs**: a directory page carries no date, so the only honest timestamp is
  when we looked.
* `employee_count_before` / `employee_count_before_as_of` — the last *different*
  number and when it was seen. Re-observing the same number refreshes `as_of`
  only, so the pair always spans a real change rather than the last two runs.

Nothing is backfilled. Eight of fifty-seven accounts carry a count and none of
them has a date worth inventing — dating them today would claim we observed in
October what may have arrived in a September CSV.

Revision ID: a7e1d4c92f85
Revises: f2c8b4e71a93
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a7e1d4c92f85"
down_revision = "f2c8b4e71a93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("account", sa.Column("employee_count_as_of", sa.Date(), nullable=True))
    op.add_column("account", sa.Column("employee_count_before", sa.Integer(), nullable=True))
    op.add_column(
        "account", sa.Column("employee_count_before_as_of", sa.Date(), nullable=True)
    )
    op.create_check_constraint(
        "ck_account_headcount_is_not_negative",
        "account",
        "(employee_count IS NULL OR employee_count >= 0) AND "
        "(employee_count_before IS NULL OR employee_count_before >= 0)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_account_headcount_is_not_negative", "account", type_="check")
    op.drop_column("account", "employee_count_before_as_of")
    op.drop_column("account", "employee_count_before")
    op.drop_column("account", "employee_count_as_of")
