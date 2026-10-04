"""Where research looks becomes configuration.

Research read a closed tuple of query families defined in code. The set was
closed because an unknown family name reports as a permanent coverage gap on a
prospect who may be perfectly well covered — so `produced_by` had to be
checkable against something.

This makes that something a table. The ten existing families are seeded as
`builtin` rows **under their own keys**, so every coverage row already written
still lines up with the source it names, and `produced_by` keeps working
unchanged. What is new is that a rep can add the eleventh.

`kind` is carried over from the code definition rather than defaulted: a
`fetch` reads a feed with no model call, a `provider` spends credits, and
`manual` is a person typing. Collapsing those into "a search" is what makes a
sweep report "coverage gap" when the truth is "no credential".

Revision ID: a3c6e820f7d1
Revises: f2a7c91b4e08
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a3c6e820f7d1"
down_revision = "f2a7c91b4e08"
branch_labels = None
depends_on = None


#: The closed set, at the moment it stopped being closed. Copied rather than
#: imported: a migration has to keep producing the same rows after the code it
#: came from has moved on.
SEED = [
    ("funding", "Funding", "Rounds, amounts, investors, filings, dates.",
     "search", ["company"], False, None),
    ("hiring", "Hiring", "Open roles, counts by function, urgency language in postings.",
     "search", ["company"], False, None),
    ("tech_stack", "Tech stack", "Tools named in job posts, integrations pages, engineering blog.",
     "search", ["company"], False, None),
    ("news", "News / press", "Launches, partnerships, expansions, incidents.",
     "search", ["company", "contact"], False, None),
    ("leadership", "Leadership", "Exec appointments and departures, team-page changes.",
     "search", ["company", "contact"], False, None),
    ("reviews", "Reviews & ratings",
     "Recurring themes in employee and customer reviews. Supports a signal, never creates one.",
     "search", ["company"], True, None),
    ("enrichment", "Enrichment",
     "Apollo \u2192 ContactOut waterfall: title, seniority, contactable details.",
     "provider", ["contact"], False, None),
    ("content_activity", "Content activity",
     "What the person has published, posted or said in public.",
     "search", ["contact"], False, None),
    ("company_site", "Company announcements",
     "The company's own feed: releases, press and blog posts, with its dates.",
     "fetch", ["company"], False, None),
    ("manual", "Manual entry",
     "Entered by a rep rather than discovered. Always available.",
     "manual", ["company", "contact"], False, None),
]


def upgrade() -> None:
    op.create_table(
        "research_source",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False, server_default=sa.text("'search'")),
        sa.Column("scopes", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[\"company\"]'::jsonb")),
        sa.Column("support_only", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("reuse_days", sa.Integer(), nullable=True),
        sa.Column("builtin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.CheckConstraint("kind IN ('search','fetch','provider','manual')",
                           name="kind_valid"),
        sa.CheckConstraint("status IN ('active','paused','deprecated')",
                           name="status_valid"),
        sa.CheckConstraint("jsonb_array_length(scopes) > 0",
                           name="scopes_not_empty"),
        sa.CheckConstraint("reuse_days IS NULL OR reuse_days > 0",
                           name="reuse_days_positive"),
        sa.PrimaryKeyConstraint("id", name="pk_research_source"),
        sa.UniqueConstraint("key", name="uq_research_source_key"),
    )

    rows = [
        {
            "key": key, "label": label, "description": description, "kind": kind,
            "scopes": json.dumps(scopes), "support_only": support_only,
            "reuse_days": reuse_days, "builtin": True, "status": "active",
        }
        for key, label, description, kind, scopes, support_only, reuse_days in SEED
    ]
    conn = op.get_bind()
    for row in rows:
        conn.execute(
            sa.text(
                "INSERT INTO research_source "
                "(key, label, description, kind, scopes, support_only, reuse_days,"
                " builtin, status) "
                "VALUES (:key, :label, :description, :kind, CAST(:scopes AS jsonb),"
                " :support_only, :reuse_days, :builtin, :status)"
            ),
            row,
        )


def downgrade() -> None:
    op.drop_table("research_source")
