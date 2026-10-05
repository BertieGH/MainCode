"""Can each registered source actually be reached, and will it actually run?

"Reachable" is four questions, not one, and a source can pass three and still
never produce a thing. `build_plan` applies them in this order:

1. **Active?** A paused or retired source is skipped outright.
2. **In the ICP's `sources` list?** That list *takes precedence over what the
   signal types claim*. A source three types name but the ICP omits never runs;
   a source the ICP names but nobody claims runs anyway, as an `extra`.
3. **A `search` or `fetch` kind?** `provider` and `manual` are excluded from
   research planning on purpose — fanning research over a provider would spend
   Apollo credits like tokens, and "running" a source whose definition is that
   a rep typed something is meaningless. Their coverage is reported from where
   the work happens.
4. **Scope.** A company-scoped source cannot run for a contact.

Then, past the gates, there is what it has actually returned — read from
`research_coverage`, not from `evidence`, because the interesting case is the
source that *was* read and gave nothing, which no evidence row can express.

    python scripts/audit_sources.py
    python scripts/audit_sources.py --csv docs/source-health-2026-10-05.csv

Read-only. Writes nothing to the database, spends no credits, makes no network
calls: every answer here is already there.

`--csv` writes the same table to a file, as the **baseline for the registry
restructure**. Worth taking before the registry changes shape, because the
numbers live in `research_coverage`, which is keyed by the source key and
cascades off `account`: rename or purge either and the measured record of what
each source produced is gone. This file is what "better than before" gets
judged against.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.config import (  # noqa: E402
    IcpProfileVersion,
    ResearchSource,
    SignalType,
)
from app.services import sources as source_service  # noqa: E402

#: Kinds `build_plan` will schedule. The others are deliberate exclusions.
PLANNABLE = ("search", "fetch")


async def main(csv_path: Path | None = None) -> None:
    async with SessionLocal() as session:
        registry = list(
            (await session.execute(select(ResearchSource).order_by(ResearchSource.key))).scalars()
        )
        types = list(
            (
                await session.execute(select(SignalType).where(SignalType.status == "active"))
            ).scalars()
        )
        icp_sources, icp_label = await _icp_sources(session)
        health = await source_service.health(session)

        claims: dict[str, list[str]] = {}
        for st in types:
            for key in st.produced_by or []:
                claims.setdefault(key, []).append(st.key)

        rows = []
        for src in registry:
            blocked = _why_not(src, icp_sources)
            stat = health.get(src.key)
            rows.append(
                {
                    "key": src.key,
                    "kind": src.kind,
                    "status": src.status,
                    "claims": len(claims.get(src.key, ())),
                    "in_icp": "-" if icp_sources is None else ("yes" if src.key in icp_sources else "NO"),
                    "attempts": stat.attempts if stat else 0,
                    "evidence": stat.evidence if stat else 0,
                    "verdict": blocked or _verdict(stat),
                }
            )

        _print(rows, icp_label)
        _notes(rows, registry, claims)
        if csv_path is not None:
            _write_csv(rows, csv_path, icp_label)


def _write_csv(rows: list[dict], path: Path, icp_label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["key", "kind", "status", "claims", "in_icp", "attempts", "evidence", "verdict"],
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nbaseline written to {path} (gates applied against {icp_label})")


async def _icp_sources(session) -> tuple[set[str] | None, str]:
    """The active ICP's accepted sources, or None when it names none.

    None is not the empty set: an ICP that has accepted no list keeps the older
    behaviour, where the plan is the union of what the types claim.
    """
    version = (
        await session.execute(
            select(IcpProfileVersion).where(IcpProfileVersion.is_active.is_(True))
        )
    ).scalars().first()
    if version is None:
        return None, "no active ICP"
    listed = (version.definition or {}).get("sources")
    if not isinstance(listed, list) or not listed:
        return None, f"ICP v{version.version} names no sources"
    return {k for k in listed if isinstance(k, str)}, f"ICP v{version.version}"


def _why_not(src: ResearchSource, icp_sources: set[str] | None) -> str:
    """The first gate this source fails, in the order `build_plan` applies them."""
    if src.status != "active":
        return f"NEVER RUNS - {src.status}"
    # Kind before ICP membership, though `build_plan` tests it after: a
    # `provider` absent from the ICP list fails both gates, and reporting the
    # list implies that adding it there would help. It would not.
    if src.kind not in PLANNABLE:
        return f"not planned by design ({src.kind})"
    if icp_sources is not None and src.key not in icp_sources:
        return "NEVER RUNS - not in the ICP's sources"
    return ""


def _verdict(stat) -> str:
    if stat is None or stat.attempts == 0:
        return "untried - no run since it was wired"
    if stat.evidence:
        return f"producing ({stat.evidence} over {stat.attempts} attempts)"
    if stat.is_dead_weight:
        return f"DEAD WEIGHT - {stat.attempts} attempts, nothing"
    return f"quiet - {stat.attempts} attempts, nothing yet"


def _print(rows: list[dict], icp_label: str) -> None:
    cols = ("key", "kind", "status", "claims", "in_icp", "attempts", "evidence", "verdict")
    widths = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
    print(f"\nSource reachability - gates applied against {icp_label}\n")
    print("  ".join(c.ljust(widths[c]) for c in cols))
    print("  ".join("-" * widths[c] for c in cols))
    for r in rows:
        print("  ".join(str(r[c]).ljust(widths[c]) for c in cols))


def _notes(rows: list[dict], registry: list[ResearchSource], claims: dict) -> None:
    print()
    never = [r["key"] for r in rows if r["verdict"].startswith("NEVER RUNS")]
    if never:
        print(f"{len(never)} source(s) cannot run at all: {', '.join(never)}")
    dead = [r["key"] for r in rows if r["verdict"].startswith("DEAD WEIGHT")]
    if dead:
        print(f"{len(dead)} tried enough to judge and produced nothing: {', '.join(dead)}")
    unclaimed = [
        r["key"] for r in rows
        if not r["claims"] and r["in_icp"] == "yes" and r["kind"] in PLANNABLE
    ]
    if unclaimed:
        print(
            f"{len(unclaimed)} run as an 'extra' - in the ICP, named by no signal type: "
            f"{', '.join(unclaimed)}"
        )
    orphan = sorted(set(claims) - {s.key for s in registry})
    if orphan:
        print(f"claimed by a type but absent from the registry: {', '.join(orphan)}")
    stale = [
        s.key for s in registry
        if s.status == "active" and (s.status_reason or "").strip()
    ]
    if stale:
        print(
            f"active but still carrying a status_reason (written while paused?): "
            f"{', '.join(stale)}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv", type=Path, default=None,
        help="also write the table here, as a baseline to judge the restructure against",
    )
    asyncio.run(main(parser.parse_args().csv))
