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


#: **Every row is a place, not a topic.** The list used to hold `funding`,
#: `hiring`, `tech_stack`, `news`, `leadership`, `content_activity` and
#: `reviews` — names for what you hoped to find rather than where to look. A
#: signal type naming `hiring` then said the same thing twice and neither said
#: where to go, which contradicts the invariant this module serves: *a source
#: says what research opens; signal types say what is read out of it.*
#: Restructured by `c1f7e3b89d24`, which also carries the frozen copy a
#: migration needs.
#:
#: This list and the `research_source` table must agree. They are the same
#: registry seen from two places — code for a fresh install and for
#: `tests/conftest.py`, the table for a running one — and when they drift, a
#: test validates `produced_by` against a registry production does not have.
QUERY_FAMILIES: tuple[QueryFamily, ...] = (
    QueryFamily(
        "company_site", "Company announcements",
        "The company's own feed and pages: releases, press, blog posts, and its "
        "/security, /trust and /compliance pages, with its own dates.",
        ("company",),
        runner="fetch",
    ),
    QueryFamily(
        "trade_press", "Trade press and wire services",
        "Insurance and technology trade publications, and the wire services companies file "
        "announcements to — Business Insurance, Insurance Journal, PR Newswire, Business "
        "Wire. Read for what somebody other than the company has said about it: an "
        "acquisition, an appointment, a new programme, an office opening. Keep the date.",
        ("company", "contact"),
    ),
    QueryFamily(
        "company_data_providers", "Company data and funding providers",
        "Crunchbase, PitchBook, ZoomInfo, Dun and Bradstreet, Bloomberg profiles and "
        "BuiltWith. Read for the structured facts a directory holds: a funding round with "
        "its size, lead investor and date; headcount and its direction; technologies "
        "detected on the domain; parent or subsidiary ownership.",
        ("company",),
    ),
    QueryFamily(
        "conference_and_podcast_circuit", "Conference, podcast and panel circuit",
        "Conference agendas and speaker bios, podcast episode pages, webinar listings and "
        "trade-press interviews. Read for a named person at this company saying something "
        "in public, in their own words, with the event and the date.",
        # Company only. Measured over 29 contact-scope searches: 13 evidence
        # rows, **not one of them cited by a signal**. The company scope is
        # kept — it is weak there too, but it has produced four.
        ("company",),
    ),
    QueryFamily(
        "regulators_and_registers", "Regulators and licence registers",
        "State insurance department licence registers, SEC and Companies House filings, and "
        "change-of-control notices filed with a regulator. A regulator's record is dated and "
        "authoritative, so prefer it over a press release describing the same event.",
        ("company",),
    ),
    QueryFamily(
        "linkedin_index", "LinkedIn via the public search index",
        "Public LinkedIn content as Google has indexed it, reached with X-Ray path operators: "
        "site:linkedin.com/in for a profile and site:linkedin.com/posts for a dated post, "
        "paired with the quoted company and person name. Read through a SERP API. "
        "**Never by opening linkedin.com.**",
        # Company only, and the company scope is the best source in the
        # registry: 905 evidence rows, 23 signals, no grounded search bought.
        #
        # The contact scope was the worst. It searched the same two X-Ray
        # paths as the `contact_content_activity` signal type over the same
        # person at the same company — one index, bought twice — and in 29
        # searches returned a single evidence row that no signal ever cited,
        # against that type's 38 rows and 3 signals. Removed as a duplicate,
        # not as a capability: the search still happens, once.
        ("company",),
    ),
    QueryFamily(
        "ats_boards", "ATS job boards",
        "Hosted applicant-tracking boards, read through their own public APIs: Greenhouse, "
        "Lever, Ashby and Workday. One request returns every open role with its title, team, "
        "location, description and the date it opened. Not the company's own careers page — "
        "`company_site` already fetches /careers and /jobs, and two sources advertising the "
        "same page is how a registry starts disagreeing with itself.",
        ("company",),
        runner="fetch",
    ),
    QueryFamily(
        "enrichment", "Enrichment",
        "Apollo → ContactOut waterfall: title, seniority, contactable details.",
        ("contact",),
        runner="provider",
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
