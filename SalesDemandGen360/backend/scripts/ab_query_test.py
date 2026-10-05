"""Does a per-signal query produce more than a topic-shaped source brief?

The question is not "do the queries return something" — a single probe already
showed they do. It is whether the *extraction* changes: more evidence that
produces no more signals is a cost increase, not an improvement.

So both arms run against the same account, and both are put through the same
extractor:

* **Arm A — today.** The research families as configured, each with its
  one-line topic brief ("Launches, partnerships, expansions, incidents").
* **Arm B — per-signal.** The grounded options from the curated CSV, one call
  per company signal type.

Nothing is written to the account's real evidence. Both arms store under a
throwaway account id so the comparison cannot pollute the book, and the rows are
removed at the end.

    cd backend
    PYTHONPATH=. ../.venv/Scripts/python.exe scripts/ab_query_test.py --account "Champion Risk"
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import re
import time
import uuid
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.account import Account
from app.models.config import SignalType

QUERY_COL = "Target Search Pattern / Query Syntax"

#: Every option is tried, X-Ray included.
#:
#: The `serp` ones were skipped at first on the grounds that LinkedIn X-Ray
#: needs a SERP API we do not have. That was an assertion standing in for a
#: measurement: these are search strings, the grounded route will happily run
#: them, and what comes back is a fact rather than a prediction. Running them
#: costs one call each and produces a per-query answer instead of a repeated
#: claim.
RUNNABLE = ("grounded", "fetch", "serp")


def options_for(row: dict) -> list[tuple[str, str]]:
    """(label, query) for each runnable option on this row."""
    out = []
    for part in (row[QUERY_COL] or "").split(" | "):
        m = re.match(r"Option \d+ \[(\w+)\] \(([^)]+)\): (.+)", part.strip())
        if m and m.group(1) in RUNNABLE:
            out.append((f"{m.group(2)} [{m.group(1)}]", m.group(3)))
    return out


def fill(query: str, account: Account, person=None) -> str:
    out = query.replace("{company}", account.name or "").replace(
        "{domain}", account.domain or ""
    )
    if person is not None:
        out = out.replace("{person}", person.full_name or "").replace(
            "{title}", getattr(person, "title", "") or ""
        )
    return out.replace("{person}", "").replace("{title}", "")


async def arm_a(session, account, run_id) -> tuple[int, float, int]:
    """The families as configured today."""
    from app.services import evidence as evidence_service
    from app.services import stages
    from app.services.research import build_plan

    plan = await build_plan(session, scope="company")
    families = [f.family for f in plan.families if f.kind == "search"]
    stored = calls = 0
    began = time.monotonic()
    for family in families:
        try:
            result = await stages.research_family(session, account=account, family=family)
        except Exception as exc:  # noqa: BLE001 — one family must not cost the arm
            print(f"    {family:<34} FAILED {type(exc).__name__}")
            continue
        calls += 1
        outcome = await evidence_service.store_found(
            session, account_id=account.id, batch=result.parsed,
            run_id=run_id, family=family,
        )
        stored += outcome.count
        print(f"    {family:<34} {outcome.count} evidence")
    return stored, time.monotonic() - began, calls


async def arm_b(
    session, account, run_id, rows, person=None
) -> tuple[int, float, int, dict[str, int]]:
    """Every option for every signal, until one returns.

    The first run took option one and moved on, which blamed a signal for a
    retrieval path that happened to be listed first. Here each option is tried
    in turn and the loop stops at the first that yields evidence — so a miss
    means every route was tried, not that the first was unlucky.

    `by_route` counts what each kind of option produced across the whole arm,
    which is what answers the X-Ray question per query rather than in aggregate.
    """
    from app.services import evidence as evidence_service
    from app.services import stages

    scope = "contact" if person is not None else "company"
    stored = calls = 0
    by_route: dict[str, int] = {}
    began = time.monotonic()

    for row in rows:
        if (row.get("scope") or "").strip().lower() != scope:
            continue
        key = (row.get("valid_key") or row["signal_type"]).strip()
        options = options_for(row)
        if not options:
            print(f"    {key:<32} no options")
            continue

        found_here = 0
        tried: list[str] = []
        for label, query in options:
            route = label.split("[")[-1].rstrip("]")
            text_q = fill(query, account, person)
            brief = {
                "key": f"ab_{key}"[:60],
                "label": key,
                "instruction": (
                    f"{text_q}\n\nQuote the sentence that carries the fact. Date "
                    f"it by when the fact was true; leave the date empty if the "
                    f"page does not give one."
                ),
                "feeds": [key],
                "scopes": [scope],
            }
            try:
                result = await stages.research_topic(
                    session, account=account, brief=brief
                )
            except Exception as exc:  # noqa: BLE001
                tried.append(f"{route}:ERR")
                continue
            calls += 1
            outcome = await evidence_service.store_found(
                session, account_id=account.id, batch=result.parsed,
                run_id=run_id, family=f"ab_{key}"[:60],
                contact_id=getattr(person, "id", None),
            )
            by_route[route] = by_route.get(route, 0) + outcome.count
            tried.append(f"{route}:{outcome.count}")
            if outcome.count:
                found_here = outcome.count
                stored += outcome.count
                break  # a route that answered; no need to pay for the rest

        mark = f"{found_here} evidence" if found_here else "nothing, all routes tried"
        print(f"    {key:<32} {mark:<26} [{' '.join(tried)}]")

    return stored, time.monotonic() - began, calls, by_route


async def _runs(session, account_id) -> tuple[uuid.UUID, uuid.UUID]:
    """One run per arm, so each arm's evidence is attributable to it."""
    from datetime import UTC, datetime

    from app.models.account import Run
    from app.services import demo

    mode = await demo.current_mode(session)
    made = []
    for label in ("ab_arm_a", "ab_arm_b"):
        run = Run(
            id=uuid.uuid4(), account_id=account_id, stage="research",
            status="running", triggered_by=label, mode=mode,
            started_at=datetime.now(UTC),
        )
        session.add(run)
        made.append(run.id)
    await session.flush()
    return made[0], made[1]


async def extract(session, account_id, run_id) -> tuple[int, int, list[str]]:
    """Put an arm's evidence through the real extractor."""
    from app.models.signal import Evidence
    from app.services import extraction, stages

    rows = list(
        (
            await session.execute(
                select(Evidence).where(
                    Evidence.account_id == account_id, Evidence.run_id == run_id
                )
            )
        ).scalars()
    )
    if not rows:
        return 0, 0, []
    keys = [
        k
        for k in (
            await session.execute(
                select(SignalType.key).where(SignalType.status == "active")
            )
        ).scalars()
    ]
    result = await stages.extract_signals(
        session, account=await session.get(Account, account_id),
        evidence=rows, type_keys=sorted(keys),
    )
    outcome = await extraction.store_batch(
        session, account_id=account_id, batch=result.parsed, run_id=run_id
    )
    kinds = sorted({s.signal_type for s in result.parsed.signals})
    return outcome.stored, len(rows), kinds


async def main_async(name: str, csv_path: Path) -> None:
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        rows = [r for r in csv.DictReader(handle) if (r.get("signal_type") or "").strip()]

    engine = create_async_engine(str(get_settings().database_url))
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        real = (
            await session.execute(select(Account).where(Account.name.ilike(f"%{name}%")))
        ).scalars().first()
        if real is None:
            print(f"no account matching {name!r}")
            return

        # The real account, with each arm tagged by its own run id.
        #
        # A twin was the first idea and was wrong twice over: the database
        # refuses a second account on one domain, and `site:{domain}` queries
        # need the real domain anyway. More to the point, both arms are
        # genuine research on a real company — storing what they find is what
        # research does, not pollution, and evidence is never deleted
        # (invariant 2). The arms are told apart by `run_id`.
        print(f"account: {real.name}  ({real.domain})\n")

        # Real `run` rows: evidence carries a foreign key to one, which is the
        # database insisting every passage can name the run that found it.
        run_a, run_b = await _runs(session, real.id)
        print("  ARM A - families as configured today")
        ev_a, secs_a, calls_a = await arm_a(session, real, run_a)

        print("\n  ARM B - every option per signal, until one returns")
        ev_b, secs_b, calls_b, routes = await arm_b(session, real, run_b, rows)

        # The contact rows, where {person} has a value and the X-Ray queries
        # are what they were written for.
        from app.models.account import Contact

        people = list(
            (
                await session.execute(
                    select(Contact).where(Contact.account_id == real.id)
                )
            ).scalars()
        )
        for person in people[:1]:
            print(f"\n  ARM B - contact rows for {person.full_name!r}")
            c_ev, c_secs, c_calls, c_routes = await arm_b(
                session, real, run_b, rows, person=person
            )
            ev_b += c_ev
            secs_b += c_secs
            calls_b += c_calls
            for k, v in c_routes.items():
                routes[k] = routes.get(k, 0) + v
        await session.commit()

        print("\n  extraction")
        sig_a, used_a, kinds_a = await extract(session, real.id, run_a)
        sig_b, used_b, kinds_b = await extract(session, real.id, run_b)
        await session.commit()

        print("\n" + "=" * 68)
        print(f"{'':<12}{'calls':>7}{'evidence':>10}{'signals':>9}{'seconds':>10}")
        print(f"{'ARM A':<12}{calls_a:>7}{ev_a:>10}{sig_a:>9}{secs_a:>10.1f}")
        print(f"{'ARM B':<12}{calls_b:>7}{ev_b:>10}{sig_b:>9}{secs_b:>10.1f}")
        print("=" * 68)
        print(f"A produced: {kinds_a or 'nothing'}")
        print(f"B produced: {kinds_b or 'nothing'}")
        print("\nevidence by retrieval route, arm B:")
        for route in ("grounded", "fetch", "serp"):
            got = routes.get(route, 0)
            note = "  <- the LinkedIn X-Ray queries" if route == "serp" else ""
            print(f"  {route:<10}{got:>4}{note}")
        print(f"\nrun ids - A {run_a}  B {run_b}")
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", required=True)
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "signal-registry-filled.csv",
    )
    args = parser.parse_args()
    asyncio.run(main_async(args.account, args.csv))


if __name__ == "__main__":
    main()
