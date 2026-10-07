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

It harvests **through `sitemap.discover` itself**, not through a copy of its
logic. This script is what widened `sitemap.THEMES` and ranked the index
children, and it is also what checks that the widening worked — so it has to
exercise the reader the sweep will actually use. A second implementation here
would drift, and the drift would read as a result: the first version of this
script reported 6,487 URLs harvested while the reader, which now skips media
and taxonomy children, sees far fewer.

    python scripts/survey_sitemaps.py
    python scripts/survey_sitemaps.py --limit 20
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.account import Account  # noqa: E402
from app.services import site_sweep, sitemap  # noqa: E402
from app.services.site_sweep import _get_bytes, client  # noqa: E402

THEMES = sitemap.THEMES


async def sitemap_urls(http, domain: str) -> tuple[str, list[str]]:
    """Every URL the reader would see for a domain, and how it found it.

    The robots.txt fetch is the one thing done here rather than in `discover`,
    because in the sweep it has already happened — `site_sweep.answers` reads
    it to decide whether the host answers at all, and `discover` takes the
    parsed rules from that. Doing it here keeps the measurement honest about
    what `discover` costs: candidates only, no robots fetch of its own.
    """
    rules = RobotFileParser()
    raw = await _get_bytes(http, f"https://{domain}/robots.txt")
    rules.parse((raw.decode("utf-8", "replace") if raw else "").splitlines())
    declared = bool(rules.site_maps())

    found = await sitemap.discover(http, domain, {f"https://{domain}": rules})
    if not found:
        return "none", []
    how = "robots" if declared and found.found_at in (rules.site_maps() or []) else "conventional"
    return how, [e.url for e in found.entries]


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
