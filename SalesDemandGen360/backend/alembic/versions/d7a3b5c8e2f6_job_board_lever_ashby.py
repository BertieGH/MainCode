"""The job board source reads Lever and Ashby as well as Greenhouse.

Only the description changes: the source was seeded saying "Greenhouse", and a
source's description is what the Research screen shows a rep. Updated only if it
still reads as seeded — a rep may have rewritten it, and theirs stands.

Revision ID: d7a3b5c8e2f6
Revises: c4e1a7d9f2b5
"""

from __future__ import annotations

from alembic import op

revision = "d7a3b5c8e2f6"
down_revision = "c4e1a7d9f2b5"
branch_labels = None
depends_on = None

OLD = (
    "Open roles from the company''s own applicant-tracking board (Greenhouse): "
    "titles, teams, locations and descriptions, dated by when each role opened."
)
NEW = (
    "Open roles from the company''s own applicant-tracking board (Greenhouse, Lever or Ashby): "
    "titles, teams, locations and descriptions, dated by when each role opened."
)


def upgrade() -> None:
    op.execute(
        f"UPDATE research_source SET description = '{NEW}' "
        f"WHERE key = 'job_board' AND description = '{OLD}'"
    )


def downgrade() -> None:
    op.execute(
        f"UPDATE research_source SET description = '{OLD}' "
        f"WHERE key = 'job_board' AND description = '{NEW}'"
    )
