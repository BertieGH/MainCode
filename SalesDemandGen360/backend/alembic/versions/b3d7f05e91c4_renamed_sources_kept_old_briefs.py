"""Two renamed sources kept the brief of the narrower thing they used to be.

`c1f7e3b89d24` renamed three sources and set `key` and `label` — and not
`description`. The description is the only part a model reads: it is what
`stages.research_request` sends as `source.read_for`. So for two of the three
the label promised one thing and the brief delivered another, and the brief won.

    ats_boards                label: "ATS boards and careers pages"
                              brief: "applicant-tracking board (Greenhouse)"
    regulators_and_registers  label: "Regulators and licence registers"
                              brief: "SEC EDGAR ... restricted to sec.gov"

`linkedin_index` escaped because `b6d4a8f32e07` rewrote its brief for the X-Ray
operators a week later.

**This has a measured consequence.** `regulators_and_registers` was trialled
against two accounts and found nothing, and that trial ran against the stale
`sec.gov`-only brief rather than the licence registers its name advertises. The
zero stands as a fact about the narrow query; it is not evidence about the
source as named, and it is worth re-trialling now that the two agree.

**And a boundary that moved.** `f2c8b4e71a93` gave `/careers` and `/jobs` to
`company_site`, which is a free fetch of the company's own site. `ats_boards`
still claimed careers pages in its label, so two sources advertised the same
page. The split is now clean: the company's own site is `company_site`, and
`ats_boards` is the hosted boards reached through their own APIs — a different
retrieval route for a different place, which is the distinction the registry is
supposed to encode.

Revision ID: b3d7f05e91c4
Revises: a7e1d4c92f85
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b3d7f05e91c4"
down_revision = "a7e1d4c92f85"
branch_labels = None
depends_on = None

ATS = (
    "Hosted applicant-tracking boards, read through their own public APIs: "
    "Greenhouse, Lever, Ashby and Workday. One request returns every open role "
    "with its title, team, location, description and the date it opened, which "
    "is better evidence than a search and costs no model call. Read for what "
    "the company is building — several related roles at once, a function being "
    "staffed for the first time — and for the platforms named in the "
    "requirements, because a role asking for a legacy skill is evidence that "
    "system is still running.\n\n"
    "Not the company's own careers page: that is read by company_site, which "
    "already fetches /careers and /jobs. This source is for a company large "
    "enough to run a board a recruiter administers."
)

REGISTERS = (
    "What a company has formally filed with a regulator or a register. Three "
    "kinds. Corporate filings — SEC EDGAR, Companies House — for ownership, "
    "change of control, named officers and risk factors. State insurance "
    "department licence registers, for a licence added, surrendered or moved "
    "to a new state, which is how a broker's expansion becomes public before "
    "anybody writes about it. And change-of-control or merger notices filed "
    "with a regulator ahead of an announcement.\n\n"
    "A regulator's record is dated and authoritative, so prefer it over a "
    "press release describing the same event, and keep the filing date rather "
    "than the date it was reported."
)


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE research_source SET label = :l, description = :d, updated_at = now() "
            "WHERE key = 'ats_boards'"
        ).bindparams(l="ATS job boards", d=ATS)
    )
    conn.execute(
        sa.text(
            "UPDATE research_source SET description = :d, updated_at = now() "
            "WHERE key = 'regulators_and_registers'"
        ).bindparams(d=REGISTERS)
    )


def downgrade() -> None:
    """Puts back the briefs that disagreed with their labels, since that is
    what this revision replaced — not the pre-rename keys."""
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE research_source SET label = :l, description = :d, updated_at = now() "
            "WHERE key = 'ats_boards'"
        ).bindparams(
            l="ATS boards and careers pages",
            d="Open roles from the company's own applicant-tracking board "
              "(Greenhouse): titles, teams, locations and descriptions, dated by "
              "when each role opened.",
        )
    )
    conn.execute(
        sa.text(
            "UPDATE research_source SET description = :d, updated_at = now() "
            "WHERE key = 'regulators_and_registers'"
        ).bindparams(
            d="SEC EDGAR and state insurance regulators. Search the company name "
              'with "acquisition", "merger", "risk factors" or an examination '
              "restricted to sec.gov",
        )
    )
