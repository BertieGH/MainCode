"""Write a real query per signal into the curation CSV.

The file arrived with one query repeated across all seventeen rows — a
contact-shaped string (`{person}`) sitting on `funding`, `m_and_a_integration`
and every other company signal. This replaces it with a query per signal under
two rules:

* **A company signal never mentions `{person}`.** Searching a newsroom for a
  person's name does not find an acquisition.
* **A contact signal always has `{person}`**; `{company}` is optional there,
  because a person's conference talk or podcast may not name their employer in
  the indexed text.

Each option carries the route it needs, because a correct query against an
unreachable corpus is still nothing:

* `grounded` — works today through Gemini grounding. Measured.
* `fetch` — read directly by `site_sweep` or `job_boards`, no model call.
* `serp` — **needs a SERP API** (SerpApi, Scrapingdog). Every LinkedIn X-Ray
  query is here. Google's public index does carry LinkedIn profiles and posts,
  which is why the X-Ray approach is sound; Gemini's grounding corpus excludes
  linkedin.com, which is why it returns nothing today for anyone, Microsoft
  included. The queries are written so they work the moment a SERP route
  exists.

    cd backend
    PYTHONPATH=. ../.venv/Scripts/python.exe scripts/fill_signal_queries.py \
        -i "C:/Download/signal-registry.csv" -o ../signal-registry-filled.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

QUERY_COL = "Target Search Pattern / Query Syntax"
ROUTE_COL = "retrieval_route"
KEY_COL = "valid_key"

#: signal key (as it appears in the file) -> (valid key, route summary, options)
#: An option is (route, label, query).
Q: dict[str, tuple[str, str, list[tuple[str, str, str]]]] = {
    # ---------------------------------------------------------------- contact
    "contact_activity": (
        "contact_content_activity",
        "grounded; serp for X-Ray",
        [
            ("serp", "LinkedIn X-Ray",
             'site:linkedin.com/posts "{person}"'),
            ("grounded", "Spoken or written elsewhere",
             '"{person}" ("{company}" OR "{title}") (wrote OR published OR '
             '"spoke at" OR podcast OR webinar OR panel)'),
            ("grounded", "Own site byline",
             'site:{domain}/blog "{person}" OR site:{domain}/insights "{person}"'),
        ],
    ),
    "linkedin_profile": (
        "contact_profile_headline_change",
        "serp only",
        [
            ("serp", "LinkedIn X-Ray headline",
             'site:linkedin.com/in "{person}" "{company}"'),
            ("serp", "X-Ray by title",
             'site:linkedin.com/in "{person}" ("CIO" OR "CTO" OR "COO" OR '
             '"Director" OR "VP")'),
        ],
    ),
    "public_pain_statement": (
        "public_pain_statement",
        "grounded; serp for X-Ray",
        [
            ("serp", "LinkedIn X-Ray",
             'site:linkedin.com/posts "{person}" ("challenge" OR "struggling" '
             'OR "frustrating" OR "pain point" OR "we had to")'),
            ("grounded", "Spoken word",
             '"{person}" ("{company}" OR "{title}") (podcast OR panel OR '
             'interview OR keynote OR webinar OR roundtable)'),
            ("grounded", "Trade press",
             '"{person}" site:insurancejournal.com OR site:businessinsurance.com '
             'OR site:propertycasualty360.com'),
        ],
    ),
    "role_change": (
        "contact_role_change",
        "grounded; provider; serp for X-Ray",
        [
            ("grounded", "Appointment language",
             '"{person}" ("joins" OR "appointed" OR "named" OR "promoted to" OR '
             '"has joined") "{company}"'),
            ("grounded", "Wires",
             '"{person}" "{company}" site:prnewswire.com OR site:businesswire.com'),
            ("serp", "LinkedIn X-Ray",
             'site:linkedin.com/in "{person}" "{company}"'),
            ("fetch", "Provider",
             "Apollo then ContactOut waterfall - the reliable path, costs credits"),
        ],
    ),
    # ---------------------------------------------------------------- company
    "Company profile": (
        "firmographic_baseline",
        "fetch; grounded",
        [
            ("fetch", "Own about pages",
             "site:{domain}/about OR site:{domain}/about-us OR "
             "site:{domain}/who-we-are OR site:{domain}/leadership"),
            ("grounded", "Stated facts",
             '"{company}" ("headquartered" OR "founded in" OR "employees" OR '
             '"offices in" OR "we serve")'),
            ("grounded", "Directories",
             '"{company}" site:zoominfo.com OR site:dnb.com OR '
             'site:bloomberg.com/profile'),
        ],
    ),
    "Technology Issues & pain statements IT only": (
        "company_pain_statement",
        "fetch; grounded",
        [
            ("fetch", "Own words on own site",
             'site:{domain}/blog OR site:{domain}/insights ("manual" OR '
             '"time-consuming" OR "bottleneck" OR "spreadsheets" OR "challenge")'),
            ("grounded", "Stated problem",
             '"{company}" ("struggling with" OR "manual process" OR "we needed" '
             'OR "our team was" OR "took us days")'),
            ("grounded", "Case studies and testimonials",
             '"{company}" ("case study" OR testimonial) ("before" OR "challenge" '
             'OR "problem")'),
        ],
    ),
    "compliance_security_deadline": (
        "compliance_security_deadline",
        "fetch; grounded - TESTED",
        [
            ("fetch", "Trust centre",
             'site:{domain}/security OR site:{domain}/trust OR '
             'site:{domain}/compliance ("SOC 2" OR "ISO 27001" OR "HIPAA" OR "PCI")'),
            ("grounded", "Named obligation",
             '"{company}" ("SOC 2" OR "HIPAA" OR "ISO 27001" OR "examination" OR '
             '"audit completed" OR "certification")'),
            ("grounded", "Filings and regulator",
             '"{company}" ("cybersecurity" OR "risk factors" OR "data breach") '
             'site:sec.gov'),
        ],
    ),
    "digital_transformation_mandate": (
        "digital_transformation_mandate",
        "grounded; fetch",
        [
            ("grounded", "Wires",
             '"{company}" ("digital transformation" OR "client portal" OR '
             '"automation initiative" OR "cloud migration" OR "AI initiative") '
             "site:prnewswire.com OR site:businesswire.com"),
            ("fetch", "Own newsroom",
             'site:{domain}/news OR site:{domain}/press ("launch" OR "portal" OR '
             '"platform" OR "modernis" OR "transformation")'),
            ("grounded", "Trade press",
             '"{company}" ("digital" OR "technology initiative" OR "platform") '
             "site:insurancejournal.com OR site:digitalinsurance.com"),
        ],
    ),
    "engineering_scaling": (
        "engineering_team_expansion",
        "fetch; grounded - ISV/SAAS track only",
        [
            ("fetch", "ATS board",
             "Greenhouse, Lever, Ashby or Workday board named by the careers page"),
            ("grounded", "Own careers page",
             'site:{domain}/careers ("engineer" OR "developer" OR "SRE" OR '
             '"platform" OR "infrastructure")'),
            ("grounded", "Aggregators",
             'site:ziprecruiter.com OR site:indeed.com "{company}" '
             '("software engineer" OR "developer")'),
        ],
    ),
    "funding": (
        "funding_growth_milestone",
        "grounded - ISV/SAAS track ONLY, never run on brokerages",
        [
            ("grounded", "Wires",
             '"{company}" ("raises" OR "Series A" OR "Series B" OR "Series C" OR '
             '"funding round" OR "led the round") site:prnewswire.com OR '
             "site:businesswire.com"),
            ("grounded", "Startup press and indices",
             '"{company}" site:crunchbase.com OR site:techcrunch.com '
             '("raised" OR "funding" OR "valuation")'),
        ],
    ),
    "hiring_bottleneck": (
        "hiring_bottleneck",
        "grounded; fetch - TESTED",
        [
            ("grounded", "Own and standalone careers domains",
             'site:{domain}/careers OR {company}careers.com ("open" OR '
             '"join our team" OR "current openings")'),
            ("grounded", "Aggregators, for posting age and re-posts",
             'site:ziprecruiter.com OR site:indeed.com OR site:glassdoor.com '
             '"{company}"'),
            ("fetch", "ATS board",
             "Workday, Greenhouse, Lever or Ashby - reads posting dates directly"),
        ],
    ),
    "leadership_Change News": (
        "leadership_change_executive",
        "grounded; fetch; serp for X-Ray",
        [
            ("grounded", "Wires",
             '"{company}" ("appoints" OR "names" OR "joins as" OR "has been '
             'named") ("CIO" OR "CTO" OR "COO" OR "VP of IT" OR "chief") '
             "site:prnewswire.com OR site:businesswire.com"),
            ("fetch", "Own newsroom and leadership page",
             'site:{domain}/news OR site:{domain}/press OR site:{domain}/leadership '
             '("appoint" OR "welcome" OR "joins")'),
            ("serp", "LinkedIn X-Ray by role",
             'site:linkedin.com/in "{company}" ("CIO" OR "CTO" OR '
             '"Chief Information" OR "VP of Technology")'),
        ],
    ),
    "m&a_integration": (
        "m_and_a_integration",
        "grounded; fetch - TESTED",
        [
            ("grounded", "Wires",
             '"{company}" ("completes acquisition of" OR "acquires" OR '
             '"merger agreement" OR "has acquired") site:prnewswire.com OR '
             "site:businesswire.com"),
            ("grounded", "Filings",
             '"{company}" ("acquisition" OR "merger" OR "purchase agreement") '
             "site:sec.gov"),
            ("fetch", "Own newsroom",
             'site:{domain}/news OR site:{domain}/press ("acquisition" OR '
             '"acquires" OR "joins forces" OR "welcomes")'),
        ],
    ),
    "partnership": (
        "strategic_partnership_alliance",
        "grounded; fetch",
        [
            ("grounded", "Wires",
             '"{company}" ("partnership" OR "alliance" OR "carrier appointment" '
             'OR "now offers" OR "teams up") site:prnewswire.com OR '
             "site:businesswire.com"),
            ("fetch", "Own newsroom",
             'site:{domain}/news OR site:{domain}/press ("partner" OR "alliance" '
             'OR "appointment" OR "now offering")'),
        ],
    ),
    "product_launch": (
        # Renamed back from `product_feature_launch` by f7b3d9e24a16 — the
        # curated spreadsheet's own name turned out to be the right one.
        "product_launch",
        "fetch; grounded",
        [
            ("fetch", "Own newsroom and blog",
             'site:{domain}/news OR site:{domain}/press OR site:{domain}/blog '
             '("launches" OR "introduces" OR "now available" OR "announcing")'),
            ("grounded", "Wires",
             '"{company}" ("launches" OR "unveils" OR "now available" OR '
             '"introduces") site:prnewswire.com OR site:businesswire.com'),
        ],
    ),
    "tech_adoption": (
        "tech_stack_expansion",
        "grounded - ISV/SAAS track only",
        [
            ("grounded", "Stack detection index",
             'site:builtwith.com "{domain}"'),
            ("grounded", "Engineering writing",
             'site:{domain}/engineering OR site:{domain}/blog ("we use" OR '
             '"built on" OR "migrated to" OR "AWS" OR "Azure" OR "Kubernetes")'),
            ("grounded", "Stack named in job adverts",
             'site:{domain}/careers ("React" OR "Kubernetes" OR "Snowflake" OR '
             '"Salesforce" OR "Databricks")'),
        ],
    ),
    "tech_debt_modernization": (
        "tech_debt_modernization",
        "grounded - enterprise track",
        [
            ("grounded", "Named legacy platform",
             '"{company}" ("Applied Epic" OR "Vertafore" OR "AMS360" OR "Sagitta" '
             'OR "legacy system" OR "end of life" OR "on-premise")'),
            ("grounded", "Legacy skill in job adverts",
             'site:{domain}/careers ("COBOL" OR ".NET Framework" OR "AS/400" OR '
             '"mainframe" OR "legacy")'),
            ("grounded", "Trade press",
             '"{company}" ("modernisation" OR "replatform" OR "migration" OR '
             '"system replacement") site:insurancejournal.com OR '
             "site:propertycasualty360.com"),
        ],
    ),
}


def render(options: list[tuple[str, str, str]]) -> str:
    return " | ".join(
        f"Option {i} [{route}] ({label}): {query}"
        for i, (route, label, query) in enumerate(options, start=1)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-i", "--infile", type=Path, required=True)
    parser.add_argument("-o", "--out", type=Path, required=True)
    args = parser.parse_args()

    with args.infile.open(newline="", encoding="utf-8-sig") as handle:
        rows = [r for r in csv.DictReader(handle) if (r.get("signal_type") or "").strip()]
        headers = list(rows[0].keys())

    for col in (ROUTE_COL, KEY_COL):
        if col not in headers:
            headers.append(col)

    unmatched = []
    for row in rows:
        key = (row["signal_type"] or "").strip()
        if key not in Q:
            unmatched.append(key)
            continue
        valid_key, route, options = Q[key]
        row[QUERY_COL] = render(options)
        row[ROUTE_COL] = route
        row[KEY_COL] = valid_key
        # The CGVAK sources cell for this row carried an unquoted comma, which
        # shifted the two columns after it by one. Put them back.
        if key == "hiring_bottleneck":
            row["sources suggested by CGVAK"] = "hiring; job_board; company_site"
            row["Gemini signal suggestion"] = "hiring_bottleneck"

    with args.out.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)

    routes = {r[ROUTE_COL].split(";")[0].strip() for r in rows if r.get(ROUTE_COL)}
    print(f"{len(rows)} rows written -> {args.out}")
    print(f"primary routes used: {sorted(routes)}")
    if unmatched:
        print(f"NO QUERY WRITTEN for: {unmatched}")


if __name__ == "__main__":
    main()
