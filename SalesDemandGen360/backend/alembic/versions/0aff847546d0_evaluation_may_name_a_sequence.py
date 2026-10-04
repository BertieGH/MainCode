"""evaluation may name a sequence

Revision ID: 0aff847546d0
Revises: a2b98a34107a
Create Date: 2026-09-06 00:46:47.382957
"""
from alembic import op
import sqlalchemy as sa


revision = '0aff847546d0'
down_revision = 'a2b98a34107a'
branch_labels = None
depends_on = None



# Alembic does not autogenerate CHECK changes, so this is written by hand.
OLD = ("research", "signal", "qualification", "strategy", "draft", "sales_prep", "execution")
NEW = OLD[:4] + ("outreach_sequence",) + OLD[4:]


def _values(values):
    return ",".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.drop_constraint("subject_type_valid", "evaluation", type_="check")
    op.create_check_constraint(
        "subject_type_valid", "evaluation", f"subject_type IN ({_values(NEW)})"
    )


def downgrade() -> None:
    # Any sequence-level evaluation would violate the narrower constraint, so
    # they are re-labelled rather than left to block the migration.
    op.execute(
        "UPDATE evaluation SET subject_type = 'draft' "
        "WHERE subject_type = 'outreach_sequence'"
    )
    op.drop_constraint("subject_type_valid", "evaluation", type_="check")
    op.create_check_constraint(
        "subject_type_valid", "evaluation", f"subject_type IN ({_values(OLD)})"
    )
