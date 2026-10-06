"""Clear every account, contact and everything discovered about them.

The book is test data on a system still being designed, and the owner's
standing instruction is to purge a conflicting one rather than spend time
reconciling it. This is that purge, written down so it is the same every time
and so what it spares is explicit rather than remembered.

**What goes:** accounts and contacts — dormant included — and everything that
hangs off them: evidence, signals, qualifications, runs, coverage, context,
suggestions, strategies, campaign queues and outreach rows.

**What stays, and why each one matters:**

* `llm_call` — the measurement ledger. It has no foreign key to an account, so
  it survives a cascade anyway, and it is the basis of every efficiency
  conclusion in `docs/13`. Never purge it to resolve a data conflict.
* All configuration: signal types, research sources, ICP profiles and their
  version chain, prompt templates, model config, scoring, services, cadence
  shapes, credentials. Purging the book must not cost the registry that took
  a week to shape.

**Invariant 2 is not suspended.** "Evidence is never deleted" protects a
signal's citation *within* a book — it is what stops a tidy-up breaking
explainability. Clearing the whole book is a different act: nothing is left to
cite, and nothing becomes unexplainable. `b4f8d1a27c95` made the same call.

**One thing it cannot undo.** A contact carrying an `lgm_identity_id` may have
a lead record in La Growth Machine. Deleting it here leaves that lead there,
untracked — harmless while no sequence is live, but it is the one effect that
does not stop at this database, so the script says so before it acts.

    python scripts/purge_book.py            # count what would go
    python scripts/purge_book.py --apply    # delete it
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.database import SessionLocal  # noqa: E402

#: Deleted in this order. Children first, because five foreign keys to
#: `account` and `contact` are **not** `ON DELETE CASCADE` — `outreach_sequence`,
#: `strategy_thread`, `persona_service_score`, `deferred_enrolment` and
#: `campaign_queue_member` would each refuse the delete rather than follow it.
#: The cascading ones are listed too: naming every table makes the count
#: honest and means a new table added to the schema shows up as a gap here
#: rather than silently surviving.
ORDER = (
    "outreach_event",
    "deferred_enrolment",
    "outreach_sequence",
    "strategy_thread",
    "strategy",
    "persona_service_score",
    "campaign_queue_contact",
    "campaign_queue_member",
    "campaign_queue",
    "signal_evidence",
    "signal",
    "qualification",
    "research_coverage",
    "contact_suggestion",
    "evidence",
    "account_context",
    "account_alias",
    "account_list_member",
    "contact",
    "run",
    "account",
    "account_list",
)

#: Named so the script states what it protects rather than relying on the
#: reader to notice it is absent from `ORDER`.
KEPT = (
    "llm_call",
    "signal_type",
    "research_source",
    "icp_profile",
    "icp_profile_version",
    "prompt_template",
    "llm_config",
    "scoring_config",
    "service_catalog",
    "cadence_shape",
    "integration_credential",
)


async def main(apply: bool) -> None:
    async with SessionLocal() as session:
        missing = [t for t in ORDER if not await _exists(session, t)]
        if missing:
            print(f"not in this schema, skipped: {', '.join(missing)}")

        tables = [t for t in ORDER if t not in missing]
        before = {t: await _count(session, t) for t in tables}
        total = sum(before.values())

        print("\nto delete")
        for table in tables:
            if before[table]:
                print(f"  {table:24} {before[table]:>6}")
        print(f"  {'':24} {'':->6}\n  {'total':24} {total:>6}")

        print("\nkept")
        for table in KEPT:
            if await _exists(session, table):
                print(f"  {table:24} {await _count(session, table):>6}")

        enrolled = await _count(session, "contact", "lgm_identity_id IS NOT NULL")
        if enrolled:
            print(
                f"\n{enrolled} contact(s) carry an LGM identity. Their lead records stay "
                "in La Growth Machine and stop being tracked here — clear them there "
                "if that matters."
            )

        if not apply:
            print("\nDry run. Re-run with --apply to delete.")
            return

        # One transaction: a half-purged book is worse than either state, and
        # the foreign keys mean a failure part-way would leave rows whose
        # parents are gone.
        for table in tables:
            await session.execute(text(f"DELETE FROM {table}"))  # noqa: S608 — fixed list
        await session.commit()

        after = sum([await _count(session, t) for t in tables])
        print(f"\ndeleted {total} row(s) across {len(tables)} tables; {after} remain")


async def _exists(session, table: str) -> bool:
    return bool(
        (
            await session.execute(
                text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = :t"
                ).bindparams(t=table)
            )
        ).scalar()
    )


async def _count(session, table: str, where: str = "TRUE") -> int:
    return (
        await session.execute(text(f"SELECT COUNT(*) FROM {table} WHERE {where}"))  # noqa: S608
    ).scalar_one()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="actually delete")
    asyncio.run(main(parser.parse_args().apply))
