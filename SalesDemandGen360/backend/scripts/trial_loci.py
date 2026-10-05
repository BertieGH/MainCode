"""Trial the proposed place-shaped loci before any of them is stored.

The registry's problem is that seven of its seventeen rows are named after what
you hope to find — `funding`, `hiring`, `leadership`, `tech_stack`,
`content_activity`, `news`, `reviews` — rather than where to look. A signal
type then names `hiring` and the two say the same thing twice, neither of them
saying where to go.

These are the replacements, written as places. Each is run against a sample of
real accounts through `source_trial`, which uses the real prompt and the real
model and stores nothing. Whatever does not produce here does not get stored.

    python scripts/trial_loci.py                 # every candidate
    python scripts/trial_loci.py trade_press     # just these

Costs model calls - one per candidate per account.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.account import Account  # noqa: E402
from app.services import source_trial  # noqa: E402

#: Three accounts, not one: a single account proves nothing about a source, and
#: `source_trial` caps the sample anyway. Chosen for having a domain.
SAMPLE = 3

CANDIDATES = [
    {
        "key": "trade_press",
        "label": "Trade press and wire services",
        "description": (
            "Insurance and technology trade publications, and the wire services "
            "companies file announcements to - Business Insurance, Insurance "
            "Journal, Reinsurance News, PR Newswire, Business Wire. Read for "
            "what has been announced about this company by somebody other than "
            "the company: an acquisition, an appointment, a new programme, a "
            "carrier appointment, an office opening. Quote the sentence and keep "
            "the publication date."
        ),
        "scopes": ["company"],
        "kind": "search",
    },
    {
        "key": "review_sites",
        "label": "Employee and customer review sites",
        "description": (
            "Glassdoor, Indeed and Google Maps reviews for this company. Read "
            "for recurring themes stated by employees or customers about how "
            "the business runs - systems people complain about, manual process, "
            "service delays, growth or churn in a team. Not software review "
            "sites: G2 and Capterra review products, not the companies that buy "
            "them. A single review is an anecdote; say so only if a theme "
            "repeats."
        ),
        "scopes": ["company"],
        "kind": "search",
    },
    {
        "key": "company_data_providers",
        "label": "Company data and funding providers",
        "description": (
            "Crunchbase, PitchBook, ZoomInfo, Dun and Bradstreet, Bloomberg "
            "profiles and BuiltWith. Read for the structured facts a directory "
            "holds about this company: a funding round with its size, lead "
            "investor and date; headcount and its direction; the technologies "
            "detected on its domain; parent or subsidiary ownership. State the "
            "provider as the source and date the fact where the provider dates "
            "it."
        ),
        "scopes": ["company"],
        "kind": "search",
    },
    {
        "key": "conference_and_podcast_circuit",
        "label": "Conference, podcast and panel circuit",
        "description": (
            "Conference agendas and speaker bios, podcast episode pages, webinar "
            "listings and trade-press interviews. Read for a named person at "
            "this company saying something in public, in their own words: a "
            "problem they have, a programme they are running, a priority for "
            "the year. Give the person, the event or episode, the date, and the "
            "quote. An industry opinion is not a statement about their own work."
        ),
        "scopes": ["company", "contact"],
        "kind": "search",
    },
]


async def main(only: set[str]) -> None:
    async with SessionLocal() as session:
        accounts = list(
            (
                await session.execute(
                    select(Account)
                    .where(Account.domain.isnot(None), Account.domain != "")
                    .order_by(Account.name)
                    .limit(SAMPLE)
                )
            ).scalars()
        )
        if not accounts:
            print("no accounts with a domain — nothing to trial against")
            return
        print(f"sample: {', '.join(a.name or '?' for a in accounts)}\n")

        rows = []
        for candidate in CANDIDATES:
            if only and candidate["key"] not in only:
                continue
            report = await source_trial.try_source(
                session,
                candidate=candidate,
                account_ids=[a.id for a in accounts],
            )
            rows.append((candidate["key"], report))
            print(f"{candidate['key']:32} {report.verdict}")
            for trial in report.trials:
                head = f"    {(trial.account_name or '?')[:28]:28}"
                if not trial.ok:
                    print(f"{head} FAILED {trial.error[:60]}")
                    continue
                print(f"{head} {len(trial.found)} found  {trial.duration_ms}ms")
                for found in trial.found[:2]:
                    when = found.observed_at or "undated"
                    print(f"        {when}  {(found.title or found.excerpt)[:72]}")
            print()

        print("=" * 78)
        for key, report in rows:
            verdict = "STORE" if report.found else "do not store"
            print(
                f"{key:32} {verdict:14} found={report.found:3} dry={report.dry} "
                f"failed={report.failed} in={report.input_tokens} out={report.output_tokens}"
            )


if __name__ == "__main__":
    asyncio.run(main(set(sys.argv[1:])))
