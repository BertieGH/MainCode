"""Which of the suggested sitemap patterns actually exist on this book?

A companion to `survey_sitemaps.py`, which settled what the *hub* pages are
called. This one tests the finer claims — department-specific careers paths,
individual job postings, case-study and event sections, theme-named child
sitemaps, and un-delimited slugs like `/joinus` — so each is adopted on
evidence or refused on evidence rather than on how plausible it sounds.

Counts are **sites**, not URLs: one large site with 300 event pages is one
site's habit, and reading it as a pattern across the book is how a single
account's shape becomes a rule for everyone.

Read-only: robots.txt and sitemaps. No model calls, no credits.

    python scripts/survey_sitemap_shapes.py
"""

from __future__ import annotations

import asyncio
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.account import Account  # noqa: E402
from app.services import sitemap  # noqa: E402
from app.services.site_sweep import _get_bytes, client  # noqa: E402

#: Claimed to carry the tech stack and the hiring mix.
DEPARTMENTS = (
    "engineering", "sales", "marketing", "technology", "it", "operations",
    "finance", "product", "data", "claims", "underwriting",
)
#: Claimed to carry one role each, naming the platforms it runs on.
POSTING = re.compile(
    r"/(?:jobs?|careers?|open-positions?)/(?:details?|apply|view|posting|opening)s?/|"
    r"/job-(?:details|description|posting)/",
    re.IGNORECASE,
)
#: Suggested as news-adjacent sections. Tested as their own themes rather than
#: folded in: a case study is undated marketing, not an announcement.
CANDIDATE_THEMES = {
    "proof": ("case-studies", "case-study", "customers", "success-stories",
              "testimonials", "testimonial", "clients", "our-clients"),
    "events": ("events", "event", "webinars", "webinar", "seminars", "conferences"),
}
#: The same words with the delimiter dropped, which a lowercase match alone
#: cannot catch: `/JoinUs` lowercases to `joinus`, and `join-us` never matches it.
UNDELIMITED = {
    "joinus": "join-us", "workwithus": "work-with-us", "aboutus": "about-us",
    "ourteam": "our-team", "pressroom": "press-room", "casestudies": "case-studies",
    "whoweare": "who-we-are", "ourstory": "our-story", "meettheteam": "meet-the-team",
    "openpositions": "open-positions", "jobopenings": "job-openings",
    "ourpeople": "our-people", "latestnews": "latest-news", "pressreleases": "press-releases",
    "successstories": "success-stories", "newsroom": "newsroom",
}
#: Claimed to be the valuable children of a sitemap index.
NAMED_CHILDREN = ("job", "career", "post", "blog", "news", "page", "press", "event")


async def shapes_for(http, domain: str) -> dict | None:
    """Everything this survey wants to know about one domain, in one pass."""
    rules = RobotFileParser()
    raw = await _get_bytes(http, f"https://{domain}/robots.txt")
    rules.parse((raw.decode("utf-8", "replace") if raw else "").splitlines())
    robots = {f"https://{domain}": rules}

    # Follow the index ourselves so the child *names* can be recorded — the
    # question is whether a theme-named child exists, which `discover` hides.
    children: list[str] = []
    candidates = list(rules.site_maps() or []) + [
        f"https://{domain}{p}" for p in sitemap.CONVENTIONAL
    ]
    entries: list[str] = []
    for candidate in list(dict.fromkeys(candidates))[: sitemap.MAX_CANDIDATES]:
        body_raw = await _get_bytes(http, candidate)
        if body_raw is None:
            continue
        body = sitemap._decode(body_raw, candidate)
        if not body or "<loc" not in body.lower():
            continue
        found, kids = sitemap.parse(body)
        if kids:
            children = kids
            for child in kids[:12]:
                child_raw = await _get_bytes(http, child)
                if child_raw is None:
                    continue
                child_body = sitemap._decode(child_raw, child)
                if child_body:
                    entries.extend(e.url for e in sitemap.parse(child_body)[0])
            if entries:
                break
        if found:
            entries = [e.url for e in found]
            break
    if not entries:
        return None

    found_shapes: dict = {"domain": domain, "urls": len(entries), "children": children}
    paths = [urlparse(u).path.lower() for u in entries]
    segments = [[s for s in p.strip("/").split("/") if s] for p in paths]

    found_shapes["departments"] = sorted({
        parts[1] for parts in segments
        if len(parts) >= 2 and sitemap._theme_of(parts[0]) == "careers"
        and parts[1] in DEPARTMENTS
    })
    found_shapes["deep_careers"] = sum(
        1 for parts in segments
        if len(parts) >= 2 and sitemap._theme_of(parts[0]) == "careers"
    )
    found_shapes["postings"] = sum(1 for p in paths if POSTING.search(p))
    for theme, words in CANDIDATE_THEMES.items():
        found_shapes[theme] = sorted({
            parts[0] for parts in segments if parts and parts[0] in words
        })
    found_shapes["undelimited"] = sorted({
        parts[0] for parts in segments if parts and parts[0] in UNDELIMITED
    })
    return found_shapes


async def main() -> None:
    async with SessionLocal() as session:
        domains = list(
            (
                await session.execute(
                    select(Account.domain)
                    .where(Account.domain.isnot(None), Account.domain != "")
                    .order_by(Account.name)
                )
            ).scalars()
        )

    async with client(12.0) as http:
        results = await asyncio.gather(
            *(shapes_for(http, d) for d in domains), return_exceptions=True
        )
    sites = [r for r in results if isinstance(r, dict)]
    print(f"domains: {len(domains)}   with a readable sitemap: {len(sites)}\n")

    def sites_with(key) -> list[dict]:
        return [s for s in sites if s[key]]

    print("— claim: department-specific careers paths (/careers/engineering)")
    hits = sites_with("departments")
    print(f"    {len(hits)} of {len(sites)} sites")
    for s in hits:
        print(f"      {s['domain']}: {', '.join(s['departments'])}")
    deep = [s for s in sites if s["deep_careers"]]
    print(f"    any page at all beneath a careers hub: {len(deep)} sites")
    for s in deep:
        print(f"      {s['domain']}: {s['deep_careers']} page(s)")

    print("\n— claim: individual job postings (/jobs/details/, /careers/apply/)")
    hits = sites_with("postings")
    print(f"    {len(hits)} of {len(sites)} sites")
    for s in hits:
        print(f"      {s['domain']}: {s['postings']} url(s)")

    for theme in CANDIDATE_THEMES:
        print(f"\n— claim: a /{theme} section is worth its own theme")
        hits = sites_with(theme)
        print(f"    {len(hits)} of {len(sites)} sites")
        spellings: Counter[str] = Counter()
        for s in hits:
            spellings.update(s[theme])
        for word, n in spellings.most_common():
            print(f"      {n:>3} sites   /{word}")

    print("\n— claim: slugs with no delimiter (/JoinUs -> joinus)")
    hits = sites_with("undelimited")
    print(f"    {len(hits)} of {len(sites)} sites")
    spellings = Counter()
    for s in hits:
        spellings.update(s["undelimited"])
    for word, n in spellings.most_common():
        matched = "already matched" if sitemap._theme_of(word) else "MISSED today"
        print(f"      {n:>3} sites   /{word:<18} ({matched})")

    print("\n— claim: theme-named child sitemaps (sitemap-jobs.xml, post-sitemap.xml)")
    indexed = [s for s in sites if s["children"]]
    print(f"    {len(indexed)} of {len(sites)} sites use a sitemap index")
    named: Counter[str] = Counter()
    beyond = 0
    child_names: dict[str, list[str]] = defaultdict(list)
    for s in indexed:
        names = [urlparse(c).path.rsplit("/", 1)[-1].lower() for c in s["children"]]
        child_names[s["domain"]] = names
        for word in NAMED_CHILDREN:
            if any(word in n for n in names):
                named[word] += 1
        # Does a theme-named child sit past the first five, where the reader
        # stops? That is the difference between the claim mattering and not.
        for position, name in enumerate(names):
            if position >= sitemap.MAX_CHILDREN and any(w in name for w in NAMED_CHILDREN):
                beyond += 1
                break
    for word, n in named.most_common():
        print(f"      {n:>3} sites   *{word}*")
    print(f"    sites whose theme-named child sits past child #{sitemap.MAX_CHILDREN}: {beyond}")
    for domain, names in child_names.items():
        if len(names) > sitemap.MAX_CHILDREN:
            print(f"      {domain}: {len(names)} children — {', '.join(names[:9])}")


if __name__ == "__main__":
    asyncio.run(main())
