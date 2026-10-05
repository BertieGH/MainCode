"""Run a candidate source before it is stored, and show what it returns.

A source added to the registry starts costing a read per account immediately,
and whether it was worth adding is only visible afterwards — by which point the
calls are spent and the coverage rows are written. `job_board` took 26 attempts
to establish that it finds nothing for a book of brokerages. Every one of those
was paid for.

So: run the real call, show what came back and what it cost, and **store
nothing**. The caller reads it, edits the wording, runs it again, and only then
saves a source that is already known to work.

**The trial is the real path or it is worthless.** A search goes through
`stages.research_family` with a `candidate` override, which means the same
prompt, the same model, the same effort and the same output contract as a
stored source — the only difference is that the definition comes from the
request instead of from a registry row, and that `evidence_service.store_found`
is never reached. A fetch goes through `site_sweep.sweep_account`, which is
already read-only.

What it cannot do is test a route that has no client. `provider` and `manual`
are refused rather than faked: a green trial for a route nothing implements is
the exact failure this module exists to prevent — `linkedin_serp` sat
"configured" for a day with no credential, no client and nothing saying so.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.schemas.evidence import FoundEvidence

log = logging.getLogger(__name__)

#: Routes a trial can actually exercise. The others are refused by name.
TESTABLE = ("search", "fetch")

#: Hard ceiling on accounts per trial. A trial is a sample, not a run: six
#: grounded searches is already enough to see whether the wording works, and an
#: unbounded list would let a "test" cost more than the thing being tested.
MAX_ACCOUNTS = 6


@dataclass
class AccountTrial:
    """What one candidate source returned for one account."""

    account_id: uuid.UUID
    account_name: str
    found: list[FoundEvidence] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class TrialReport:
    """Every account tried, plus the totals worth deciding on."""

    candidate: dict
    route: str
    trials: list[AccountTrial] = field(default_factory=list)

    @property
    def accounts(self) -> int:
        return len(self.trials)

    @property
    def found(self) -> int:
        return sum(len(t.found) for t in self.trials)

    @property
    def dry(self) -> int:
        """Accounts the candidate returned nothing for.

        Reported separately from failures. "Looked and there is nothing here"
        is a legitimate answer about an account and a damning one about a
        source — the difference is whether it holds across the sample.
        """
        return sum(1 for t in self.trials if t.ok and not t.found)

    @property
    def failed(self) -> int:
        return sum(1 for t in self.trials if not t.ok)

    @property
    def input_tokens(self) -> int:
        return sum(t.input_tokens for t in self.trials)

    @property
    def output_tokens(self) -> int:
        return sum(t.output_tokens for t in self.trials)

    @property
    def verdict(self) -> str:
        """One line a person can act on, in the shape the audit uses."""
        if not self.trials:
            return "no accounts to try"
        if self.failed == self.accounts:
            return f"FAILED at every account ({self.accounts}) - the route or the query is wrong"
        if not self.found:
            return (
                f"nothing at any of {self.accounts} accounts - do not store this "
                "without changing the wording"
            )
        return (
            f"{self.found} passage(s) across {self.accounts} accounts, "
            f"{self.dry} of them empty"
        )


class NotTestable(Exception):
    """The route has no client, so a trial would be a lie rather than a test."""


async def try_source(
    session: AsyncSession,
    *,
    candidate: dict,
    account_ids: list[uuid.UUID],
    client=None,
) -> TrialReport:
    """Run `candidate` against a few real accounts without storing anything.

    `candidate` is the source definition as it would be saved — `key`, `label`,
    `description`, `scopes`, `kind`. The description is the load-bearing part:
    it is what the research prompt reads as "what to read this source for", so
    a trial is mostly a test of that wording.
    """
    route = (candidate.get("kind") or "search").strip()
    if route not in TESTABLE:
        raise NotTestable(
            f"{route!r} cannot be trialled: it has no client to run. "
            f"Testable routes are {', '.join(TESTABLE)}. A source on an "
            "untestable route can still be stored, but nothing will have "
            "checked that it works."
        )

    wanted = account_ids[:MAX_ACCOUNTS]
    accounts = list(
        (await session.execute(select(Account).where(Account.id.in_(wanted)))).scalars()
    )
    # Requested order, not database order: the caller picked these accounts to
    # look at in a particular order and the report is read top to bottom.
    by_id = {a.id: a for a in accounts}
    ordered = [by_id[i] for i in wanted if i in by_id]

    report = TrialReport(candidate=candidate, route=route)
    for account in ordered:
        report.trials.append(await _one(session, account, candidate, route, client))

    log.info(
        "source_trial.done key=%s route=%s accounts=%d found=%d dry=%d failed=%d "
        "in=%d out=%d",
        candidate.get("key"), route, report.accounts, report.found, report.dry,
        report.failed, report.input_tokens, report.output_tokens,
    )
    return report


async def _one(
    session: AsyncSession, account: Account, candidate: dict, route: str, client
) -> AccountTrial:
    from app.services import site_sweep, stages

    trial = AccountTrial(account_id=account.id, account_name=account.name or "")
    started = time.monotonic()
    try:
        if route == "fetch":
            swept = await site_sweep.sweep_account(account)
            trial.found = list(swept.batch.evidence)
            trial.not_found = list(swept.batch.not_found)
        else:
            result = await stages.research_family(
                session,
                account=account,
                family=candidate.get("key") or "candidate",
                candidate=candidate,
                client=client,
            )
            trial.found = list(result.parsed.evidence)
            trial.not_found = list(result.parsed.not_found)
            trial.input_tokens = result.input_tokens
            trial.output_tokens = result.output_tokens
    except Exception as exc:  # noqa: BLE001 — a failed trial is a result
        # Caught per account and reported, not raised. One account whose site
        # refuses us says nothing about the candidate; five do. Letting the
        # first failure end the trial would hide that distinction, which is
        # the only thing the sample is for.
        trial.error = f"{type(exc).__name__}: {exc}"
        log.warning(
            "source_trial.failed key=%s account=%s %s",
            candidate.get("key"), account.id, trial.error,
        )
    trial.duration_ms = int((time.monotonic() - started) * 1000)
    return trial
