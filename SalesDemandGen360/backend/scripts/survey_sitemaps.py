"""What are a company's pages actually called? Ask their sitemaps.

`site_sweep` guesses: it tries `/news`, then `/careers`, then `/jobs`, and each
miss costs an eight-second timeout. Measured across twenty accounts, that
guessing finds a real careers page on **one site in twenty** (§94).

A sitemap turns the guess into a lookup. The URLs are declared, so matching
them is free — which means a long synonym list costs nothing, where a long
*guess* list costs a timeout per entry.

This harvests them and tallies what the pages are called, so the synonyms are
derived from the book rather than invented. Read-only: robots.txt, sitemaps,
nothing else, no model calls and no credits.

    python scripts/survey_sitemaps.py
    python scripts/survey_sitemaps.py --limit 20
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.account import Account  # noqa: E402
from app.services import site_sweep, sitemap  # noqa: E402
from app.services.site_sweep import client  # noqa: E402

#: Tried when robots.txt declares nothing. Four of fourteen domains in the
#: first probe had a sitemap at a conventional path and no declaration.
CONVENTIONAL = ("/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml", "/sitemap-index.xml")

#: A sitemap index points at child sitemaps. Followed, but bounded: a large
#: site can list hundreds, and this is a survey rather than a crawl.
MAX_CHILDREN = 5
#: Per domain. The largest in the probe held 451 URLs, which is fine to parse
#: and far more than any ranking needs.
MAX_URLS = 2000

LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)
DECLARED = re.compile(r"(?im)^\s*sitemap:\s*(\S+)")

#: **The reader's own vocabulary**, not a copy of it. This script is what
#: widened `sitemap.THEMES` in the first place, and it is also what checks the
#: widening worked — so it has to measure the list the sweep will actually use.
#: A second copy here would drift, and the drift would read as a result.
THEMES = sitemap.THEMES


async def fetch(http, url: str) -> str | None:
    try:
        response = await http.get(url)
    except Exception:  # noqa: BLE001 — a dead host is a result
        return None
    if response.status_code != 200:
        return None
    body = response.content
    if url.endswith(".gz") or body[:2] == b"\x1f\x8b":
        try:
            body = gzip.decompress(body)
        except Exception:  # noqa: BLE001
            return None
    return body.decode("utf-8", "replace")


async def sitemap_urls(http, domain: str) -> tuple[str, list[str]]:
    """Every URL a domain's sitemap declares, and how it was found."""
    candidates: list[str] = []
    how = "none"

    robots = await fetch(http, f"https://{domain}/robots.txt")
    if robots:
        declared = DECLARED.findall(robots)
        if declared:
            candidates.extend(declared)
            how = "robots"
    candidates.extend(f"https://{domain}{path}" for path in CONVENTIONAL)

    for candidate in candidates:
        body = await fetch(http, candidate)
        if not body or "<loc" not in body.lower():
            continue
        locs = LOC.findall(body)
        if "<sitemapindex" in body.lower():
            # An index: its locs are child sitemaps, not pages.
            found: list[str] = []
            for child in locs[:MAX_CHILDREN]:
                child_body = await fetch(http, child)
                if child_body:
                    found.extend(LOC.findall(child_body))
            if found:
                return (how if how != "none" else "conventional") + "+index", found[:MAX_URLS]
            continue
        if locs:
            return (how if candidate in (robots or "") else "conventional"), locs[:MAX_URLS]
    return "none", []


def segments(url: str) -> list[str]:
    path = urlparse(url).path.strip("/").lower()
    return [s for s in path.split("/") if s and not s.endswith((".pdf", ".jpg", ".png"))]


async def main(limit: int) -> None:
    async with SessionLocal() as session:
        domains = list(
            (
                await session.execute(
                    select(Account.domain)
                    .where(Account.domain.isnot(None), Account.domain != "")
                    .order_by(Account.name)
                    .limit(limit)
                )
            ).scalars()
        )

    found: dict[str, list[str]] = {}
    hows: Counter[str] = Counter()
    async with client(12.0) as http:
        results = await asyncio.gather(
            *(sitemap_urls(http, d) for d in domains), return_exceptions=True
        )
    for domain, result in zip(domains, results, strict=True):
        if isinstance(result, Exception):
            hows["error"] += 1
            continue
        how, urls = result
        hows[how] += 1
        if urls:
            found[domain] = urls

    print(f"domains: {len(domains)}   with a sitemap: {len(found)}")
    print("  how found: " + ", ".join(f"{k}={v}" for k, v in hows.most_common()))
    print(f"  urls harvested: {sum(len(v) for v in found.values())}")

    # Which spellings actually occur, per theme, and on how many sites. Scored
    # through `sitemap.classify`, so the prefix rules and the first-segment-only
    # rule are measured as the sweep applies them rather than approximated here.
    per_theme: dict[str, Counter[str]] = {k: Counter() for k in THEMES}
    sites_with: dict[str, set[str]] = defaultdict(set)
    vocabulary: Counter[str] = Counter()
    for domain, urls in found.items():
        seen_here: dict[str, set[str]] = defaultdict(set)
        for url in urls:
            parts = segments(url)
            if not parts:
                continue
            vocabulary.update(parts)
            what = sitemap.classify(url)
            if what is not None:
                seen_here[what[0]].add(parts[0])
        for theme, segs in seen_here.items():
            sites_with[theme].add(domain)
            for seg in segs:
                per_theme[theme][seg] += 1

    for theme in THEMES:
        print(f"\n{theme}: on {len(sites_with[theme])} of {len(found)} sites with a sitemap")
        for seg, n in per_theme[theme].most_common(14):
            print(f"    {n:>3} sites   /{seg}")

    # What the sweep would actually fetch. The point of the exercise: a theme
    # the vocabulary recognises but `pick` never selects buys nothing.
    print(f"\nwhat the sweep would fetch (limit {site_sweep.MAX_SITEMAP_PAGES} per account):")
    picked_themes: Counter[str] = Counter()
    hubs_only = 0
    nothing = 0
    for domain, urls in found.items():
        chosen = sitemap.pick(
            sitemap.Sitemap(tuple(sitemap.Entry(u) for u in urls)),
            limit=site_sweep.MAX_SITEMAP_PAGES,
        )
        if not chosen:
            nothing += 1
            continue
        if all(p.hub for p in chosen):
            hubs_only += 1
        for page in chosen:
            picked_themes[f"{page.theme} {'section' if page.hub else 'article'}"] += 1
    for label, n in picked_themes.most_common():
        print(f"    {n:>4}  {label}")
    print(
        f"    {nothing} site(s) with a sitemap that names no page we recognise "
        f"— these fall through to the {len(site_sweep.PAGE_PATHS)} guessed paths"
    )

    print("\nmost common path segments overall (for spotting a theme we did not name):")
    for seg, n in vocabulary.most_common(28):
        print(f"    {n:>4}  /{seg}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=60)
    asyncio.run(main(parser.parse_args().limit))
