"""who a call was for

The ledger recorded what a call cost and never who it was for. Every figure
on the cost screen is therefore a scenario-level total: it can say
`company_research` is 746 calls, and cannot say which account owns one of
them. So the question a cost screen exists to answer — *which research cost
ten times its neighbours, and why* — had no column behind it.

Four id columns plus a scope, because the stages differ in what they know.
Research knows its run and its account. Drafting knows its campaign. A trial
from a settings screen knows none of them and is still worth counting.

**No foreign keys, which is the whole point of this note.** The first version
had all four, and it silently destroyed the ledger. `_record_call` writes in a
transaction of its own — deliberately, so that a failed call's row survives
the rollback that follows it — and `run_research` only *flushes* the run row
on its sequential path. A separate transaction cannot see a flush, so every
attributed row raised `ForeignKeyViolation`, the guard that keeps bookkeeping
from breaking the work it measures swallowed it, and the row was lost.
Measured before this was written: a flushed-but-uncommitted run produced
**zero** ledger rows. Referential integrity cannot be asked of a writer that
is outside the transaction creating the rows it points at.

So these are ids, not references. A deleted account leaves its spend behind
pointing at nothing, which is the right answer anyway: what was spent
happened, and a bill that shrinks when somebody tidies up is not a bill.

`scope` is separate from `contact_id` on purpose. The contact pass makes **one
call for every person in a family**, not one per person, so a row about people
usually names none of them — and a null `contact_id` therefore cannot mean
"this was company work". Asking one column to carry both facts would file the
entire contact half of a research bill under the company.

Nullable throughout, and null on history: rows written before this belong to
runs nobody recorded. Queries filter on NOT NULL, so the unattributed past is
excluded and counted rather than smeared across whoever ran first.

Revision ID: e7b4d2a51c93
Revises: a3e91f7b60d4
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e7b4d2a51c93"
down_revision = "a3e91f7b60d4"
branch_labels = None
depends_on = None

_IDS = ("run_id", "account_id", "contact_id", "campaign_id")


def upgrade() -> None:
    for column in _IDS:
        op.add_column(
            "llm_call", sa.Column(column, postgresql.UUID(as_uuid=True), nullable=True)
        )

    # Text + CHECK like every other enum-like column here. Nullable, and null
    # on history: a call made before this existed had no scope recorded, and
    # 'company' would be a guess that reads as a measurement.
    op.add_column("llm_call", sa.Column("scope", sa.Text()))
    op.create_check_constraint(
        "llm_call_scope_known",
        "llm_call",
        "scope IS NULL OR scope IN ('company', 'contact', 'campaign')",
    )

    # Partial, on the column each ranking groups by. The rankings read one
    # window of attributed rows; an index covering the unattributed history
    # would be dead weight on a table that is append-only and grows a row per
    # call.
    op.create_index(
        "ix_llm_call_run",
        "llm_call",
        ["run_id"],
        postgresql_where=sa.text("run_id IS NOT NULL"),
    )
    op.create_index(
        "ix_llm_call_campaign",
        "llm_call",
        ["campaign_id"],
        postgresql_where=sa.text("campaign_id IS NOT NULL"),
    )
    # The company-versus-contact split groups by scope inside a run, so the
    # useful index is the pair, not either column alone.
    op.create_index(
        "ix_llm_call_run_scope",
        "llm_call",
        ["run_id", "scope"],
        postgresql_where=sa.text("run_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_llm_call_run_scope", table_name="llm_call")
    op.drop_index("ix_llm_call_campaign", table_name="llm_call")
    op.drop_index("ix_llm_call_run", table_name="llm_call")
    op.drop_constraint("llm_call_scope_known", "llm_call", type_="check")
    for column in ("scope", *reversed(_IDS)):
        op.drop_column("llm_call", column)
