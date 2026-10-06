"""Does Google's index actually hold anything about a small company's people?

`linkedin_index` has been registered and inert since `b6d4a8f32e07`: the X-Ray
queries are written, three contact signal types name it, and nothing runs
because no SERP credential exists. Gemini grounding cannot stand in — it
excludes `linkedin.com` for everyone (§64, four confirmations) and returns
cited passages rather than a result set, so it can neither reach these pages
nor count them.

This asks the one question that decides whether any of that work pays off:
**for a company of twenty-five people, is there anything in Google's index to
find?** Every other question — accuracy, freshness, cost — is downstream of it,
and 47 of 57 accounts producing nothing is the reason to doubt it.

Nothing here opens `linkedin.com`. A SERP API returns Google's index of public
pages, which is the whole distinction the registry is built on and the reason
`linkedin` is deprecated while `linkedin_index` is not.

    APIFY_TOKEN=... python scripts/trial_serp.py "Beach and O'Neill Insurance" "Agentero"

Stores nothing. Costs a few SERP pages per company — fractions of a cent.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.services import linkedin  # noqa: E402

#: Apify's synchronous run: start the actor, wait, return the dataset. The
#: token goes in the query string because that is the only form this endpoint
#: accepts; it is read from the environment and **never printed**, so a pasted
#: terminal log cannot leak it (invariant 9).
RUN = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"

#: Default actor. Community actors differ in input schema, so `--actor` and
#: `--input-key` exist for swapping one in without editing this file.
ACTOR = os.environ.get("APIFY_ACTOR", "scraperlink~google-search-results-serp-scraper")

#: The X-Ray forms, exactly as `b6d4a8f32e07` wrote them into the registry.
#: `/in` is the employee question — and counting distinct profiles across two
#: runs is the snapshot delta that §82 could not get from grounding, because
#: grounding has no pagination.
QUERIES = {
    "profiles": 'site:linkedin.com/in "{company}"',
    "posts": 'site:linkedin.com/posts "{company}"',
    "company_page": 'site:linkedin.com/company "{company}"',
}

TIMEOUT = 180.0


async def search(client: httpx.AsyncClient, token: str, query: str, want: int) -> list[dict]:
    """One SERP query. Returns whatever rows the actor produced, unflattened."""
    body = {
        # The names most Google-SERP actors share. A 400 here names the field
        # the chosen actor wanted instead, which is faster to read than any
        # amount of guessing from a marketing page.
        "queries": query,
        "maxPagesPerQuery": max(1, want // 10),
        "resultsPerPage": 10,
        "countryCode": "us",
        "languageCode": "en",
    }
    response = await client.post(
        RUN.format(actor=ACTOR), params={"token": token}, json=body, timeout=TIMEOUT
    )
    if response.status_code >= 400:
        raise RuntimeError(f"{response.status_code}: {response.text[:400]}")
    return response.json()


def urls_in(rows: list[dict]) -> list[str]:
    """Every URL in the payload, whatever shape the actor used.

    Actors disagree about where results live — `organicResults`, `results`, or
    the row itself — so this walks the structure rather than assuming one. A
    trial that returned nothing because of a key name would be indistinguishable
    from a trial that proved the index is empty, and that is the one confusion
    worth spending code to avoid.
    """
    found: list[str] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("url", "link") and isinstance(value, str):
                    found.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(rows)
    return found


async def main(companies: list[str], want: int) -> None:
    token = os.environ.get("APIFY_TOKEN", "").strip()
    if not token:
        print("APIFY_TOKEN is not set. Nothing was called.")
        return

    async with httpx.AsyncClient() as client:
        for company in companies:
            print(f"\n=== {company} " + "=" * max(0, 60 - len(company)))
            for label, template in QUERIES.items():
                query = template.format(company=company)
                try:
                    rows = await search(client, token, query, want)
                except Exception as exc:  # noqa: BLE001 — a failed query is a result
                    print(f"  {label:13} FAILED  {exc}")
                    continue

                urls = [u for u in urls_in(rows) if linkedin.is_linkedin(u)]
                people = {s for u in urls if (s := linkedin.person_slug(u))}
                dated = [d for u in urls if (d := linkedin.post_date(u))]

                print(f"  {label:13} {len(urls):>3} linkedin urls", end="")
                if label == "profiles":
                    print(f" · {len(people)} distinct people", end="")
                if dated:
                    print(f" · {len(dated)} dated, newest {max(dated)}", end="")
                print()
                for url in urls[:3]:
                    print(f"      {url[:96]}")

    print(
        "\nWhat this decides: distinct people per company is the snapshot a delta "
        "is measured from.\nA company with none in the index cannot produce a contact "
        "signal by this route, whatever\nthe wording — and the three contact types "
        "that name linkedin_index should be dropped\nrather than left waiting."
    )


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    results = 30
    for flag in sys.argv[1:]:
        if flag.startswith("--results="):
            results = int(flag.split("=", 1)[1])
    if not args:
        print(__doc__)
        print("Give at least one company name.")
    else:
        asyncio.run(main(args, results))
