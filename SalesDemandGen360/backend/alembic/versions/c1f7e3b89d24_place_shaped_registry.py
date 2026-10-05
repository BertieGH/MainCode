"""Make every source a place, not a topic.

Seven of seventeen rows were named after what you hoped to find — `funding`,
`hiring`, `leadership`, `tech_stack`, `content_activity`, `news`, `reviews` —
rather than where to look. A signal type then named `hiring` and the two said
the same thing twice, neither of them saying where to go. That is the
restructure left open as decision #4 in `docs/15-signal-registry.md`, and the
registry was quietly contradicting its own invariant in CLAUDE.md: *a source
says what research opens; signal types say what is read out of it*.

After this there are **seven loci and two routes**:

    company_site                    the company's own feed and pages (fetch)
    trade_press                     trade publications and the wire services
    company_data_providers          Crunchbase, PitchBook, ZoomInfo, BuiltWith
    conference_and_podcast_circuit  agendas, episode pages, speaker bios
    ats_boards                      Greenhouse, Lever, Ashby, Workday, careers (fetch)
    regulators_and_registers        licence registers and filings
    linkedin_index                  public LinkedIn as Google indexes it
    enrichment                      the provider waterfall (route)
    manual                          a rep typed it (route)

**Three of the new loci were trialled before being written here**, through
`source_trial` against three real accounts — the same prompt and model a stored
source gets, storing nothing. `trade_press`, `company_data_providers` and
`conference_and_podcast_circuit` each returned passages. A fourth candidate,
`review_sites`, returned **nothing at any of the three** and is therefore not
in this migration at all; `reviews`, the row it would have replaced, is
retired. That is the point of the harness: the old way of finding this out was
`job_board`'s 26 attempts across the book.

**What the trial also showed, which is bigger than the renaming.** Every
passage came from the one *insurtech* in the sample. The two brokerages
returned nothing from any locus, and the stored record agrees: 47 of 57
accounts have never produced a passage, and the two largest (41 and 42 people)
hold 69% of all evidence. These places are where a technology company appears.
They do not rescue a twenty-person brokerage, and nothing will — which is why
`company_site` is the only reliable producer. The restructure opens the
technology track; it does not fix the book.

**Old keys are deleted, not deprecated, along with their coverage rows.** The
owner's standing instruction is to purge conflicting transaction data rather
than spend time reconciling it, and `research_coverage.family` holds the old
key as free text. The measured record those rows carried was written to
`docs/source-health-2026-10-05.csv` first, which is what the restructure gets
judged against.

Revision ID: c1f7e3b89d24
Revises: b6d4a8f32e07
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "c1f7e3b89d24"
down_revision = "b6d4a8f32e07"
branch_labels = None
depends_on = None

#: The new loci, as they will be read by the research prompt. `trade_press` and
#: `conference_and_podcast_circuit` carry `contact` as well as `company`: an
#: appointment notice names a person, and a panel bio is a person speaking.
NEW_SOURCES = [
    (
        "trade_press", "Trade press and wire services", "search", ["company", "contact"],
        "Insurance and technology trade publications, and the wire services companies "
        "file announcements to - Business Insurance, Insurance Journal, Reinsurance "
        "News, PR Newswire, Business Wire. Read for what has been announced about this "
        "company by somebody other than the company: an acquisition, an appointment, a "
        "new programme, a carrier appointment, an office opening. Quote the sentence "
        "and keep the publication date.",
    ),
    (
        "company_data_providers", "Company data and funding providers", "search", ["company"],
        "Crunchbase, PitchBook, ZoomInfo, Dun and Bradstreet, Bloomberg profiles and "
        "BuiltWith. Read for the structured facts a directory holds about this company: "
        "a funding round with its size, lead investor and date; headcount and its "
        "direction; the technologies detected on its domain; parent or subsidiary "
        "ownership. State the provider as the source and date the fact where the "
        "provider dates it.",
    ),
    (
        "conference_and_podcast_circuit", "Conference, podcast and panel circuit",
        "search", ["company", "contact"],
        "Conference agendas and speaker bios, podcast episode pages, webinar listings "
        "and trade-press interviews. Read for a named person at this company saying "
        "something in public, in their own words: a problem they have, a programme they "
        "are running, a priority for the year. Give the person, the event or episode, "
        "the date, and the quote. An industry opinion is not a statement about their "
        "own work.",
    ),
]

#: old key -> new key. Everything mapping to None is retired outright.
#:
#: `trust_security_portals` folds into `company_site` because it always was
#: part of it: `site_sweep.PAGE_PATHS` already reads /security, /trust and
#: /compliance. It was a second row for pages one fetch already opened.
MOVED = {
    "news": "trade_press",
    "press_wire_aggregators": "trade_press",
    "leadership": "trade_press",
    "funding": "company_data_providers",
    "tech_stack": "company_data_providers",
    "content_activity": "conference_and_podcast_circuit",
    "hiring": "ats_boards",
    "job_board": "ats_boards",
    "careers_domain_direct": "ats_boards",
    "trust_security_portals": "company_site",
    "regulatory_and_filings": "regulators_and_registers",
    "linkedin_serp": "linkedin_index",
    # Trialled as `review_sites` against three accounts and found nothing at
    # any of them. Retired rather than renamed: a place that returns nothing is
    # not a place worth keeping a row for.
    "reviews": None,
}

#: Renamed in place — same row, same coverage history, a name that says where.
RENAMED = {
    "job_board": ("ats_boards", "ATS boards and careers pages"),
    "regulatory_and_filings": ("regulators_and_registers", "Regulators and licence registers"),
    "linkedin_serp": ("linkedin_index", "LinkedIn via the public search index"),
}

#: Kept untouched: the one proven producer and the two routes.
KEPT = ("company_site", "enrichment", "manual")


def upgrade() -> None:
    conn = op.get_bind()

    # Renames first, so the rows that keep their history keep it, and the
    # MOVED mapping below finds them already under the new name.
    for old, (new, label) in RENAMED.items():
        conn.execute(
            sa.text(
                "UPDATE research_source SET key=:new, label=:label, updated_at=now() "
                "WHERE key=:old"
            ).bindparams(new=new, label=label, old=old)
        )
        conn.execute(
            sa.text("UPDATE research_coverage SET family=:new WHERE family=:old").bindparams(
                new=new, old=old
            )
        )

    for key, label, kind, scopes, description in NEW_SOURCES:
        conn.execute(
            sa.text(
                "INSERT INTO research_source "
                "(key, label, description, kind, scopes, support_only, builtin, status) "
                "VALUES (:k, :l, :d, :kind, CAST(:s AS jsonb), false, false, 'active') "
                "ON CONFLICT (key) DO UPDATE SET label=EXCLUDED.label, "
                "description=EXCLUDED.description, scopes=EXCLUDED.scopes, "
                "status='active', status_reason=NULL, updated_at=now()"
            ).bindparams(k=key, l=label, d=description, kind=kind, s=json.dumps(scopes))
        )

    # `ats_boards` keeps the row but stops being planned: 26 attempts across
    # the book and not one passage. Paused rather than deleted, because the
    # technology track this restructure opens is exactly where an ATS board
    # does exist, and the row carries that history.
    conn.execute(
        sa.text(
            "UPDATE research_source SET status='paused', status_reason=:r, updated_at=now() "
            "WHERE key='ats_boards'"
        ).bindparams(
            r="26 attempts across 57 accounts and no evidence: a small brokerage runs "
              "no ATS board. Kept for the technology track, where they do."
        )
    )

    _remap_types(conn)
    _remap_icps(conn)

    # The retired rows and their coverage, last — after everything that pointed
    # at them has been moved.
    retired = sorted(k for k in MOVED if k not in RENAMED)
    conn.execute(
        sa.text("DELETE FROM research_coverage WHERE family = ANY(:k)").bindparams(k=retired)
    )
    conn.execute(
        sa.text("DELETE FROM research_source WHERE key = ANY(:k)").bindparams(k=retired)
    )


def _remap_types(conn) -> None:
    """Point every signal type's `produced_by` at the new loci.

    Rebuilt in Python rather than with nested `array_replace` calls: several old
    keys collapse onto one new one, so the result needs de-duplication, and the
    order a person put them in is worth keeping.
    """
    rows = conn.execute(
        sa.text("SELECT id, key, produced_by, scope FROM signal_type")
    ).all()
    for row_id, _key, produced_by, scope in rows:
        current = list(produced_by or [])
        moved = []
        for src in current:
            target = MOVED.get(src, src)
            if target is None:
                continue
            moved.append(target)
        # A contact-scoped type cannot name a company-only locus; the registry
        # refuses it elsewhere, so drop it here rather than write a row that
        # `sources.validate` would reject the next time anybody edits it.
        if scope == "contact":
            moved = [s for s in moved if s != "company_data_providers"]
        fresh = list(dict.fromkeys(moved))
        if fresh == current:
            continue
        conn.execute(
            sa.text(
                "UPDATE signal_type SET produced_by=:p, updated_at=now() WHERE id=:i"
            ).bindparams(p=fresh, i=row_id)
        )


def _remap_icps(conn) -> None:
    """And every ICP's accepted sources, which is the gate that decides the plan."""
    rows = conn.execute(
        sa.text("SELECT id, definition FROM icp_profile_version WHERE definition ? 'sources'")
    ).all()
    for row_id, definition in rows:
        current = definition.get("sources") or []
        if not isinstance(current, list):
            continue
        moved = []
        for src in current:
            target = MOVED.get(src, src)
            if target is None:
                continue
            moved.append(target)
        for key, _l, _k, _s, _d in NEW_SOURCES:
            if key not in moved:
                moved.append(key)
        fresh = [s for s in dict.fromkeys(moved) if s != "ats_boards"]
        if fresh == current:
            continue
        definition["sources"] = fresh
        conn.execute(
            sa.text(
                "UPDATE icp_profile_version SET definition=CAST(:d AS jsonb) WHERE id=:i"
            ).bindparams(d=json.dumps(definition), i=row_id)
        )


def downgrade() -> None:
    """Puts the three renames back. The retired rows are not restored.

    A downgrade undoes a restructure, not a purge: the rows deleted here were
    deleted because the owner asked for conflicting data to go rather than be
    reconciled, and resurrecting them would leave the registry disagreeing with
    the coverage history again.
    """
    conn = op.get_bind()
    for old, (new, _label) in RENAMED.items():
        conn.execute(
            sa.text(
                "UPDATE research_source SET key=:old, updated_at=now() WHERE key=:new"
            ).bindparams(old=old, new=new)
        )
        conn.execute(
            sa.text("UPDATE research_coverage SET family=:old WHERE family=:new").bindparams(
                old=old, new=new
            )
        )
    conn.execute(
        sa.text("DELETE FROM research_source WHERE key = ANY(:k)").bindparams(
            k=[k for k, *_ in NEW_SOURCES]
        )
    )
