"""The evidence-resolution guard — the service half of "no signal without evidence".

The database enforces that a signal has *some* evidence row (deferred constraint
trigger). It cannot enforce that the evidence the model *named* is the evidence
that exists, because by the time a foreign key would fire, a hallucinated id has
already been discarded or, worse, silently matched something real.

So this module resolves every id the model returned, against the evidence
belonging to **this account**, and drops any signal citing an id it cannot find.
It fails closed. A hallucinated citation is the single failure mode that would
destroy rep trust: a rep who opens one citation and finds it fabricated stops
believing all of them, including the true ones.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.config import SignalType
from app.models.governance import Evaluation
from app.services.durability import durability_of
from app.models.signal import Evidence, Signal, signal_evidence
from app.schemas.signal import (
    DroppedSignal,
    ExtractedSignal,
    ExtractionOutcome,
    SignalBatch,
)

log = logging.getLogger(__name__)


def _as_uuids(raw: list[str]) -> tuple[list[uuid.UUID], list[str]]:
    """Split ids into parseable UUIDs and unusable strings.

    A malformed id is treated exactly like a missing one. Letting it raise
    would abort the whole batch, so one bad citation would discard every good
    signal alongside it.
    """
    good: list[uuid.UUID] = []
    bad: list[str] = []
    for value in raw:
        try:
            good.append(uuid.UUID(str(value)))
        except (ValueError, AttributeError, TypeError):
            bad.append(str(value))
    return good, bad


async def _live_types(session: AsyncSession) -> dict[str, SignalType]:
    """Active registry rows, keyed by key.

    Paused and deprecated types are absent on purpose: pausing a type is meant
    to stop it being extracted, and a signal written against a paused type
    would not appear in `signal_current` anyway — it would exist, count for
    nothing, and be invisible.
    """
    rows = await session.execute(select(SignalType).where(SignalType.status == "active"))
    return {row.key: row for row in rows.scalars()}


async def store_batch(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    batch: SignalBatch,
    run_id: uuid.UUID | None = None,
) -> ExtractionOutcome:
    """Persist the signals whose citations all resolve; drop and log the rest.

    Every signal is written with its join rows inside one transaction, so the
    deferred trigger sees a complete picture at COMMIT.
    """
    outcome = ExtractionOutcome()
    if not batch.signals:
        return outcome

    types = await _live_types(session)

    # One query for the whole batch rather than one per signal. Scoped to the
    # account: evidence belonging to another account must not resolve, or a
    # citation would leak one prospect's documents into another's audit trail.
    cited: list[uuid.UUID] = []
    for sig in batch.signals:
        parsed, _ = _as_uuids(sig.evidence_ids)
        cited.extend(parsed)

    known: set[uuid.UUID] = set()
    #: Which page each cited passage came from — what lets two passages quoted
    #: differently from one press release be recognised as one source.
    page_by_id: dict[uuid.UUID, str | None] = {}
    if cited:
        rows = await session.execute(
            select(Evidence.id, Evidence.source_url).where(
                Evidence.account_id == account_id, Evidence.id.in_(set(cited))
            )
        )
        page_by_id = {evidence_id: page_of(url) for evidence_id, url in rows.all()}
        known = set(page_by_id)

    held = await _existing_facts(session, account_id)
    themes = await _current_themes(session, account_id, types)

    for sig in batch.signals:
        parsed_ids, _ = _as_uuids(sig.evidence_ids)
        registry = types.get(sig.signal_type)
        theme_key = (sig.signal_type, sig.contact_id)
        current = (
            themes.get(theme_key)
            if registry is not None and getattr(registry, "kind", None) == "theme"
            else None
        )
        if current is not None and sig.observed_at <= current.observed_at:
            # An ongoing theme already live, re-read at a date no newer than the
            # one held. BlueWave's blog publishing on AI every few weeks is one
            # theme — not a signal per post the model happened to date it by.
            outcome.duplicates += 1
            continue
        if _already_held(sig, parsed_ids, held, page_by_id):
            # The same fact, re-read. Evidence is re-interpreted on every run —
            # a rerun, a new family, a wider window — and without this the same
            # funding round accumulates a row per run, each one expiring on the
            # same day and each one counted as a separate conclusion.
            outcome.duplicates += 1
            continue
        problem = _reject_reason(sig, types, known, account_id)
        if problem is not None:
            reason, unknown = problem
            outcome.dropped.append(
                DroppedSignal(
                    signal_type=sig.signal_type,
                    summary=sig.summary,
                    reason=reason,
                    unknown_evidence_ids=unknown,
                )
            )
            log.warning(
                "extraction.signal_dropped account=%s type=%s reason=%s unknown=%s",
                account_id, sig.signal_type, reason, unknown,
            )
            continue

        registry = types[sig.signal_type]
        parsed, _ = _as_uuids(sig.evidence_ids)

        row = Signal(
            account_id=account_id,
            contact_id=sig.contact_id,
            run_id=run_id,
            signal_type=sig.signal_type,
            scope=registry.scope,
            summary=sig.summary,
            business_implication=sig.business_implication,
            strength=sig.strength,
            confidence=sig.confidence,
            observed_at=sig.observed_at,
            expires_at=expiry_for(sig.observed_at, registry.default_ttl_days),
            is_hypothesis=sig.is_hypothesis,
        )
        session.add(row)
        await session.flush()  # assigns row.id without committing

        # Deduplicated: the model naming the same excerpt twice is a repetition,
        # not two citations, and the composite PK would reject the second.
        for i, evidence_id in enumerate(dict.fromkeys(parsed)):
            await session.execute(
                signal_evidence.insert().values(
                    signal_id=row.id,
                    evidence_id=evidence_id,
                    role="primary" if i == 0 else "supporting",
                )
            )
        outcome.stored += 1
        # Held from now on, so a second reading of the same fact later in this
        # same batch is caught too, not only readings from earlier runs.
        held.setdefault(_fact_key(sig), []).append(
            HeldFact(
                evidence_ids=set(parsed),
                pages={p for i in parsed if (p := page_by_id.get(i))},
                words=words_of(sig.summary),
            )
        )
        if getattr(registry, "kind", None) == "theme":
            if current is not None:
                # The theme moved forward. Every older live reading stops
                # counting and says which reading replaced it — kept, never
                # deleted, since a strategy or a draft may cite one.
                await session.execute(
                    update(Signal)
                    .where(Signal.id.in_(current.signal_ids))
                    .values(superseded_by=row.id)
                )
            themes[theme_key] = LiveTheme(observed_at=sig.observed_at, signal_ids=[row.id])

    if outcome.duplicates:
        log.info(
            "extraction.duplicates account=%s stored=%d duplicate=%d",
            account_id, outcome.stored, outcome.duplicates,
        )
    if outcome.dropped:
        log.warning(
            "extraction.batch account=%s stored=%d dropped=%d rate=%.2f",
            account_id, outcome.stored, len(outcome.dropped), outcome.drop_rate,
        )
        if run_id is not None:
            # Recorded, not only logged. A rising drop rate is the earliest
            # sign that an extraction prompt has drifted, and a log line nobody
            # reads is indistinguishable from a clean run.
            session.add(
                Evaluation(
                    subject_type="research",
                    subject_id=run_id,
                    method="rules",
                    verdict="fail" if not outcome.stored else "warn",
                    scores={
                        "stored": outcome.stored,
                        "dropped": len(outcome.dropped),
                        "drop_rate": round(outcome.drop_rate, 3),
                    },
                    issues=[d.model_dump() for d in outcome.dropped],
                    evaluator_version="extraction-guard-1",
                )
            )
            await session.flush()
    return outcome


#: How alike two summaries must be — word overlap, 0 to 1 — for readings of
#: one page on one date to count as one fact.
#:
#: Set from the pairs that forced this, on BlueWave. The same fact worded
#: twice: "announced / secured an initial capital raise of $75 million led by
#: Columbia Capital" is 0.73, and the CBTS award quoted with and without "its"
#: is 0.93. Two facts from one release: "appointed Drew Cather as Chief Revenue
#: Officer" against "acquired CloudZen Partners and appointed multiple key
#: executives" is 0.25. 0.6 sits clear of both sides. A different wording of the
#: same fact that falls below it is stored twice — the cheaper mistake, since
#: collapsing two facts into one loses one of them.
SAME_FACT_SIMILARITY = 0.6


def page_of(url: str | None) -> str | None:
    """A page, for deciding whether two passages share one.

    Case of the scheme and host, a trailing slash and a fragment are spelling,
    not a different page. The query string is kept: on many sites it *is* the
    page.
    """
    if not url or not url.strip():
        return None
    parts = urlsplit(url.strip())
    return urlunsplit(
        (parts.scheme.casefold(), parts.netloc.casefold(), parts.path.rstrip("/"), parts.query, "")
    )


def words_of(text: str | None) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9$]+", (text or "").casefold()))


def similarity(a: frozenset[str], b: frozenset[str]) -> float:
    """Word overlap: shared words over all words. No stopword list, on purpose
    — dropping "a" and "as" made two different appointments look identical."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class HeldFact:
    """One signal an account already has, as dedupe sees it."""

    evidence_ids: set[uuid.UUID]
    pages: set[str]
    words: frozenset[str]


def same_fact(
    held: HeldFact,
    *,
    evidence_ids: set[uuid.UUID],
    pages: set[str],
    words: frozenset[str],
) -> bool:
    """Whether a new reading is a fact already held. Type, date and person
    are already equal by the time this is asked — see `_fact_key`.

    Either of two things makes it the same:

    * **A shared passage.** A second reading of one quote is the same fact
      however it is worded.
    * **The same page, said the same way.** A page quoted twice is stored as
      two passages, so a rerun's new quote shares no passage with the old one:
      that is how the CBTS award was written twice. The summary has to agree as
      well, because one release can carry two facts of one type on one day —
      an acquisition and an appointment — and those must stay two.
    """
    if held.evidence_ids & evidence_ids:
        return True
    return bool(held.pages & pages) and similarity(held.words, words) >= SAME_FACT_SIMILARITY


def _fact_key(sig) -> tuple[str, date, uuid.UUID | None]:
    """Type, date, and who it is about.

    The person is part of it: one article naming two new vice presidents is two
    role changes, and without the contact in the key the shared citation would
    have made the second a "duplicate" of the first.
    """
    return (sig.signal_type, sig.observed_at, sig.contact_id)


@dataclass
class LiveTheme:
    """An ongoing theme's live readings at one account: the newest date, and
    every reading not yet superseded — more than one only for copies written
    before the type became a theme."""

    observed_at: date
    signal_ids: list[uuid.UUID]


async def _current_themes(
    session: AsyncSession, account_id: uuid.UUID, types: dict[str, SignalType]
) -> dict[tuple[str, uuid.UUID | None], LiveTheme]:
    """The live readings of each theme-kind type, by type and person."""
    keys = [key for key, t in types.items() if getattr(t, "kind", None) == "theme"]
    if not keys:
        return {}
    rows = await session.execute(
        select(Signal.id, Signal.signal_type, Signal.contact_id, Signal.observed_at)
        .where(
            Signal.account_id == account_id,
            Signal.signal_type.in_(keys),
            Signal.superseded_by.is_(None),
        )
        .order_by(Signal.observed_at.desc(), Signal.created_at.desc())
    )
    out: dict[tuple[str, uuid.UUID | None], LiveTheme] = {}
    for signal_id, signal_type, contact_id, observed_at in rows.all():
        live = out.setdefault((signal_type, contact_id), LiveTheme(observed_at, []))
        live.signal_ids.append(signal_id)
    return out


async def _existing_facts(
    session: AsyncSession, account_id: uuid.UUID
) -> dict[tuple[str, date, uuid.UUID | None], list[HeldFact]]:
    """What this account already says, by fact key, with citations and pages."""
    signals = list(
        (
            await session.execute(
                select(
                    Signal.id, Signal.signal_type, Signal.observed_at, Signal.contact_id,
                    Signal.summary,
                ).where(Signal.account_id == account_id)
            )
        ).all()
    )
    if not signals:
        return {}
    cited = await session.execute(
        select(signal_evidence.c.signal_id, Evidence.id, Evidence.source_url)
        .join(Evidence, Evidence.id == signal_evidence.c.evidence_id)
        .where(signal_evidence.c.signal_id.in_([s.id for s in signals]))
    )
    ids: dict[uuid.UUID, set[uuid.UUID]] = {}
    pages: dict[uuid.UUID, set[str]] = {}
    for signal_id, evidence_id, url in cited.all():
        ids.setdefault(signal_id, set()).add(evidence_id)
        if (page := page_of(url)) is not None:
            pages.setdefault(signal_id, set()).add(page)

    held: dict[tuple[str, date, uuid.UUID | None], list[HeldFact]] = {}
    for s in signals:
        held.setdefault(_fact_key(s), []).append(
            HeldFact(
                evidence_ids=ids.get(s.id, set()),
                pages=pages.get(s.id, set()),
                words=words_of(s.summary),
            )
        )
    return held


def _already_held(
    sig: ExtractedSignal,
    parsed_ids: list[uuid.UUID],
    held: dict[tuple[str, date, uuid.UUID | None], list[HeldFact]],
    page_by_id: dict[uuid.UUID, str | None],
) -> bool:
    """Is this reading a fact the account already holds?

    Pages come only from evidence resolved against this account, so a
    hallucinated id contributes no page and cannot make something a duplicate.
    """
    facts = held.get(_fact_key(sig))
    if not facts:
        return False
    evidence_ids = set(parsed_ids)
    pages = {p for i in parsed_ids if (p := page_by_id.get(i))}
    words = words_of(sig.summary)
    return any(
        same_fact(f, evidence_ids=evidence_ids, pages=pages, words=words) for f in facts
    )


def expiry_for(observed_at: date, ttl_days: int) -> date:
    """Ageing is arithmetic, not judgement — which is why re-scoring is free."""
    return observed_at + timedelta(days=ttl_days)


def _reject_reason(
    sig: ExtractedSignal,
    types: dict[str, SignalType],
    known: set[uuid.UUID],
    account_id: uuid.UUID,
) -> tuple[str, list[str]] | None:
    """Why this signal cannot be stored, or None if it can.

    Checked here rather than left to the database because a constraint
    violation aborts the transaction and takes the whole batch with it. One bad
    signal must cost one signal.
    """
    registry = types.get(sig.signal_type)
    if registry is None:
        return ("unknown or inactive signal type", [])

    parsed, malformed = _as_uuids(sig.evidence_ids)
    missing = [str(i) for i in parsed if i not in known]
    if malformed or missing:
        return ("cited evidence that does not exist", malformed + missing)
    if not parsed:
        return ("no usable evidence ids", [])

    # The composite FK would catch this too, but only at flush — by which point
    # the batch is already poisoned.
    if registry.scope == "contact" and sig.contact_id is None:
        return ("contact-scoped type without a contact_id", [])
    if registry.scope == "company" and sig.contact_id is not None:
        return ("company-scoped type carrying a contact_id", [])

    # The exact per-type cut. Evidence intake applies the widest window across
    # all active types, because one document is read against all of them; here
    # the type is known, so the right window is its own. This is what separates
    # a `mgt_change` dated 638 days ago (refused — durability 540) from a
    # `tech_adoption` dated 582 days ago (kept — durability 1095).
    #
    # Without it, `expiry_for` would hand back a date already in the past and
    # the signal would be stored expired: invisible to every prompt, visible on
    # the screen, and paid for. Five of the first eight signals held were this.
    window = durability_of(registry)
    if sig.observed_at < date.today() - timedelta(days=window):
        return (f"dated beyond this type's {window}-day durability", [])

    return None
