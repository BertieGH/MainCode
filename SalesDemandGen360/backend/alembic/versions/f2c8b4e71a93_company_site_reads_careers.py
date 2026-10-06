"""Let the company's own site answer the hiring questions too.

`ats_boards` is paused at **26 attempts across 57 accounts and no evidence**. A
twenty-person broker does not run a Greenhouse board. It does have a careers
page, and `company_site` — a `fetch`, costing no model call, and the only
source on this book that reliably produces anything (25 passages) — was already
reading its `/news` and `/security` pages while walking straight past
`/careers`.

So the cheapest available answer to "who are they hiring and what stack do they
name" was already running and not being asked. `site_sweep.PAGE_PATHS` now
interleaves announcements with careers rather than grouping them, because the
loop stops at `MAX_PAGES` and grouping meant a site with four news pages never
reached the second kind at all.

`/security`, `/trust` and `/compliance` are **dropped** in the same change, at
the owner's instruction. They were read for `compliance_security_deadline`,
which has produced nothing on this book, and each miss costs an eight-second
timeout on every account without such a page — which is most of them. That type
keeps `trade_press`, `regulators_and_registers` and its own search instruction,
so it is narrowed rather than orphaned.

Two registry changes follow from it:

* `company_site`'s brief says it reads careers pages, because that brief is
  what extraction is told the source contains;
* `engineering_team_expansion` adds `company_site`. It named `ats_boards`,
  `trade_press` and `company_data_providers` — a paused source and two that
  ignore companies this size — so on this book it had no live route to the one
  page that actually lists its evidence.

`hiring_bottleneck` already named `company_site` and needs no change.

Revision ID: f2c8b4e71a93
Revises: e4a9c7d13b60
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f2c8b4e71a93"
down_revision = "e4a9c7d13b60"
branch_labels = None
depends_on = None

BRIEF = (
    "The company's own site, read directly rather than searched: its feed first "
    "— releases, press and blog posts, with its own dates — and when there is no "
    "feed, its conventional pages. Two kinds are read. Announcements on /news, "
    "/newsroom and /press. Open roles on /careers and /jobs, which for a "
    "company too small to run an applicant-tracking board is "
    "the only place its hiring is visible — take the titles, how many there are, "
    "and any software or platform named in the requirements. A role asking for a "
    "legacy skill is evidence that system is still running."
)


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE research_source SET description = :d, updated_at = now() "
            "WHERE key = 'company_site'"
        ).bindparams(d=BRIEF)
    )
    # `array_append` only when it is not already there, so a re-run is a no-op.
    conn.execute(
        sa.text(
            "UPDATE signal_type "
            "   SET produced_by = array_append(produced_by, 'company_site'), "
            "       updated_at = now() "
            " WHERE key = 'engineering_team_expansion' "
            "   AND NOT ('company_site' = ANY(produced_by))"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE research_source SET description = :d, updated_at = now() "
            "WHERE key = 'company_site'"
        ).bindparams(
            d="The company's own feed and pages: releases, press, blog posts, and "
              "its /security, /trust and /compliance pages, with its own dates."
        )
    )
    conn.execute(
        sa.text(
            "UPDATE signal_type "
            "   SET produced_by = array_remove(produced_by, 'company_site'), "
            "       updated_at = now() "
            " WHERE key = 'engineering_team_expansion'"
        )
    )
