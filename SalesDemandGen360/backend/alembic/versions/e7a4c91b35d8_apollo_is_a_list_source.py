"""A list can come from Apollo, so `source` has to be able to say so.

`account_list.source` allowed `csv`, `manual` and `crm`. The Apollo builder
writes lists that are none of those: not a file somebody uploaded, not rows
typed in by hand, and not a sync from our own CRM — they are picked out of a
data provider's stored contacts, which is a fourth thing.

Found the way these are usually found. The build returned
`500 Internal Server Error` and the traceback said
`new row for relation "account_list" violates check constraint
ck_account_list_source_valid`, with `source` of `apollo` in the failing row.

The alternative was to write `csv` and move on, which would have been one word
cheaper and wrong: the column exists to record where a list came from, and
every list built this way would have claimed to be a file that never existed.
That matters beyond tidiness — `source` is what a later question like "which
of our lists came from the provider, and did they convert better" has to read.

Revision ID: e7a4c91b35d8
Revises: d9b2f45c17ae
"""

from __future__ import annotations

from alembic import op

revision = "e7a4c91b35d8"
down_revision = "d9b2f45c17ae"
branch_labels = None
depends_on = None

NAME = "ck_account_list_source_valid"
OLD = "source IN ('csv','manual','crm')"
NEW = "source IN ('csv','manual','crm','apollo')"


def upgrade() -> None:
    # `op.f` marks the name as final. Without it the metadata's naming
    # convention prefixes it again and the statement goes out as
    # `ck_account_list_ck_account_list_source_valid`, which does not exist —
    # the original migration used `op.f` for exactly this reason.
    op.drop_constraint(op.f(NAME), "account_list", type_="check")
    op.create_check_constraint(op.f(NAME), "account_list", NEW)


def downgrade() -> None:
    # Any Apollo-built list would fail the old constraint, so they become
    # `csv` on the way down rather than blocking the downgrade. It is the
    # nearest true thing: the rows reached the database through the CSV
    # importer either way.
    op.execute("UPDATE account_list SET source = 'csv' WHERE source = 'apollo'")
    op.drop_constraint(op.f(NAME), "account_list", type_="check")
    op.create_check_constraint(op.f(NAME), "account_list", OLD)
