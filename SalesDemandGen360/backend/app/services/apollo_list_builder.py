"""Building a list out of the Apollo contacts this account already owns.

**The whole point is that this costs nothing.** `contacts/search` reads the
contacts the account has already paid for — 356,830 of them here, 250,354 with
a verified email — and reading them is free however many times it is done. A
credit is spent only when Apollo *reveals* somebody new, which this never does.

That is the difference from the Suggested tab, and it is why the two are
separate routes rather than one with a flag: a suggestion is a proposal to
spend a credit, and these people are already bought. Proposing them for reveal
would be theatre.

Measured on the live account before this was written:

```
356,830  all saved contacts
250,354  verified email
 87,911  persona titles
 36,170  all three, under 50 employees
     71  companies that can field *both* personas
```

That last line is the one that matters and the one nothing else would have
told us. 247 companies in the band had two matching people; only 71 had one of
each persona. The rest were two co-founding CTOs, which is not an economic
buyer and a technical buyer — it is the same conversation twice.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field

from app.services.providers import ProviderError

log = logging.getLogger(__name__)

#: Apollo's own size bands, as its API spells them.
SIZE_BANDS = {
    "1-10": "1,10", "11-50": "11,50", "51-200": "51,200",
    "201-500": "201,500", "501-1000": "501,1000", "1001+": "1001,100000",
}

#: Titles asked of Apollo. Wider than the personas below, because the server
#: filter is a coarse sieve and the persona decision is made here where it can
#: be explained — asking Apollo for exactly our ladder would drop a
#: "Head of Technology" that our own matcher would have recognised.
ASK_TITLES = (
    "CEO", "Chief Executive", "President", "Founder", "Owner", "Managing Director",
    "CTO", "Chief Technology", "CIO", "Chief Information", "Chief Digital",
    "Head of IT", "IT Director", "Head of Engineering", "VP",
)

#: **Technical first, and it wins.** A "Founder & CTO" is the technical buyer,
#: not the economic one. The first version ranked each person on both ladders
#: independently and duly paired a "Co-founder & CTO" with a
#: "Co-founder, CEO & CTO", labelling one of them the economic buyer — two
#: technical people and one wrong label.
TECHNICAL = (
    "chief technology", "cto", "chief information officer", "cio", "chief digital",
    "head of it", "it director", "director of it", "vp engineering",
    "vp of engineering", "head of engineering", "head of technology",
    "vp technology", "vp of technology", "it manager",
)
ECONOMIC = (
    "chief executive", "ceo", "owner", "president", "managing director",
    "chief operating", "coo", "founder", "vice president", "vp",
)

#: Apollo's page size, and the ceiling on one build. Free, but **not free of
#: time**: forty pages is four thousand contacts and a measured sixty-four
#: seconds, which is far too slow for a screen that recounts as you type.
PER_PAGE = 100
MAX_PAGES = 40

#: Pages read before checking whether there is enough yet. Small enough that
#: a short ask stops early, large enough not to re-run the grouping per page.
CHUNK = 4

#: Breathing room between pages.
#:
#: Apollo's limits are per minute, and forty requests as fast as the event loop
#: can issue them trips them — measured, as a 429 in the middle of a deep read
#: that had already done most of the work. A tenth of a second costs four
#: seconds across a full read and keeps the rate under ten a second, which is
#: roughly what the limit exists to stop.
PAGE_PAUSE = 0.1

#: Apollo's industry names, **in this account's order of volume**, and only
#: names verified to return something here.
#:
#: Checked rather than copied from a taxonomy, because a wrong name fails
#: silently: `organization_industries=["zzz-not-real"]` returns 0, exactly like
#: a real industry nobody is in. Two of the forty tried came back empty —
#: `insurance brokers` and `electrical & electronic manufacturing` — and there
#: is no way to tell a misspelling from an absence, so neither is offered.
#:
#: Ordered by what this account actually holds, verified and in a persona
#: title: information technology & services 43,896, marketing & advertising
#: 10,836, computer software 9,601. A list sorted alphabetically would bury
#: the three that matter under thirty that do not.
INDUSTRIES = (
    "information technology & services", "marketing & advertising", "computer software",
    "internet", "financial services", "insurance", "biotechnology",
    "management consulting", "hospital & health care", "telecommunications",
    "logistics & supply chain", "real estate", "banking", "construction", "machinery",
    "education management", "higher education", "staffing & recruiting",
    "medical devices", "retail", "oil & energy", "accounting",
    "government administration", "transportation/trucking/railroad", "automotive",
    "apparel & fashion", "architecture & planning", "civil engineering",
    "consumer goods", "food & beverages", "legal services",
    "mechanical or industrial engineering", "nonprofit organization management",
    "pharmaceuticals", "renewables & environment", "semiconductors", "utilities",
    "wholesale",
)


def persona_of(title: str | None) -> tuple[str | None, int]:
    """One persona per person, with the seniority within it.

    Returns `(None, -1)` for a title neither ladder recognises, which is how a
    "Head of Partnerships" that Apollo's coarse title filter let through is
    kept out of a persona slot it does not belong in.
    """
    t = (title or "").lower()
    for i, term in enumerate(TECHNICAL):
        if term in t:
            return "technical buyer", i
    for i, term in enumerate(ECONOMIC):
        if term in t:
            return "economic buyer", i
    return None, -1


@dataclass
class Candidate:
    full_name: str
    title: str | None
    email: str | None
    email_status: str | None
    linkedin_url: str | None
    company: str
    domain: str
    company_linkedin: str | None
    persona: str
    seniority: int
    apollo_contact_id: str | None = None


@dataclass
class Funnel:
    """What the filters left, at each step. Every number here is free to get."""

    saved_total: int = 0
    verified: int = 0
    titled: int = 0
    in_band: int = 0
    #: Read in this build — bounded by `MAX_PAGES`, so it is a sample of
    #: `in_band` rather than all of it.
    read: int = 0
    companies: int = 0
    #: Companies that can fill every requested persona slot. The real filter.
    usable_companies: int = 0
    available: int = 0


@dataclass
class Build:
    funnel: Funnel = field(default_factory=Funnel)
    chosen: list[Candidate] = field(default_factory=list)
    note: str = ""


def _candidate(row: dict) -> Candidate | None:
    org = row.get("organization") or {}
    domain = (org.get("primary_domain") or "").strip().lower()
    company = (row.get("organization_name") or "").strip()
    persona, seniority = persona_of(row.get("title"))
    if not domain or not company or persona is None:
        return None
    return Candidate(
        full_name=(row.get("name") or "").strip(),
        title=row.get("title"),
        email=row.get("email"),
        email_status=row.get("email_status"),
        linkedin_url=row.get("linkedin_url"),
        company=company,
        domain=domain,
        company_linkedin=org.get("linkedin_url"),
        persona=persona,
        seniority=seniority,
        apollo_contact_id=row.get("id"),
    )


def choose(
    rows: list[dict],
    *,
    personas: tuple[str, ...] = ("economic buyer", "technical buyer"),
    per_company: int = 2,
    limit: int = 100,
) -> Build:
    """Pick the people, company by company.

    **A company qualifies only if it can fill every persona asked for.** With
    both personas and `per_company = 2`, one person of each — not the two most
    senior, which on a small company is two co-founders with the same job.
    With `per_company` above the number of personas the extra slots go to the
    next most senior of any persona, since the pair is covered.

    Sorted by how much a company offers, so a build capped at fifty takes the
    fifty best-covered companies rather than the first fifty Apollo returned.
    """
    build = Build()
    by_company: dict[tuple[str, str], list[Candidate]] = defaultdict(list)
    for row in rows:
        person = _candidate(row)
        if person is not None:
            by_company[(person.company, person.domain)].append(person)

    build.funnel.read = len(rows)
    build.funnel.companies = len(by_company)

    wanted = tuple(personas) or ("economic buyer", "technical buyer")
    usable: list[list[Candidate]] = []
    for people in by_company.values():
        picked: list[Candidate] = []
        for persona in wanted:
            pool = [
                p for p in sorted(people, key=lambda p: p.seniority)
                if p.persona == persona and p not in picked
            ]
            if pool:
                picked.append(pool[0])
        # Every requested persona, or the company does not qualify. A list of
        # economic buyers with a gap where the technical buyer should be is not
        # what was asked for, and it is not visible once the list is built.
        if len(picked) < len(wanted):
            continue
        for p in sorted(people, key=lambda p: p.seniority):
            if len(picked) >= per_company:
                break
            if p not in picked:
                picked.append(p)
        usable.append(picked[:per_company])

    usable.sort(key=lambda group: -len(group))
    build.funnel.usable_companies = len(usable)
    build.funnel.available = sum(len(g) for g in usable)

    for group in usable:
        if len(build.chosen) + len(group) > limit:
            break
        build.chosen.extend(group)

    shortfall = build.funnel.available < limit
    build.note = (
        f"{len(build.chosen)} contacts at {len(build.chosen) // max(per_company, 1)} companies"
        + (
            f" — {build.funnel.available} is all the filters leave, from "
            f"{build.funnel.read} contacts read"
            if shortfall
            else ""
        )
    )
    return build


async def counts(client, *, size_bands: tuple[str, ...], verified_only: bool,
                 industries: tuple[str, ...] = ()) -> Funnel:
    """The coarse funnel — four one-row queries, and nothing else.

    **Split out from `search` because of the difference in cost.** These four
    come back in a couple of seconds; reading the pages behind them took a
    measured sixty-four. A screen that recounts as you type can afford these
    on every keystroke and cannot afford the rest, so the two are separate
    calls and the screen says which numbers it is still waiting for.
    """
    from app.services.apollo_people import CONTACTS_SEARCH_PATH

    ranges = [SIZE_BANDS[b] for b in size_bands if b in SIZE_BANDS]
    funnel = Funnel()

    async def total(body: dict) -> int:
        payload = await client._post(
            CONTACTS_SEARCH_PATH, body={"page": 1, "per_page": 1, **body}
        )
        return int(((payload or {}).get("pagination") or {}).get("total_entries") or 0)

    verified = {"contact_email_status": ["verified"]} if verified_only else {}
    titles = {"person_titles": list(ASK_TITLES)}
    band = {"organization_num_employees_ranges": ranges} if ranges else {}
    # An unselected industry list means every industry, not none. Sending an
    # empty array would filter to nothing and look like an empty account.
    trade = {"organization_industries": list(industries)} if industries else {}

    funnel.saved_total = await total({})
    funnel.verified = await total(verified) if verified_only else funnel.saved_total
    funnel.titled = await total({**verified, **titles})
    funnel.in_band = await total({**verified, **titles, **band, **trade})
    return funnel


async def search(client, *, size_bands: tuple[str, ...], verified_only: bool,
                 pages: int = MAX_PAGES) -> tuple[list[dict], Funnel]:
    """Read the saved contacts matching the coarse filters. Costs nothing.

    The funnel counts come from `total_entries` on four cheap one-row queries
    rather than from the rows themselves, so the screen can show where the
    numbers fall away before anybody waits for the pages.
    """
    from app.services.apollo_people import CONTACTS_SEARCH_PATH

    ranges = [SIZE_BANDS[b] for b in size_bands if b in SIZE_BANDS]
    funnel = Funnel()

    async def total(body: dict) -> int:
        payload = await client._post(
            CONTACTS_SEARCH_PATH, body={"page": 1, "per_page": 1, **body}
        )
        return int(((payload or {}).get("pagination") or {}).get("total_entries") or 0)

    verified = {"contact_email_status": ["verified"]} if verified_only else {}
    titles = {"person_titles": list(ASK_TITLES)}
    band = {"organization_num_employees_ranges": ranges} if ranges else {}

    funnel.saved_total = await total({})
    funnel.verified = await total(verified) if verified_only else funnel.saved_total
    funnel.titled = await total({**verified, **titles})
    funnel.in_band = await total({**verified, **titles, **band})

    rows: list[dict] = []
    for page in range(1, max(1, pages) + 1):
        payload = await client._post(
            CONTACTS_SEARCH_PATH,
            body={"page": page, "per_page": PER_PAGE, **verified, **titles, **band},
        )
        got = (payload or {}).get("contacts") or []
        if not got:
            break
        rows.extend(got)
    log.info(
        "apollo_list_builder.read rows=%d in_band=%d bands=%s", len(rows), funnel.in_band, ranges
    )
    return rows, funnel


async def gather(client, *, size_bands: tuple[str, ...], verified_only: bool,
                 personas: tuple[str, ...], per_company: int, limit: int,
                 industries: tuple[str, ...] = ()) -> Build:
    """Read until there is enough, or until the pages run out.

    **Adaptive, because the yield is not linear.** A fixed pages-per-company
    ratio was tried and under-read badly: 1,300 contacts gave 38 usable
    companies, while 4,000 gave 209 — more than three times the pages for more
    than five times the companies. The reason is that later pages mostly add a
    *second* person at a company already seen, which is exactly what turns an
    unusable company into a pair. Estimating that up front is guesswork; asking
    after every few pages is not.

    `exhausted` is the honest distinction the first version lost. "76 is all
    the filters leave" and "76 is all 1,300 contacts yielded, and there are
    23,000 more" are different facts, and only one of them is a reason to
    widen the filters.
    """
    from app.services.apollo_people import CONTACTS_SEARCH_PATH

    ranges = [SIZE_BANDS[b] for b in size_bands if b in SIZE_BANDS]
    verified = {"contact_email_status": ["verified"]} if verified_only else {}
    body = {
        "per_page": PER_PAGE,
        **verified,
        "person_titles": list(ASK_TITLES),
        **({"organization_num_employees_ranges": ranges} if ranges else {}),
        **({"organization_industries": list(industries)} if industries else {}),
    }

    rows: list[dict] = []
    build = Build()
    exhausted = False
    limited = False
    page = 1
    while page <= MAX_PAGES and not limited:
        for _ in range(CHUNK):
            if page > MAX_PAGES:
                break
            try:
                payload = await client._post(CONTACTS_SEARCH_PATH, body={**body, "page": page})
            except ProviderError as exc:
                # **Keep what was read.** A rate limit thirty pages in is not a
                # reason to discard the twenty-nine that worked — the same
                # reasoning as `OutOfCredits` carrying everything revealed
                # before it. The note then says the read was cut short, so a
                # short answer is not mistaken for a complete one.
                if "rate limit" not in str(exc).lower():
                    raise
                log.info("apollo_list_builder.rate_limited page=%d rows=%d", page, len(rows))
                limited = True
                break
            got = (payload or {}).get("contacts") or []
            page += 1
            if not got:
                exhausted = True
                break
            rows.extend(got)
            await asyncio.sleep(PAGE_PAUSE)
        build = choose(rows, personas=personas, per_company=per_company, limit=limit)
        if exhausted or build.funnel.available >= limit:
            break

    build.note = _note(
        build, limit=limit, per_company=per_company, exhausted=exhausted, limited=limited
    )
    log.info(
        "apollo_list_builder.gathered read=%d usable=%d available=%d exhausted=%s",
        len(rows), build.funnel.usable_companies, build.funnel.available, exhausted,
    )
    return build


def _note(build: Build, *, limit: int, per_company: int, exhausted: bool,
          limited: bool = False) -> str:
    taken = len(build.chosen)
    companies = taken // max(per_company, 1)
    if limited and taken < limit:
        # A third shortfall, distinct from the other two: not that the filters
        # are narrow, nor that we stopped early by choice, but that Apollo cut
        # us off. The advice is to wait, not to change anything.
        return (
            f"{taken} contacts at {companies} companies — Apollo's rate limit stopped the "
            f"read after {build.funnel.read:,} contacts. Wait a minute and check again."
        )
    if taken >= limit:
        return f"{taken} contacts at {companies} companies"
    if exhausted:
        return (
            f"{taken} contacts at {companies} companies — that is every company in "
            f"these filters that can field each persona"
        )
    return (
        f"{taken} contacts at {companies} companies — the most found in "
        f"{build.funnel.read:,} contacts read. Narrowing the personas or the size "
        f"band would find more."
    )
