"""normalise produced_by to the query family registry

Revision ID: 5473abf2ce14
Revises: 16d1312c4918
Create Date: 2026-09-05 02:15:47.419599
"""
from alembic import op
import sqlalchemy as sa


revision = '5473abf2ce14'
down_revision = '16d1312c4918'
branch_labels = None
depends_on = None



# Free text let these into produced_by before the registry existed. Mapped
# rather than dropped: the intent behind each is unambiguous, and clearing them
# would silently turn a configured type into one with no producer at all.
RENAMES = {
    "content activity": "content_activity",
    "news / press": "news",
    "tech stack": "tech_stack",
}


def upgrade() -> None:
    for old, new in RENAMES.items():
        op.execute(
            sa.text(
                "UPDATE signal_type "
                "SET produced_by = array_replace(produced_by, :old, :new) "
                "WHERE :old = ANY(produced_by)"
            ).bindparams(old=old, new=new)
        )


def downgrade() -> None:
    for old, new in RENAMES.items():
        op.execute(
            sa.text(
                "UPDATE signal_type "
                "SET produced_by = array_replace(produced_by, :new, :old) "
                "WHERE :new = ANY(produced_by)"
            ).bindparams(old=old, new=new)
        )
