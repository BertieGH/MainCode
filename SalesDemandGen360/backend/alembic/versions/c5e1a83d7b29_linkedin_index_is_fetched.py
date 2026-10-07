"""`linkedin_index` becomes a fetch with its own reader, and sources get a recency window.

The source has been registered and inert since `b6d4a8f32e07`. It was declared
`kind='search'`, which routes it to grounded search — and grounding **excludes
linkedin.com for everyone** (§64, four confirmations), so the one route that
could never work was the one it was wired to.

A SERP API reads Google's index instead, which is the whole distinction the
registry is built on. That makes it the same shape as `company_site` and
`ats_boards`: a `fetch` with a dedicated reader, dispatched by registry key in
`pipeline`. Three things come free from that shape rather than being built —
the fast-sweep gate (no sweep hits, no credits spent), the reuse window, and a
coverage row per account.

**`max_age_days`**, new on every source, is the recency window. Measured
first — `after:YYYY-MM-DD` in the query is honoured by Google, and for one
company 38 indexed posts became 6 inside ninety days, every one genuinely
within the window. The `tbs=qdr:` parameter is **ignored** by this provider, so
the operator has to travel in the query string.

It buys two different things:

* **the results shrink** — fewer passages stored, fewer extraction tokens;
* **a gate** — `totalResults` on the windowed query answers "is there anything
  recent here" in the *same* call, before a single result is read. Measured
  across the band: **eight of ten companies have no post in ninety days**, so
  the per-contact post queries are skipped for eighty per cent of accounts.

Null means no window, and the intake cutoff from `durability.research_cutoff`
still applies — this narrows a source below that bound, it does not widen
anything past it. Set to 365 for `linkedin_index` rather than 90: a post is
read against *every* signal type, and an acquisition announced ten months ago
is still an acquisition, so the floor belongs where the widest reader needs it
rather than where the narrowest type's TTL sits.

Revision ID: c5e1a83d7b29
Revises: a7e1d4c92f85
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c5e1a83d7b29"
down_revision = "b3d7f05e91c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("research_source", sa.Column("max_age_days", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_research_source_max_age_positive",
        "research_source",
        "max_age_days IS NULL OR max_age_days > 0",
    )
    op.execute(
        sa.text(
            "UPDATE research_source "
            "   SET kind = 'fetch', max_age_days = 365, updated_at = now() "
            " WHERE key = 'linkedin_index'"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE research_source SET kind = 'search', updated_at = now() "
            " WHERE key = 'linkedin_index'"
        )
    )
    op.drop_constraint(
        "ck_research_source_max_age_positive", "research_source", type_="check"
    )
    op.drop_column("research_source", "max_age_days")
