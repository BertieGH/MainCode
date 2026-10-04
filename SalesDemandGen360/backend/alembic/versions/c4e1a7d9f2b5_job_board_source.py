"""A company's job board becomes a research source.

Careers pages render their openings with a script from the applicant-tracking
system, so research reading the page saw the container and not the jobs. The
`job_board` source reads the board the company's own site names, through the
ATS's public API — Greenhouse first. See `services/job_boards.py`.

Seeded as `builtin` and `fetch`, like `company_site`: it needs code behind it,
and a rep could not create it from the screen.

Revision ID: c4e1a7d9f2b5
Revises: b8d2f4a61c93
"""

from __future__ import annotations

from alembic import op

revision = "c4e1a7d9f2b5"
down_revision = "b8d2f4a61c93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO research_source
            (key, label, description, kind, scopes, support_only, builtin, status)
        VALUES (
            'job_board', 'Job board',
            'Open roles from the company''s own applicant-tracking board (Greenhouse): '
            'titles, teams, locations and descriptions, dated by when each role opened.',
            'fetch', '["company"]'::jsonb, false, true, 'active'
        )
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    # Only while nothing has been read under it: a coverage row names its
    # source, and removing the source would orphan the record of that read.
    op.execute(
        "DELETE FROM research_source WHERE key = 'job_board' "
        "AND NOT EXISTS (SELECT 1 FROM research_coverage WHERE family = 'job_board')"
    )
