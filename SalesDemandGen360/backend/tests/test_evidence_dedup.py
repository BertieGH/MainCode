"""Evidence deduplication.

The key is the excerpt, not the document, and that choice has a specific
failure behind it. Deduping on the document admits only the first passage from
a page; a signal citing one of the rejected passages is then dropped by the
missing-evidence guard, and the drop looks *exactly* like a hallucinated
citation. Someone diagnosing that misreads it as model drift and loosens the
guard — which is the one thing holding the citation chain up.

So these tests assert the discriminating cases: two passages from one page are
two rows, and the same passage twice is one.
"""

from __future__ import annotations

import uuid

import pytest

from app.schemas.evidence import EvidenceBatch, FoundEvidence
from app.services.evidence import excerpt_hash, source_hash, store_found
from tests.conftest import LongLivedSignalType, is_signal_type_query


class _Scalars:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return self

    def __iter__(self):
        return iter(self._rows)


class FakeSession:
    """Holds the hashes already stored for the account, and collects adds.

    Answers by *what is being asked*, not with one canned list. `store_found`
    now runs two queries — the account's excerpt hashes, and the active signal
    types it derives the staleness cutoff from — and a fake that replies to
    both with the hashes handed `durability_of` a string. The failure was
    oblique (an `IndexError` on `outcome.stored[0]`) and nothing about it
    pointed at the fake, which is reason enough to make the fake discriminate.
    """

    def __init__(
        self, existing: list[str] | None = None, types: list | None = None
    ):
        self.existing = existing or []
        self.types = types if types is not None else [LongLivedSignalType()]
        self.added: list = []
        self.flushes = 0

    async def execute(self, stmt):
        if is_signal_type_query(stmt):
            return _Scalars(self.types)
        return _Scalars(self.existing)

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        self.flushes += 1


def _found(url: str, excerpt: str, **over) -> FoundEvidence:
    return FoundEvidence(
        source_type=over.pop("source_type", "news"),
        source_url=url,
        excerpt=excerpt,
        **over,
    )


class TestTheKeyIsTheExcerpt:
    async def test_two_passages_from_one_page_are_two_rows(self):
        """The case that breaks a document-level key."""
        session = FakeSession()
        batch = EvidenceBatch(
            evidence=[
                _found("https://example.com/post", "They opened six QA roles."),
                _found("https://example.com/post", "The release train slipped twice."),
            ]
        )
        outcome = await store_found(
            session, account_id=uuid.uuid4(), batch=batch
        )
        assert outcome.count == 2
        assert outcome.duplicates == 0
        # Same document, so the source hash is shared — that is the point of
        # keeping both hashes rather than one.
        assert len({r.source_hash for r in outcome.stored}) == 1
        assert len({r.excerpt_hash for r in outcome.stored}) == 2

    async def test_a_passage_already_held_is_skipped_not_replaced(self):
        """The held row may already be cited. Replacing it breaks the citation."""
        key = excerpt_hash("https://example.com/a", "They opened six QA roles.")
        session = FakeSession(existing=[key])
        batch = EvidenceBatch(
            evidence=[_found("https://example.com/a", "They opened six QA roles.")]
        )
        outcome = await store_found(session, account_id=uuid.uuid4(), batch=batch)
        assert outcome.count == 0
        assert outcome.duplicates == 1
        assert session.added == []

    async def test_a_batch_that_repeats_itself_stores_once(self):
        """Without the in-flight guard this is an IntegrityError at flush.

        And the flush takes the whole family's evidence with it — one repeated
        sentence would cost every other passage in the batch.
        """
        session = FakeSession()
        batch = EvidenceBatch(
            evidence=[
                _found("https://example.com/a", "They opened six QA roles."),
                _found("https://example.com/a", "They opened six QA roles."),
            ]
        )
        outcome = await store_found(session, account_id=uuid.uuid4(), batch=batch)
        assert outcome.count == 1
        assert outcome.duplicates == 1

    def test_whitespace_differences_do_not_defeat_the_key(self):
        """The same sentence re-retrieved often differs only by a line break."""
        a = excerpt_hash("https://example.com/a", "They opened  six QA roles.")
        b = excerpt_hash("https://example.com/a", "They opened six QA roles.\n")
        assert a == b

    def test_the_same_sentence_from_two_places_is_two_rows(self):
        """Two sources saying the same thing is corroboration, not a duplicate."""
        a = excerpt_hash("https://example.com/a", "They opened six QA roles.")
        b = excerpt_hash("https://other.example/b", "They opened six QA roles.")
        assert a != b

    def test_the_source_hash_is_not_the_dedup_key(self):
        one = source_hash("https://example.com/post", "Northwind hiring")
        two = source_hash("https://example.com/post", "Northwind hiring")
        assert one == two, "the same document must hash the same for the index"


class TestWhatIsWrittenToTheRow:
    async def test_raw_status_is_unavailable_without_a_snapshot(self):
        """`stored` with no `raw_ref` violates the table's own check.

        Writing `stored` optimistically is an IntegrityError at flush, which
        surfaces as a failed research run rather than as the missing feature
        it actually is.
        """
        session = FakeSession()
        batch = EvidenceBatch(evidence=[_found("https://example.com/a", "x")])
        outcome = await store_found(session, account_id=uuid.uuid4(), batch=batch)
        assert outcome.stored[0].raw_status == "unavailable"
        assert outcome.stored[0].raw_ref is None

    async def test_observed_at_is_carried_through_not_replaced_with_today(self):
        """When the fact was true, never when it was retrieved."""
        from datetime import date

        session = FakeSession()
        batch = EvidenceBatch(
            evidence=[
                _found("https://example.com/a", "Closed a Series B.", observed_at=date(2023, 5, 1))
            ]
        )
        outcome = await store_found(session, account_id=uuid.uuid4(), batch=batch)
        assert outcome.stored[0].observed_at == date(2023, 5, 1)

    async def test_an_undated_source_stays_undated(self):
        """Guessing a date would turn old history into a live trigger."""
        session = FakeSession()
        batch = EvidenceBatch(evidence=[_found("https://example.com/a", "x")])
        outcome = await store_found(session, account_id=uuid.uuid4(), batch=batch)
        assert outcome.stored[0].observed_at is None

    async def test_an_empty_batch_does_not_touch_the_database(self):
        session = FakeSession()
        batch = EvidenceBatch(evidence=[], not_found=["Series B coverage"])
        outcome = await store_found(session, account_id=uuid.uuid4(), batch=batch)
        assert outcome.count == 0
        assert session.flushes == 0


class TestTheContractGuardsTheRow:
    def test_an_excerpt_may_not_be_empty(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _found("https://example.com/a", "")

    def test_reliability_is_a_proportion(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _found("https://example.com/a", "x", reliability=1.4)
