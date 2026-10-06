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

    SEARLO_API_KEY=... python scripts/trial_serp.py "Beach and O'Neill Insurance" "Agentero"

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

from app.services.enrichment_clients import _client  # noqa: E402

from app.services import linkedin  # noqa: E402

#: Searlo's live SERP read. The key travels in a header, is read from the
#: environment, and is **never printed** — a trial that leaked a credential
#: into a terminal log would breach invariant 9 to answer a question about
#: coverage.
SEARLO = "https://api.searlo.tech/api/v1/search/web"

#: The X-Ray forms, exactly as `b6d4a8f32e07` wrote them into the registry.
#: `/in` is the employee question — counting distinct profiles across two runs
#: is the snapshot delta §82 could not get from grounding, which has no
#: pagination and excludes linkedin.com besides.
QUERIES = {
    "profiles": 'site:linkedin.com/in "{company}"',
    "posts": 'site:linkedin.com/posts "{company}"',
    "company_page": 'site:linkedin.com/company "{company}"',
}

TIMEOUT = 90.0


async def search(client: httpx.AsyncClient, key: str, query: str, want: int) -> dict:
    """One SERP query. Returns the parsed body, whatever shape it is in."""
    response = await client.get(
        SEARLO,
        params={"q": query, "num": want},
        headers={"x-api-key": key},
        timeout=TIMEOUT,
    )
    if response.status_code >= 400:
        # The body names the parameter it wanted, which beats guessing from a
        # marketing page — but it can also echo the request, so it is trimmed
        # and never the key itself.
        raise RuntimeError(f"{response.status_code}: {response.text[:300]}")
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
    key = os.environ.get("SEARLO_API_KEY", "").strip()
    if not key:
        print("SEARLO_API_KEY is not set. Nothing was called.")
        return

    # The shared client, which trusts the **OS** certificate store via
    # `truststore`. This machine runs a TLS-inspection agent whose CA is in
    # the Windows store and not in certifi, so a plain httpx client fails to
    # verify. Reusing the app's client keeps verification on: turning it off
    # would be circumventing the inspection agent, which is IT policy and
    # not something a trial script gets to decide.
    async with _client(TIMEOUT) as client:
        for company in companies:
            print(f"\n=== {company} " + "=" * max(0, 60 - len(company)))
            for label, template in QUERIES.items():
                query = template.format(company=company)
                try:
                    rows = await search(client, key, query, want)
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
