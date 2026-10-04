"""The research sources the product ships with.

This was the closed set, and the reason it was closed is worth keeping in view
because it survives the change: a source key nothing runs is indistinguishable
from a source that ran and found nothing. It reports as a permanent coverage gap
on a prospect who may be perfectly well covered, and nothing errors.

The registry is a table now — `research_source`, read through
`services/sources.py`, which is the authority for what exists and what a signal
type may claim. These rows are the *seed*: what a fresh installation gets, and
what `tests/conftest.py` puts back after a truncate. Migration `a3c6e820f7d1`
inserted them under their original keys, so coverage written before the table
existed still resolves against it.

What survives here besides the seed is `Runner`, which says how a source's work
actually gets done. Not every source is a web search, and that used to be an
unwritten assumption.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

#: How a family's work actually gets done. Every family was assumed to be a web
#: search until this existed, and `enrichment` quietly broke that assumption in
#: three ways: it costs credits rather than tokens, it is already modelled by
#: `enrichment_config` and the provider waterfall, and its "returned nothing"
#: can mean no credential or no credit rather than nobody found.
#:
#: That last one is why a flag was not enough. Coverage has a single bucket —
#: returned nothing means gap — while `verification` deliberately keeps five
#: outcomes apart, because collapsing them is how a reachable contact gets
#: written off or an unreachable one keeps getting re-charged. A sweep
#: reporting "enrichment: coverage gap" when the truth is "no ContactOut
#: credential" tells a rep the wrong thing.
#:
#: * `search`   — the research agent runs it; nothing found is a coverage gap.
#: * `fetch`    — read directly from the source, with no model call. Cheaper
#:                than a search and better evidence: the company's own words
#:                with the company's own date on them, and a link that opens
#:                the page. Nothing found is a coverage gap, as with a search.
#: * `provider` — a metered provider waterfall; never auto-run, and its status
#:                comes from the verification report rather than from whether
#:                it returned anything.
#: * `manual`   — a rep entered it. Never run, never a gap, always available.
#:
#: One axis rather than two booleans: `manual` needs the same "do not run,
#: do not report as a gap" treatment for entirely different reasons, and under
#: a `provider_backed` flag it would have needed a second one.
Runner = Literal["search", "fetch", "provider", "manual"]


@dataclass(frozen=True)
class QueryFamily:
    key: str
    label: str
    description: str
    scopes: tuple[str, ...]
    #: Reviews can corroborate a signal but never create one on its own — a
    #: single complaint is noise, a repeated theme is evidence (§7.1 rule 1).
    #: Orthogonal to `runner`: reviews is a real search that cannot conclude.
    support_only: bool = False
    runner: Runner = "search"


QUERY_FAMILIES: tuple[QueryFamily, ...] = (
    QueryFamily(
        "funding", "Funding",
        "Rounds, amounts, investors, filings, dates.",
        ("company",),
    ),
    QueryFamily(
        "hiring", "Hiring",
        "Open roles, counts by function, urgency language in postings.",
        ("company",),
    ),
    QueryFamily(
        "tech_stack", "Tech stack",
        "Tools named in job posts, integrations pages, engineering blog.",
        ("company",),
    ),
    QueryFamily(
        "news", "News / press",
        "Launches, partnerships, expansions, incidents.",
        ("company", "contact"),
    ),
    QueryFamily(
        "leadership", "Leadership",
        "Exec appointments and departures, team-page changes.",
        ("company", "contact"),
    ),
    QueryFamily(
        "reviews", "Reviews & ratings",
        "Recurring themes in employee and customer reviews. Supports a signal, never creates one.",
        ("company",),
        support_only=True,
    ),
    QueryFamily(
        "enrichment", "Enrichment",
        "Apollo → ContactOut waterfall: title, seniority, contactable details.",
        ("contact",),
        runner="provider",
    ),
    QueryFamily(
        "content_activity", "Content activity",
        "What the person has published, posted or said in public.",
        ("contact",),
    ),
    QueryFamily(
        "company_site", "Company announcements",
        "The company's own feed: releases, press and blog posts, with its dates.",
        ("company",),
        runner="fetch",
    ),
    QueryFamily(
        "job_board", "Job board",
        "Open roles from the company's own applicant-tracking board (Greenhouse, Lever or "
        "Ashby): titles, teams, locations and descriptions, dated by when each role opened.",
        ("company",),
        runner="fetch",
    ),
    QueryFamily(
        "linkedin", "LinkedIn (via search)",
        "What search engines have indexed from LinkedIn: the company's LinkedIn page and posts "
        "published by it, and each person's profile headline and posts. Search "
        "site:linkedin.com/company/<slug>, site:linkedin.com/posts/<slug> and "
        "site:linkedin.com/in/<slug>, using the LinkedIn URL given when there is one. Quote only "
        "what the search results show; never open a linkedin.com page.",
        ("company", "contact"),
    ),
    QueryFamily(
        "manual", "Manual entry",
        "Entered by a rep rather than discovered. Always available.",
        ("company", "contact"),
        runner="manual",
    ),
)

BY_KEY: dict[str, QueryFamily] = {f.key: f for f in QUERY_FAMILIES}


def searchable() -> list[QueryFamily]:
    """The shipped sources a research sweep may fan out over.

    Excludes `provider` and `manual`. Running the whole list would spend Apollo
    credits as though they were tokens, and would invoke a source whose entire
    definition is "a person typed this".
    """
    return [f for f in QUERY_FAMILIES if f.runner == "search"]


# `validate` used to live here. It checks what a signal type may claim, and
# that question is now answered by the `research_source` table — see
# `services/sources.validate`. Two validators would mean a key retired in the
# registry still passing here, which is the silent coverage gap the check
# exists to prevent.
