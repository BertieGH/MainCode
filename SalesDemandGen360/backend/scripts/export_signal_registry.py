"""The signal registry as a CSV, for curating in a spreadsheet.

TTL, Life, sources and the signal count are read live, so the file is true when
it is written rather than true when someone last edited it. The judgement
columns — what to search, how healthy the sources are, what to do about the
type — are curated here, because they are opinions and the database holds none.

    cd backend
    PYTHONPATH=. ../.venv/Scripts/python.exe scripts/export_signal_registry.py

Columns are flat and plain on purpose: no emoji, no merged meanings. A status
mark that means three things at once reads fine in a document and sorts badly
in a spreadsheet, which is what this is for.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings

#: key -> (track, recommendation, source health, tested?, what to search)
CURATED: dict[str, tuple[str, str, str, str, str]] = {
    "m_and_a_integration": (
        "enterprise", "keep - core", "ok", "yes",
        '"{company}" ("completes acquisition of" OR "acquires" OR "merger agreement") '
        "site:prnewswire.com OR site:businesswire.com OR site:sec.gov",
    ),
    "compliance_security_deadline": (
        "enterprise", "keep - core", "ok", "yes",
        'site:{domain}/security OR /trust OR /compliance ("SOC 2" OR "ISO 27001" '
        'OR "HIPAA" OR "examination")',
    ),
    "leadership_vendor_review": (
        "enterprise", "keep - core", "ok", "no",
        '"{company}" ("appoints" OR "names" OR "joins as") ("CIO" OR "CTO" OR "COO" '
        'OR "VP of IT" OR "head of operations"), plus the newsroom',
    ),
    "tech_debt_modernization": (
        "enterprise", "keep - core", "ok", "no",
        '"{company}" ("Applied Epic" OR "Vertafore" OR "AMS360" OR "legacy" OR '
        '"end of life" OR "migration" OR "on-premise")',
    ),
    "vendor_consolidation": (
        "enterprise", "keep - core", "ok", "no",
        '"{company}" ("vendor consolidation" OR "cost rationalisation" OR '
        '"preferred vendor" OR "contractor reduction"), plus wires',
    ),
    "digital_transformation_mandate": (
        "enterprise", "keep - core", "ok", "no",
        '"{company}" ("digital transformation" OR "client portal" OR '
        '"automation initiative" OR "cloud migration")',
    ),
    "hiring_bottleneck": (
        "enterprise", "keep - core", "weak (job_board)", "yes",
        'site:{domain}/careers OR {company}careers.com OR site:ziprecruiter.com '
        '"{company}" - titles, posting age, re-posts',
    ),
    "company_pain_statement": (
        "enterprise", "keep - supporting", "ok", "no",
        '"{company}" ("struggling with" OR "manual process" OR "bottleneck") - '
        "their own words, quoted",
    ),
    "delivery_quality_theme": (
        "enterprise", "keep - supporting", "weak (reviews)", "yes",
        '"{company}" site:glassdoor.com OR site:google.com/maps - NOT G2 or '
        "Capterra, which review software products",
    ),
    "partnership": (
        "enterprise", "keep - supporting", "ok", "no",
        '"{company}" ("carrier appointment" OR "partnership" OR "alliance" OR '
        '"now offers")',
    ),
    "public_focus": (
        "enterprise", "keep - supporting", "dead (linkedin)", "no",
        "site:{domain}/blog OR /insights OR /resources - recurring themes",
    ),
    "funding": (
        "tech", "pause for this book", "ok", "no",
        "Crunchbase, PitchBook, wires",
    ),
    "tech_adoption": (
        "tech", "pause for this book", "ok", "no",
        'site:builtwith.com "{domain}", site:{domain}/engineering',
    ),
    "engineering_scaling": (
        "tech", "pause for this book", "weak (job_board)", "no",
        "ATS boards - overlaps hiring_bottleneck",
    ),
    "product_launch": (
        "tech", "pause for this book", "ok", "no",
        '"{company}" ("launches" OR "introduces" OR "now available")',
    ),
    "mgt_change": (
        "enterprise", "deprecate", "ok", "no",
        "Superseded - split into leadership_vendor_review and m_and_a_integration",
    ),
    "role_change": (
        "enterprise", "decide - needs contact research", "weak (enrichment)", "no",
        '"{person}" "{company}" ("joins" OR "appointed" OR "promoted to"); the '
        "Apollo to ContactOut waterfall is the reliable path",
    ),
    "public_pain_statement": (
        "enterprise", "decide - needs contact research", "dead (linkedin)", "no",
        '"{person}" "{company}" across podcasts, panels, trade press, conference bios',
    ),
    "contact_activity": (
        "enterprise", "fix - no sources assigned", "none", "no",
        "No sources assigned - can only fire if a general sweep turns something up",
    ),
    "linkedin_profile": (
        "enterprise", "deprecate", "dead (linkedin)", "no",
        "No live retrieval route; only a rep typing it in",
    ),
}

HEADERS = [
    "scope", "signal_type", "track", "recommendation", "sources",
    "source_health", "what_to_search", "pattern_tested", "ttl_days",
    "life_days", "signals_so_far", "status",
]


async def rows() -> list[dict]:
    engine = create_async_engine(str(get_settings().database_url))
    async with engine.connect() as conn:
        found = (
            await conn.execute(
                text(
                    """
                    select key, scope, status, default_ttl_days ttl,
                           coalesce(durability_days, default_ttl_days * 3) life,
                           array_to_string(produced_by, '; ') sources,
                           (select count(*) from signal s
                             where s.signal_type = signal_type.key) n
                    from signal_type
                    order by scope desc, key
                    """
                )
            )
        ).mappings().all()
    await engine.dispose()

    out = []
    for r in found:
        track, rec, health, tested, query = CURATED.get(
            r["key"], ("", "unreviewed", "", "no", "")
        )
        out.append(
            {
                "scope": r["scope"],
                "signal_type": r["key"],
                "track": track,
                "recommendation": rec,
                "sources": r["sources"] or "NONE",
                "source_health": health,
                "what_to_search": query,
                "pattern_tested": tested,
                "ttl_days": r["ttl"],
                "life_days": r["life"],
                "signals_so_far": r["n"],
                "status": r["status"],
            }
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-o",
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "signal-registry.csv",
    )
    args = parser.parse_args()

    data = asyncio.run(rows())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig: Excel on Windows reads a plain UTF-8 CSV as the system
    # codepage and mangles anything non-ASCII. The BOM is what tells it.
    with args.out.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(data)
    print(f"{len(data)} signal types -> {args.out}")


if __name__ == "__main__":
    main()
