"""Where research looks — read from the registry, not from code.

`query_families` held a closed tuple and this module replaces it as the
authority. The closure existed for a reason worth restating, because the reason
survives the change: a source key nothing runs is indistinguishable from a
source that ran and found nothing. It reports as a permanent coverage gap on a
prospect who may be perfectly well covered, and nothing errors.

So the key is still checked against a registry before a signal type may claim
it. The registry is just no longer a Python literal.

The other half of the design lives in the callers rather than here, and is the
reason this exists at all: **a source decides what gets opened, never what gets
read out of it.** Extraction reads every document against every active signal
type, so a leadership change mentioned in a job posting is still found.
Narrowing a sweep to the types that named the source would rebuild the
one-search-per-signal-type problem under new names.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.config import ResearchSource
from app.models.research import ResearchCoverage

#: Kinds a rep may create from the screen. `fetch` and `provider` need code
#: behind them — a feed reader, a credentialled waterfall — and a row claiming
#: one with nothing behind it is exactly the silent gap this registry prevents.
CREATABLE_KINDS = ("search",)


async def all_sources(
    session: AsyncSession, *, include_retired: bool = False
) -> list[ResearchSource]:
    stmt = select(ResearchSource).order_by(ResearchSource.key)
    if not include_retired:
        stmt = stmt.where(ResearchSource.status != "deprecated")
    return list((await session.execute(stmt)).scalars())


async def by_key(session: AsyncSession) -> dict[str, ResearchSource]:
    """Every source including retired ones, keyed.

    Retired ones are included deliberately: a run recorded six months ago names
    sources that may since have been retired, and a report that cannot name one
    prints a bare key where a label should be.
    """
    return {s.key: s for s in await all_sources(session, include_retired=True)}


async def for_scope(session: AsyncSession, scope: str) -> list[ResearchSource]:
    return [
        s
        for s in await all_sources(session)
        if scope in (s.scopes or []) and s.status == "active"
    ]


async def validate(session: AsyncSession, keys: list[str], scope: str) -> list[str]:
    """Problems with a list of claimed sources. Empty means fine.

    Every problem rather than the first, so a form naming three bad sources
    says so once instead of over three round trips.
    """
    problems: list[str] = []
    known = await by_key(session)

    unknown = [k for k in keys if k not in known]
    if unknown:
        problems.append(
            f"unknown research sources: {sorted(unknown)}. "
            f"Known sources are {sorted(known)}"
        )

    present = [k for k in keys if k in known]

    wrong_scope = [k for k in present if scope not in (known[k].scopes or [])]
    if wrong_scope:
        available = sorted(k for k, s in known.items() if scope in (s.scopes or []))
        problems.append(
            f"sources not available to {scope} signals: {sorted(wrong_scope)}. "
            f"Available: {available}"
        )

    if len(set(present)) != len(present):
        problems.append("duplicate research sources")

    # A type whose only source can never create a signal can never fire. It
    # would sit in the registry looking configured and produce nothing, forever.
    in_scope = [k for k in present if scope in (known[k].scopes or [])]
    if in_scope and all(known[k].support_only for k in in_scope):
        support = sorted({k for k in in_scope if known[k].support_only})
        problems.append(
            f"{support} can support a signal but never create one, so this type "
            "would never fire. Pair it with another source."
        )

    return problems


# ==========================================================================
# is this source still earning its place?
# ==========================================================================
#: Consecutive failures at one account before a source stops being tried there.
QUARANTINE_AFTER = 3


@dataclass(frozen=True)
class SourceHealth:
    """What one source has actually produced, across every account."""

    key: str
    accounts: int
    evidence: int
    ran: int
    empty: int
    failed: int
    last_seen: datetime | None

    @property
    def attempts(self) -> int:
        return self.ran + self.empty + self.failed

    @property
    def is_dead_weight(self) -> bool:
        """Tried at several accounts and never produced anything.

        Not an error and never auto-disabled — some sources are legitimately
        quiet, and a source silently stopping is the coverage lie this module
        exists to prevent. It is a prompt to look, because a registry only ever
        grows and a dead source costs a read per account forever.
        """
        return self.attempts >= 5 and self.evidence == 0


async def health(session: AsyncSession, *, days: int = 90) -> dict[str, SourceHealth]:
    """Per source: how often it was tried and what it returned.

    Read from coverage rather than from evidence, because the interesting case
    is the source that was read and gave nothing — which no evidence row can
    express.
    """
    since = datetime.now(UTC) - timedelta(days=days)
    rows = await session.execute(
        select(
            ResearchCoverage.family,
            ResearchCoverage.status,
            func.count().label("n"),
            func.count(func.distinct(ResearchCoverage.account_id)).label("accounts"),
            func.sum(ResearchCoverage.evidence_count).label("evidence"),
            func.max(ResearchCoverage.created_at).label("last_seen"),
        )
        .where(ResearchCoverage.created_at >= since)
        .group_by(ResearchCoverage.family, ResearchCoverage.status)
    )

    acc: dict[str, dict] = {}
    for family, status, n, accounts, evidence, last_seen in rows.all():
        cur = acc.setdefault(
            family,
            {
                "accounts": 0, "evidence": 0, "ran": 0, "empty": 0, "failed": 0,
                "last_seen": None,
            },
        )
        cur["accounts"] = max(cur["accounts"], accounts or 0)
        cur["evidence"] += int(evidence or 0)
        if status in ("ran", "empty", "failed"):
            cur[status] += int(n or 0)
        if last_seen and (cur["last_seen"] is None or last_seen > cur["last_seen"]):
            cur["last_seen"] = last_seen

    return {key: SourceHealth(key=key, **vals) for key, vals in acc.items()}


async def quarantined(session: AsyncSession, account_id: uuid.UUID) -> dict[str, str]:
    """Sources that have failed at this account often enough to stop trying.

    Per account, not globally: a site that blocks our agent blocks it for that
    company only. The reason travels with it so the screen can say why rather
    than showing an unexplained hole.
    """
    rows = list(
        (
            await session.execute(
                select(ResearchCoverage)
                .where(
                    ResearchCoverage.account_id == account_id,
                    ResearchCoverage.contact_id.is_(None),
                )
                .order_by(ResearchCoverage.created_at.desc())
            )
        ).scalars()
    )
    runs: dict[str, list] = {}
    for row in rows:
        runs.setdefault(row.family, []).append(row)

    out: dict[str, str] = {}
    for family, history in runs.items():
        streak = 0
        detail = None
        for row in history:
            if row.status != "failed":
                break
            streak += 1
            detail = detail or row.detail
        if streak >= QUARANTINE_AFTER:
            out[family] = f"failed {streak} times running at this account" + (
                f" — {detail}" if detail else ""
            )
    return out
