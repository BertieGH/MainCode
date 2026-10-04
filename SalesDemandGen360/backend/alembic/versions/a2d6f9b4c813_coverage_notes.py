"""Separate "we kept fewer than we found" from "we looked and it is not there".

`research_coverage.not_found` holds what a family searched for and could not
establish — the thing that turns "empty" from "did not look" into "looked for
these; none of it is there". The site sweep was also writing volume remarks
into it, so the screen reported

    company_site · ran · 10 evidence · 1 not established

for a sweep that had found **thirty** entries and kept ten. Nothing failed, and
the one line a rep reads said something close to the opposite.

`notes` carries those remarks instead. One field per meaning.

Revision ID: a2d6f9b4c813
Revises: f8c2a5d9e134
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a2d6f9b4c813"
down_revision = "f8c2a5d9e134"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "research_coverage",
        sa.Column(
            "notes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("research_coverage", "notes")
