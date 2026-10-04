"""Tier 0 — turning a CSV row into a company we are sure about.

A spreadsheet cell saying "Acme" is a claim about who to look at, not an
identity. Researching the wrong Acme fails **silently**: the evidence, the
signals, the score and the draft all come out well-formed and about a different
business, and nothing on screen says so. By the time anybody notices, tokens
and credits have been spent and a rep has read a briefing that was fiction.

So this runs first, it is the cheapest step in the pipeline, and the expensive
stages refuse an account that has not passed it.

Three rules the rest of the system depends on:

**A near-miss is not a match.** When two companies are plausible the honest
answer is `needs_review` with both recorded, not the more likely one written in
as fact. Forcing a guess here is precisely what produces confident research
about the wrong company, and a rep glancing at a list spots it in seconds.

**The waterfall stops at the first real answer.** Apollo's domain lookup is the
cheapest call in the system and returns firmographics as a by-product; the LLM
fallback exists for rows with no domain at all. Asking both and merging would
spend a model call on every row Apollo already resolved.

**Nothing is overwritten.** A domain the rep corrected by hand outranks anything
a provider returns later — `resolve_account` fills gaps and records
disagreement in `resolution_note`, it does not silently replace a human's work.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountListMember
from app.models.config import EnrichmentConfig
from app.services.versioning import get_active

log = logging.getLogger(__name__)

#: Below this, an answer is offered for review rather than accepted. Chosen so
#: an exact domain match (1.0) passes and a name-only guess does not — the
#: whole point is that unsupported confidence never becomes a stored fact.
ACCEPT_ABOVE = 0.75


@dataclass(frozen=True)
class Candidate:
    """One company a source thinks this row might be."""

    name: str | None = None
    domain: str | None = None
    linkedin_url: str | None = None
    industry: str | None = None
    employee_count: int | None = None
    #: 0–1. A source that matched on an exact domain should say 1.0; one that
    #: matched a common name should not.
    confidence: float = 0.0
    #: Why this was proposed, shown to the rep who has to judge it.
    rationale: str | None = None
    #: Which source proposed it. Set by the waterfall, not by the resolver, so
    #: a source cannot mis-attribute its own answer. `resolved_by` was picking
    #: the first source *called* rather than the one that answered, which made
    #: it report Apollo for answers Apollo had explicitly declined.
    source: str | None = None

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "source": self.source,
            "domain": self.domain,
            "linkedin_url": self.linkedin_url,
            "industry": self.industry,
            "employee_count": self.employee_count,
            "confidence": round(float(self.confidence), 3),
            "rationale": self.rationale,
        }


@dataclass
class ResolutionResult:
    """What one source concluded."""

    best: Candidate | None = None
    others: list[Candidate] = field(default_factory=list)
    #: Set when the source could not be reached. Distinct from "no match" —
    #: the first needs a retry, the second needs a different identifier.
    unavailable: str | None = None
    #: Something learned that is not a candidate — "this domain does not
    #: exist". Carried into the note so a rep sees why nothing was confirmed.
    finding: str | None = None


@runtime_checkable
class Resolver(Protocol):
    key: str

    async def resolve(self, account: Account) -> ResolutionResult:
        """Identify this company, or say honestly that you could not."""
        ...


class ResolverError(RuntimeError):
    """The source could not be reached, or refused the request."""


# --------------------------------------------------------------------------
# normalising, so two spellings of one company do not read as two companies
# --------------------------------------------------------------------------

_SCHEME = re.compile(r"^\s*https?://", re.I)
_WWW = re.compile(r"^www\.", re.I)


def normalise_domain(raw: str | None) -> str | None:
    """`https://WWW.Acme.com/about?x=1` → `acme.com`.

    Done here rather than at each call site because the partial unique index on
    `lower(domain)` is what stops a re-import duplicating an account, and it
    only works if every writer agrees on the form.
    """
    if not raw or not raw.strip():
        return None
    value = _SCHEME.sub("", raw.strip())
    value = value.split("/")[0].split("?")[0].split("#")[0]
    value = _WWW.sub("", value).strip().lower().rstrip(".")
    # A bare word is a name, not a domain. Accepting it would let "Acme" be
    # stored as a domain and then fail every lookup that uses one.
    return value if "." in value and " " not in value else None


def normalise_linkedin(raw: str | None) -> str | None:
    """Company pages only, trailing slash and query stripped.

    A `/in/` URL is a *person*. Storing one as the company page is how a rep
    ends up looking at a stranger's profile when they click through from an
    account, and `csv_import.classify_linkedin` exists for the same reason.
    """
    if not raw or not raw.strip():
        return None
    value = raw.strip().split("?")[0].split("#")[0].rstrip("/")
    if "/company/" not in value.lower():
        return None
    # Strip the scheme and `www.` unconditionally, then put one scheme back.
    # Doing it only when a scheme was absent produced two stored forms of the
    # same page, which is exactly what normalising is for.
    value = _WWW.sub("", _SCHEME.sub("", value))
    return f"https://{value}"


# --------------------------------------------------------------------------
# the waterfall
# --------------------------------------------------------------------------


@dataclass
class AccountOutcome:
    account_id: uuid.UUID
    name: str
    #: `resolved`, `needs_review`, `unresolved`, `skipped`, or `unavailable`.
    outcome: str
    detail: str = ""
    sources_called: list[str] = field(default_factory=list)


@dataclass
class ResolutionReport:
    checked: int = 0
    resolved: int = 0
    needs_review: int = 0
    unresolved: int = 0
    skipped: int = 0
    unavailable: int = 0
    outcomes: list[AccountOutcome] = field(default_factory=list)
    order: list[str] = field(default_factory=list)
    #: Set when no source could be called at all. The pass did nothing and says
    #: so, rather than reporting that it resolved nobody.
    blocked: str | None = None

    @property
    def ran(self) -> bool:
        return self.blocked is None


async def resolution_order(session: AsyncSession) -> list[str]:
    row = await get_active(session, EnrichmentConfig)
    return list(getattr(row, "resolution_order", None) or []) if row else []


async def unresolved_accounts(
    session: AsyncSession,
    *,
    list_id: uuid.UUID,
    include_reviewed: bool = False,
    account_ids: list[uuid.UUID] | None = None,
) -> list[Account]:
    """Accounts on this list that nobody has confirmed yet.

    `resolved` and `rejected` are both settled — one confirmed, one dismissed —
    and re-running over them would spend a call to reach the same answer, or
    worse, overturn a rep's decision.
    """
    settled = ["resolved", "rejected"]
    if not include_reviewed:
        settled.append("needs_review")
    rows = await session.execute(
        select(Account)
        .join(AccountListMember, AccountListMember.account_id == Account.id)
        .where(
            AccountListMember.list_id == list_id,
            Account.resolution_status.not_in(settled),
            # A selection from the table narrows it; still scoped to the list,
            # so an id from elsewhere matches nothing.
            *([Account.id.in_(account_ids)] if account_ids else []),
        )
        .order_by(Account.name)
    )
    return list(rows.scalars())


def _apply(account: Account, best: Candidate, source: str) -> list[str]:
    """Write what is missing. Never overwrite what is already there.

    Returns notes about anything the source disagreed with. A rep who typed a
    domain by hand has made a judgement, and a later provider call is not
    grounds to overturn it silently — but the disagreement is worth recording,
    because one of the two is wrong.
    """
    notes: list[str] = []

    domain = normalise_domain(best.domain)
    if domain:
        current = normalise_domain(account.domain)
        if not current:
            account.domain = domain
        elif current != domain:
            notes.append(f"{source} says {domain}, list says {current}")

    linkedin = normalise_linkedin(best.linkedin_url)
    if linkedin and not account.linkedin_url:
        account.linkedin_url = linkedin

    # Firmographics are the by-product that makes this step pay for itself:
    # `industry_key` feeds the scoring multipliers and `employee_count` derives
    # the size band, and today both come from the CSV or not at all.
    if best.industry and not account.industry:
        account.industry = best.industry
        if hasattr(account, "industry_key"):
            account.industry_key = _industry_key(best.industry)
    if best.employee_count and not account.employee_count:
        account.employee_count = int(best.employee_count)

    return notes


def _industry_key(value: str) -> str:
    return " ".join(value.casefold().split())


async def resolve_account(
    session: AsyncSession, *, account: Account, resolvers: list[Resolver]
) -> AccountOutcome:
    """One account, through the waterfall, written back with its provenance."""
    called: list[str] = []
    errors: list[str] = []
    findings: list[str] = []
    everything: list[Candidate] = []

    for resolver in resolvers:
        called.append(resolver.key)
        try:
            found = await resolver.resolve(account)
        except ResolverError as exc:
            errors.append(f"{resolver.key}: {exc}")
            log.warning(
                "resolution.source_failed source=%s account=%s err=%s",
                resolver.key, account.id, exc,
            )
            continue

        if found.unavailable:
            errors.append(f"{resolver.key}: {found.unavailable}")
            continue
        if found.finding:
            findings.append(found.finding)

        # Stamped here rather than trusted from the resolver: attribution is
        # what makes a wrong domain traceable weeks later.
        from dataclasses import replace as _replace

        everything.extend(
            _replace(c, source=resolver.key)
            for c in (found.best, *found.others)
            if c
        )
        if found.best and found.best.confidence >= ACCEPT_ABOVE:
            # Confident enough to stop. Asking the next source would spend a
            # call to confirm what this one already established.
            break

    if not everything:
        if errors and len(errors) == len(called):
            # Every source we asked failed. The account is untouched and stays
            # unresolved, which is what makes a retry correct rather than a
            # second charge.
            account.resolution_note = "; ".join(errors)
            return AccountOutcome(
                account.id, account.name, "unavailable", "; ".join(errors), called
            )
        # Say what was learned. "No source could identify this company" over a
        # domain with no DNS record hid the one fact a rep needed.
        note = "; ".join(findings) or "no source could identify this company"
        account.resolution_status = "unresolved"
        account.resolution_note = note
        return AccountOutcome(account.id, account.name, "unresolved", note, called)

    everything.sort(key=lambda c: c.confidence, reverse=True)
    best = everything[0]
    runners_up = [c for c in everything[1:] if c.confidence > 0]

    account.resolution_confidence = round(float(best.confidence), 3)
    account.resolved_by = best.source or (called[-1] if called else None)
    account.resolved_at = datetime.now(UTC)
    account.resolution_candidates = [c.as_dict() for c in everything[:5]] or None

    notes = _apply(account, best, account.resolved_by or "a source")

    # A close second is itself a reason to look. Two companies within 0.15 of
    # each other means the winner won on very little, and accepting it is how
    # the wrong Acme gets researched with full confidence.
    close = runners_up and (best.confidence - runners_up[0].confidence) < 0.15

    # An answer that names no identifier has not identified anything. A live
    # run produced exactly this: a company confidently matched at 0.90 with no
    # domain, marked `resolved`, and therefore cleared to be researched — with
    # nothing for Apollo to look up or a search to anchor on. Confidence is
    # about *which* company; this is about whether we can act on it.
    identified = bool(
        normalise_domain(best.domain)
        or normalise_linkedin(best.linkedin_url)
        or normalise_domain(account.domain)
        or normalise_linkedin(account.linkedin_url)
    )

    if best.confidence >= ACCEPT_ABOVE and not close and not notes and identified:
        account.resolution_status = "resolved"
        account.resolution_note = None
        return AccountOutcome(
            account.id, account.name, "resolved",
            f"{best.domain or best.name} ({best.confidence:.2f})", called,
        )

    reasons = [*findings, *notes]
    if best.confidence < ACCEPT_ABOVE:
        reasons.append(f"best match only {best.confidence:.2f} confident")
    if close:
        reasons.append(
            f"a second candidate scored {runners_up[0].confidence:.2f} — too close to call"
        )
    if not identified:
        reasons.append(
            "no domain or LinkedIn page was found, so there is nothing to "
            "research or look up"
        )
    account.resolution_status = "needs_review"
    account.resolution_note = "; ".join(reasons)
    return AccountOutcome(
        account.id, account.name, "needs_review", account.resolution_note, called
    )


async def resolve_list(
    session: AsyncSession,
    *,
    list_id: uuid.UUID,
    resolvers: dict[str, Resolver] | None = None,
    limit: int | None = None,
    account_ids: list[uuid.UUID] | None = None,
    include_reviewed: bool = False,
) -> ResolutionReport:
    """Run every unresolved account on a list through the waterfall.

    `resolvers` is injected so this is testable without a network and without a
    contract. When omitted they are built from configuration.
    """
    from app.services import resolution_clients

    report = ResolutionReport()
    order = await resolution_order(session)
    available = (
        resolvers
        if resolvers is not None
        else await resolution_clients.build_all(session, order)
    )
    runnable = [k for k in order if k in available]
    report.order = runnable

    if not runnable:
        missing = [k for k in order if k not in available]
        report.blocked = (
            "No resolution source could be called. "
            + (f"Not available: {', '.join(missing)}." if missing
               else "None is configured.")
        )
        log.warning("resolution.blocked list=%s reason=%s", list_id, report.blocked)
        return report

    chain = [available[k] for k in runnable]
    accounts = await unresolved_accounts(
        session, list_id=list_id, account_ids=account_ids, include_reviewed=include_reviewed
    )
    if limit is not None:
        accounts = accounts[:limit]

    for account in accounts:
        report.checked += 1
        outcome = await resolve_account(session, account=account, resolvers=chain)
        report.outcomes.append(outcome)
        setattr(report, outcome.outcome, getattr(report, outcome.outcome, 0) + 1)

    await session.flush()
    log.info(
        "resolution.done list=%s checked=%d resolved=%d review=%d unresolved=%d",
        list_id, report.checked, report.resolved,
        report.needs_review, report.unresolved,
    )
    return report
