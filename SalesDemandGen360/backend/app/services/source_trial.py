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
#:
#: Halved when a B variant is given, because an A/B runs both against every
#: account and the ceiling is on calls, not on rows.
MAX_ACCOUNTS = 6

#: What a source can need from the account before it can search for it at all,
#: and the field that carries it. Reported per account so "found nothing" can
#: be told apart from "we had nothing to search with" — a brokerage with no
#: stored domain returns nothing for every source, and that is a fact about the
#: row rather than about the wording somebody is trying to tune.
ACCOUNT_INPUTS = {
    "name": "the company name",
    "domain": "its website",
    "linkedin_url": "its LinkedIn page",
    "industry": "its industry",
    "hq_country": "its country",
}


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
    #: Which variant produced this — "A" or "B". Always "A" when no B was given.
    variant: str = "A"
    #: Account fields that are empty, named in plain words. A source searching
    #: for a company with no stored website may legitimately find nothing, and
    #: without this the empty result reads as a verdict on the brief.
    missing: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class TrialReport:
    """Every account tried, plus the totals worth deciding on."""

    candidate: dict
    route: str
    trials: list[AccountTrial] = field(default_factory=list)
    #: The search logic, exactly as sent: the editable `company_research`
    #: template and the rendered payload. Shown rather than summarised, so the
    #: brief can be tuned against what actually runs — and so it can be pasted
    #: into a model elsewhere and argued with.
    prompt: str = ""
    payload: dict = field(default_factory=dict)
    #: Set when a B variant ran. The comparison is the point of an A/B: the same
    #: accounts, the same prompt, one field different.
    variant_b: str | None = None

    def side(self, variant: str) -> list[AccountTrial]:
        return [t for t in self.trials if t.variant == variant]

    @property
    def accounts(self) -> int:
        return len({t.account_id for t in self.trials})

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
        if self.variant_b is not None:
            a = sum(len(t.found) for t in self.side("A"))
            b = sum(len(t.found) for t in self.side("B"))
            if a == b:
                return (
                    f"A and B both found {a} across {self.accounts} accounts - "
                    "nothing to choose between them on this sample"
                )
            return f"B found {b}, A found {a}, across {self.accounts} accounts"
        if self.failed == len(self.trials):
            return f"FAILED at every account ({self.accounts}) - the route or the query is wrong"
        if not self.found:
            starved = sorted({m for t in self.trials for m in t.missing})
            if starved:
                return (
                    f"nothing at any of {self.accounts} accounts - but the sample is "
                    f"missing {', '.join(starved)}, so this may not be the wording"
                )
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
    description_b: str | None = None,
    client=None,
) -> TrialReport:
    """Run `candidate` against a few real accounts without storing anything.

    `candidate` is the source definition as it would be saved — `key`, `label`,
    `description`, `scopes`, `kind`. The description is the load-bearing part:
    it is what the research prompt reads as "what to read this source for", so
    a trial is mostly a test of that wording.

    `description_b` runs a second wording against **the same accounts in the
    same call**. That is what makes it an A/B rather than two trials: the
    prompt, the model, the account and the day are held still and one field
    moves, so a difference in what comes back is attributable to the wording.
    Comparing two separate runs minutes apart is not — the same request
    returned one sound answer on 411 tokens and nothing usable on 790, minutes
    apart (§74).
    """
    route = (candidate.get("kind") or "search").strip()
    if route not in TESTABLE:
        raise NotTestable(
            f"{route!r} cannot be trialled: it has no client to run. "
            f"Testable routes are {', '.join(TESTABLE)}. A source on an "
            "untestable route can still be stored, but nothing will have "
            "checked that it works."
        )

    # The ceiling is on calls. An A/B runs both wordings at every account, so
    # the row budget halves rather than the cost doubling.
    ceiling = MAX_ACCOUNTS // 2 if description_b else MAX_ACCOUNTS
    wanted = account_ids[:ceiling]
    accounts = list(
        (await session.execute(select(Account).where(Account.id.in_(wanted)))).scalars()
    )
    # Requested order, not database order: the caller picked these accounts to
    # look at in a particular order and the report is read top to bottom.
    by_id = {a.id: a for a in accounts}
    ordered = [by_id[i] for i in wanted if i in by_id]

    report = TrialReport(candidate=candidate, route=route, variant_b=description_b)
    variants = [("A", candidate)]
    if description_b:
        variants.append(("B", {**candidate, "description": description_b}))

    for account in ordered:
        for name, definition in variants:
            trial = await _one(session, account, definition, route, client)
            trial.variant = name
            report.trials.append(trial)

    # The logic itself, captured once from the first account. Built by the same
    # function the real call uses, so what is shown cannot drift from what runs.
    #
    # Guarded, because this is a display aid and the trial results above are the
    # answer. A failure here means somebody cannot read the prompt; letting it
    # propagate would mean they also lose the findings they just paid for.
    if ordered and route == "search":
        try:
            from app.services import stages

            prefix, payload = await stages.research_request(
                session, account=ordered[0], family=candidate.get("key") or "candidate",
                candidate=candidate,
            )
            report.prompt = _text_of(prefix)
            report.payload = payload
        except Exception as exc:  # noqa: BLE001 — never fail a trial over this
            log.warning(
                "source_trial.capture_failed key=%s %s: %s",
                candidate.get("key"), type(exc).__name__, exc,
            )

    log.info(
        "source_trial.done key=%s route=%s accounts=%d variants=%d found=%d dry=%d "
        "failed=%d in=%d out=%d",
        candidate.get("key"), route, report.accounts, len(variants), report.found,
        report.dry, report.failed, report.input_tokens, report.output_tokens,
    )
    return report


def _text_of(prefix) -> str:
    """The prompt as text, whatever shape `load_prefix` returned.

    It carries a system body and may carry tool declarations; only the body is
    worth showing, and a caller tuning a brief should not have to care which
    container it arrived in.
    """
    if isinstance(prefix, str):
        return prefix
    for attr in ("system", "body", "text"):
        value = getattr(prefix, attr, None)
        if isinstance(value, str):
            return value
    if isinstance(prefix, dict):
        for attr in ("system", "body", "text"):
            if isinstance(prefix.get(attr), str):
                return prefix[attr]
    return str(prefix)


async def _one(
    session: AsyncSession, account: Account, candidate: dict, route: str, client
) -> AccountTrial:
    from app.services import site_sweep, stages

    trial = AccountTrial(
        account_id=account.id,
        account_name=account.name or "",
        missing=[
            words for attr, words in ACCOUNT_INPUTS.items()
            if not str(getattr(account, attr, "") or "").strip()
        ],
    )
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
