"""LinkedIn, as search engines have indexed it, becomes a builtin source.

Research had a rep-made `linkedin_profile` source whose brief asked it to
"browse direct" — which nothing here may do: LinkedIn forbids automated access
and has won in court over it. In fifteen runs it stored nothing from linkedin.com.

`linkedin` is a search source with a brief that can be followed: what search
engines show of the account's LinkedIn company page and its posts, and of each
contact's profile and posts, identified by the LinkedIn URL on record. The pipeline
drops passages from a different company page or person, and dates posts from
their URLs. See `services/linkedin.py`.

Revision ID: e2b9d4a7c1f3
Revises: d7a3b5c8e2f6
"""

from __future__ import annotations

from alembic import op

revision = "e2b9d4a7c1f3"
down_revision = "d7a3b5c8e2f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO research_source
            (key, label, description, kind, scopes, support_only, builtin, status)
        VALUES (
            'linkedin', 'LinkedIn (via search)',
            'What search engines have indexed from LinkedIn: the company''s LinkedIn page and '
            'posts published by it, and each person''s profile headline and posts. Search '
            'site:linkedin.com/company/<slug>, site:linkedin.com/posts/<slug> and '
            'site:linkedin.com/in/<slug>, using the LinkedIn URL given when there is one. '
            'Quote only what the search results show; never open a linkedin.com page.',
            'search', '["company", "contact"]'::jsonb, false, true, 'active'
        )
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM research_source WHERE key = 'linkedin' "
        "AND NOT EXISTS (SELECT 1 FROM research_coverage WHERE family = 'linkedin')"
    )
