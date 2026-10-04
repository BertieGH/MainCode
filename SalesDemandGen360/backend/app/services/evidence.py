"""Writing what research found, once.

The dedup key is the **excerpt**, not the document — see the constraint comment
on `evidence`. One page yields many passages, and deduping on the page would
admit only the first; signals citing the rejected ones would then be dropped by
the missing-evidence guard, looking exactly like hallucinated citations. That
failure is indistinguishable from the one the guard exists to catch, which is
why the key is where it is.

Duplicates are expected, not exceptional. Two research families searching a
company's newsroom and its press coverage will find the same sentence, and the
right behaviour is to keep the row that is already there — it may already be
cited by a signal, and replacing it would break that citation.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import durability, linkedin
from app.models.signal import Evidence
from app.schemas.evidence import EvidenceBatch, FoundEvidence

log = logging.getLogger(__name__)


def excerpt_hash(source_url: str | None, excerpt: str) -> str:
    """The dedup key: this passage, from this place.

    Normalised before hashing, because the same sentence retrieved twice comes
    back subtly different often enough that hashing the raw text lets most
    duplicates through — and each one is a row a rep has to read past.

    Whitespace was normalised from the start. Case and trailing punctuation
    were not, and a live run showed what that costs: one line, from one page,
    stored twice, a single full stop apart.

        [web]      growjo.com/…  "Christian DeKnock. Design & Communications Manager"
        [provider] growjo.com/…  "Christian DeKnock. Design & Communications Manager."

    Only *trailing* punctuation goes. Stripping it everywhere would make
    "we raised $4M." and "we raised $4M?" into one passage, and the difference
    between a claim and a question is the whole content of some excerpts.
    """
    normalised = " ".join(excerpt.split()).casefold().rstrip(".,;:!·—- ")
    return hashlib.sha256(
        f"{(source_url or '').strip().casefold()}\n{normalised}".encode()
    ).hexdigest()


def source_hash(source_url: str | None, title: str | None) -> str:
    """Which document this came from. Deliberately not unique."""
    return hashlib.sha256(
        f"{(source_url or '').strip()}\n{(title or '').strip()}".encode()
    ).hexdigest()


@dataclass
class StoreOutcome:
    stored: list[Evidence] = field(default_factory=list)
    #: Passages already held for this account. Counted rather than discarded:
    #: a family that returns nothing but duplicates has covered no new ground,
    #: which coverage should reflect.
    duplicates: int = 0
    #: Passages dated before any active signal type could use them. Counted
    #: separately from duplicates because they mean something different about
    #: the family: duplicates say the ground was already covered, stale says
    #: the search went somewhere there was nothing current to find.
    stale: int = 0

    @property
    def count(self) -> int:
        return len(self.stored)


async def store_found(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    batch: EvidenceBatch,
    run_id: uuid.UUID | None = None,
    source_type_override: str | None = None,
    family: str | None = None,
    contact_id: uuid.UUID | None = None,
) -> StoreOutcome:
    """Persist a research batch, skipping passages already held.

    Existing hashes are read once up front rather than probed per row. A family
    can return thirty passages, and thirty round-trips to answer a question one
    query answers is the kind of cost that only shows up under a real book.
    """
    outcome = StoreOutcome()
    if not batch.evidence:
        return outcome

    existing = set(
        (
            await session.execute(
                select(Evidence.excerpt_hash).where(Evidence.account_id == account_id)
            )
        ).scalars()
    )
    # The research prompt is told the same cutoff, but a prompt is a request and
    # this is the rule. Half the evidence held when this was written carried no
    # date at all, so the test is deliberately one-sided: a date older than the
    # cutoff is refused, and no date is admitted. Treating undated as stale
    # would throw away every provider and job-board passage, none of which
    # carries one.
    cutoff = await durability.research_cutoff(session)

    for found in batch.evidence:
        observed = found.observed_at or linkedin.post_date(found.source_url)
        if observed is not None and observed < cutoff:
            outcome.stale += 1
            continue

        key = excerpt_hash(found.source_url, found.excerpt)
        if key in existing:
            outcome.duplicates += 1
            continue
        # Guards against a batch that repeats a passage inside itself, which
        # the database would otherwise reject at flush and take the whole
        # family's evidence down with it.
        existing.add(key)

        row = _to_row(
            found,
            account_id=account_id,
            run_id=run_id,
            key=key,
            # Passed in rather than recomputed, so the date the gate tested is
            # the date that gets stored. Deriving it twice would let a row be
            # kept on one reading of its date and filed under another.
            observed_at=observed,
            source_type_override=source_type_override,
            family=family,
            contact_id=contact_id,
        )
        session.add(row)
        outcome.stored.append(row)

    await session.flush()
    log.info(
        "evidence.stored account=%s stored=%d duplicate=%d stale=%d not_found=%d",
        account_id, outcome.count, outcome.duplicates, outcome.stale,
        len(batch.not_found),
    )
    return outcome


def _to_row(
    found: FoundEvidence,
    *,
    account_id: uuid.UUID,
    run_id: uuid.UUID | None,
    key: str,
    observed_at: date | None,
    source_type_override: str | None,
    family: str | None = None,
    contact_id: uuid.UUID | None = None,
) -> Evidence:
    return Evidence(
        account_id=account_id,
        run_id=run_id,
        family=family,
        contact_id=contact_id,
        source_type=source_type_override or found.source_type,
        source_url=found.source_url,
        source_name=found.source_name,
        title=found.title,
        excerpt=found.excerpt,
        # A LinkedIn post's date is written into its URL; a search snippet of
        # the post carries none of its own. See `services/linkedin.py`. Derived
        # by the caller, which needs the same answer to apply the staleness
        # gate.
        observed_at=observed_at,
        source_hash=source_hash(found.source_url, found.title),
        excerpt_hash=key,
        # Nothing is snapshotted to object storage yet, and `stored` without a
        # `raw_ref` violates the table's own check. `unavailable` is the honest
        # state: the page was read, but we cannot reproduce it from our side.
        raw_status="unavailable",
        reliability=found.reliability,
    )
