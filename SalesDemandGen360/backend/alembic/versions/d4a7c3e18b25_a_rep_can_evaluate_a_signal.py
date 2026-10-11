"""a rep can evaluate a signal

The prep screen shows each signal with its source, its date and what we read
into it, and asks the rep whether it is right. That answer belongs in
`evaluation`, which already accepts `subject_type = 'signal'` and already
exists to be read back — a second feedback table beside it would split the
record of "was this any good" in two.

Only `method` needed widening. The verdict vocabulary a rep uses — accurate,
outdated, irrelevant — does not map onto pass/warn/fail without losing which
of the three it was, so the specific word goes in `issues` and the column
keeps its existing three values:

    accurate            -> pass
    needs_verification  -> warn,  issues [{kind: needs_verification}]
    inaccurate          -> fail,  issues [{kind: inaccurate}]
    outdated            -> fail,  issues [{kind: outdated}]
    irrelevant          -> fail,  issues [{kind: irrelevant}]

A rep saying "outdated" is not the same finding as "inaccurate" — the first
is about our refresh cadence and the second about our extraction — and
flattening them would make the evaluation layer unable to tell us which to fix.

Revision ID: d4a7c3e18b25
Revises: c2f91a7e4db6
"""
from __future__ import annotations

from alembic import op

revision = "d4a7c3e18b25"
down_revision = "c2f91a7e4db6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("method_valid", "evaluation", type_="check")
    op.create_check_constraint(
        "method_valid", "evaluation", "method IN ('rules','llm','hybrid','rep')"
    )


def downgrade() -> None:
    # Rep verdicts would violate the narrower constraint, so they go first.
    # They are judgements about rows that still exist and can be given again;
    # the evidence and signals they describe are untouched.
    op.execute("DELETE FROM evaluation WHERE method = 'rep'")
    op.drop_constraint("method_valid", "evaluation", type_="check")
    op.create_check_constraint(
        "method_valid", "evaluation", "method IN ('rules','llm','hybrid')"
    )
