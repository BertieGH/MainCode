"""The evidence-resolution guard, against a real database.

These are the three conditions `docs/08` sets for Phase 3, plus the failure
modes that would let a hallucinated citation through.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.account import Account, Contact
from app.models.config import SignalType
from app.models.signal import Evidence, Signal, signal_evidence
from app.schemas.signal import ExtractedSignal, SignalBatch, build_batch_model
from app.services.extraction import (
    SAME_FACT_SIMILARITY,
    expiry_for,
    page_of,
    similarity,
    store_batch,
    words_of,
)

pytestmark = pytest.mark.db

TEST_DB = os.getenv("TEST_DATABASE_URL")
requires_db = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DB)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
        await s.rollback()
    await engine.dispose()


@pytest.fixture
async def world(session):
    """An account, a contact, and one company + one contact signal type."""
    account = Account(name="Meridian Cloud", domain="MERIDIANCLOUD.IO")
    other = Account(name="Other Co", domain="OTHER.IO")
    session.add_all([account, other])
    await session.flush()

    contact = Contact(account_id=account.id, full_name="Dana Reyes")
    session.add(contact)
    session.add_all(
        [
            SignalType(key="funding", label="Funding", scope="company", default_ttl_days=300),
            SignalType(
                key="role_change", label="New in role", scope="contact", default_ttl_days=180
            ),
        ]
    )
    await session.flush()
    return {"account": account, "other": other, "contact": contact}


async def _evidence(session, account_id, excerpt="They raised a Series B.") -> Evidence:
    row = Evidence(
        account_id=account_id,
        source_type="news",
        source_url="https://example.test/a",
        excerpt=excerpt,
        source_hash="doc-1",
        excerpt_hash=f"hash-{excerpt}",
        raw_ref="s3://snap/1",
    )
    session.add(row)
    await session.flush()
    return row


def _signal(**over) -> ExtractedSignal:
    base = dict(
        signal_type="funding",
        summary="Raised a Series B",
        strength="high",
        confidence=0.9,
        observed_at=date(2026, 8, 1),
        evidence_ids=[],
    )
    return ExtractedSignal(**{**base, **over})


async def _count(session, model) -> int:
    return await session.scalar(select(func.count()).select_from(model))


@requires_db
class TestHallucinatedCitationsAreDropped:
    async def test_a_signal_citing_an_unknown_id_is_not_stored(self, session, world):
        ev = await _evidence(session, world["account"].id)
        ghost = str(uuid.uuid4())

        outcome = await store_batch(
            session,
            account_id=world["account"].id,
            batch=SignalBatch(
                signals=[
                    _signal(evidence_ids=[str(ev.id)]),
                    _signal(summary="Invented", evidence_ids=[ghost]),
                ]
            ),
        )

        assert outcome.stored == 1
        assert len(outcome.dropped) == 1
        assert outcome.dropped[0].summary == "Invented"
        assert ghost in outcome.dropped[0].unknown_evidence_ids
        assert await _count(session, Signal) == 1, "the invented signal reached the table"

    async def test_one_bad_citation_drops_only_that_signal(self, session, world):
        """A constraint violation would abort the transaction and take the good
        signals with it. One bad signal must cost one signal."""
        ev = await _evidence(session, world["account"].id)
        # Three different facts: a date each. Three readings of one passage on
        # one date are one fact, and would now be counted as duplicates — which
        # is not what this test is about.
        good = [
            _signal(summary=f"Good {i}", observed_at=date(2026, 8, 1 + i), evidence_ids=[str(ev.id)])
            for i in range(3)
        ]
        bad = _signal(summary="Bad", evidence_ids=[str(uuid.uuid4())])

        outcome = await store_batch(
            session, account_id=world["account"].id, batch=SignalBatch(signals=[*good, bad])
        )

        assert outcome.stored == 3
        assert len(outcome.dropped) == 1

    async def test_a_partly_real_citation_list_is_still_refused(self, session, world):
        """Half-true is not true. A signal resting on one real and one invented
        excerpt cannot be shown to a rep as sourced."""
        ev = await _evidence(session, world["account"].id)
        outcome = await store_batch(
            session,
            account_id=world["account"].id,
            batch=SignalBatch(signals=[_signal(evidence_ids=[str(ev.id), str(uuid.uuid4())])]),
        )
        assert outcome.stored == 0
        assert len(outcome.dropped) == 1

    async def test_a_malformed_id_is_treated_as_missing(self, session, world):
        outcome = await store_batch(
            session,
            account_id=world["account"].id,
            batch=SignalBatch(signals=[_signal(evidence_ids=["not-a-uuid"])]),
        )
        assert outcome.stored == 0
        assert "not-a-uuid" in outcome.dropped[0].unknown_evidence_ids

    async def test_evidence_from_another_account_does_not_resolve(self, session, world):
        """Otherwise a citation leaks one prospect's documents into another's
        audit trail, and the id would resolve perfectly."""
        foreign = await _evidence(session, world["other"].id)

        outcome = await store_batch(
            session,
            account_id=world["account"].id,
            batch=SignalBatch(signals=[_signal(evidence_ids=[str(foreign.id)])]),
        )

        assert outcome.stored == 0
        assert str(foreign.id) in outcome.dropped[0].unknown_evidence_ids


@requires_db
class TestScopeIsEnforcedBeforeTheDatabaseSeesIt:
    async def test_a_contact_type_without_a_contact_is_dropped(self, session, world):
        ev = await _evidence(session, world["account"].id)
        outcome = await store_batch(
            session,
            account_id=world["account"].id,
            batch=SignalBatch(
                signals=[_signal(signal_type="role_change", evidence_ids=[str(ev.id)])]
            ),
        )
        assert outcome.stored == 0
        assert "contact_id" in outcome.dropped[0].reason

    async def test_a_company_type_carrying_a_contact_is_dropped(self, session, world):
        ev = await _evidence(session, world["account"].id)
        outcome = await store_batch(
            session,
            account_id=world["account"].id,
            batch=SignalBatch(
                signals=[_signal(contact_id=world["contact"].id, evidence_ids=[str(ev.id)])]
            ),
        )
        assert outcome.stored == 0
        assert "contact_id" in outcome.dropped[0].reason

    async def test_a_valid_contact_signal_is_stored_with_its_scope(self, session, world):
        ev = await _evidence(session, world["account"].id)
        outcome = await store_batch(
            session,
            account_id=world["account"].id,
            batch=SignalBatch(
                signals=[
                    _signal(
                        signal_type="role_change",
                        contact_id=world["contact"].id,
                        evidence_ids=[str(ev.id)],
                    )
                ]
            ),
        )
        assert outcome.stored == 1
        row = (await session.execute(select(Signal))).scalar_one()
        assert row.scope == "contact", "scope is taken from the registry, not the model"
        assert row.contact_id == world["contact"].id

    async def test_a_paused_type_stops_producing_signals(self, session, world):
        """Pause exists to take a noisy type out of extraction. If signals were
        still written, pausing would change nothing a rep could see."""
        st = (
            await session.execute(select(SignalType).where(SignalType.key == "funding"))
        ).scalar_one()
        st.status, st.paused_at = "paused", func.now()
        await session.flush()

        ev = await _evidence(session, world["account"].id)
        outcome = await store_batch(
            session,
            account_id=world["account"].id,
            batch=SignalBatch(signals=[_signal(evidence_ids=[str(ev.id)])]),
        )
        assert outcome.stored == 0
        assert "inactive" in outcome.dropped[0].reason


@requires_db
class TestOneDocumentManyExcerpts:
    async def test_three_excerpts_from_one_document_all_survive(self, session, world):
        """The Phase 3 condition. Deduping on the document would admit only the
        first excerpt, and signals citing the other two would then be dropped by
        the guard — looking exactly like hallucination."""
        rows = [
            await _evidence(session, world["account"].id, excerpt=f"Passage {i}")
            for i in range(3)
        ]
        assert len({r.id for r in rows}) == 3
        assert len({r.source_hash for r in rows}) == 1, "same document, by construction"

        outcome = await store_batch(
            session,
            account_id=world["account"].id,
            batch=SignalBatch(
                signals=[_signal(evidence_ids=[str(r.id) for r in rows])]
            ),
        )

        assert outcome.stored == 1
        joins = await session.scalar(
            select(func.count()).select_from(signal_evidence)
        )
        assert joins == 3

    async def test_the_same_excerpt_cited_twice_is_stored_once(self, session, world):
        # Repetition is not corroboration, and the composite primary key would
        # reject the second row and abort the batch.
        ev = await _evidence(session, world["account"].id)
        outcome = await store_batch(
            session,
            account_id=world["account"].id,
            batch=SignalBatch(signals=[_signal(evidence_ids=[str(ev.id), str(ev.id)])]),
        )
        assert outcome.stored == 1
        assert await session.scalar(select(func.count()).select_from(signal_evidence)) == 1

    async def test_the_first_citation_is_marked_primary(self, session, world):
        rows = [
            await _evidence(session, world["account"].id, excerpt=f"P{i}") for i in range(2)
        ]
        await store_batch(
            session,
            account_id=world["account"].id,
            batch=SignalBatch(signals=[_signal(evidence_ids=[str(r.id) for r in rows])]),
        )
        roles = list(
            (await session.execute(select(signal_evidence.c.role))).scalars()
        )
        assert sorted(roles) == ["primary", "supporting"]


@requires_db
class TestTheDatabaseHalfOfTheInvariant:
    async def test_a_signal_with_no_evidence_cannot_be_committed(self, session, world):
        """The deferred trigger. It runs at COMMIT, so the signal inserts fine
        and the failure arrives when the transaction tries to close — which is
        the only point at which "has it got evidence yet?" has an answer."""
        row = Signal(
            account_id=world["account"].id,
            signal_type="funding",
            scope="company",
            summary="Unsupported",
            strength="low",
            confidence=0.5,
            observed_at=date(2026, 8, 1),
        )
        session.add(row)
        await session.flush()  # the row inserts; the trigger has not run yet

        with pytest.raises(Exception, match="has no evidence"):
            await session.commit()

    async def test_evidence_cited_by_a_signal_cannot_be_deleted(self, session, world):
        """ON DELETE RESTRICT. A signal must never lose its citation."""
        ev = await _evidence(session, world["account"].id)
        await store_batch(
            session,
            account_id=world["account"].id,
            batch=SignalBatch(signals=[_signal(evidence_ids=[str(ev.id)])]),
        )
        with pytest.raises(Exception, match="violates foreign key|still referenced"):
            await session.execute(
                text("DELETE FROM evidence WHERE id = :i"), {"i": str(ev.id)}
            )
            await session.flush()


@requires_db
class TestAgeing:
    async def test_expiry_is_observed_at_plus_the_type_ttl(self, session, world):
        ev = await _evidence(session, world["account"].id)
        await store_batch(
            session,
            account_id=world["account"].id,
            batch=SignalBatch(
                signals=[_signal(observed_at=date(2026, 1, 1), evidence_ids=[str(ev.id)])]
            ),
        )
        row = (await session.execute(select(Signal))).scalar_one()
        assert row.expires_at == date(2026, 10, 28), "1 Jan + 300 days"

    async def test_expiry_dates_from_observation_not_retrieval(self):
        # A funding round from three years ago is not a trigger, however
        # recently the page describing it was fetched.
        assert expiry_for(date(2023, 1, 1), 90) == date(2023, 4, 1)


class TestTheOutputSchemaComesFromTheRegistry:
    def test_only_registered_types_are_accepted(self):
        model = build_batch_model(["funding", "hiring"])
        ok = model(signals=[_signal(evidence_ids=["x"]).model_dump()])
        assert len(ok.signals) == 1

        with pytest.raises(ValidationError):
            model(signals=[_signal(signal_type="invented", evidence_ids=["x"]).model_dump()])

    def test_an_empty_registry_permits_no_signals(self):
        """The honest reading of "nothing is configured to be extracted"."""
        model = build_batch_model([])
        assert model(signals=[]).signals == []
        with pytest.raises(ValidationError):
            model(signals=[{"anything": 1}])

    def test_evidence_ids_cannot_be_empty(self):
        with pytest.raises(ValidationError):
            ExtractedSignal(
                signal_type="funding", summary="x", strength="low",
                confidence=0.5, observed_at=date(2026, 1, 1), evidence_ids=[],
            )


@requires_db
class TestTheSameFactReadTwice:
    """Evidence is re-interpreted on every run — a rerun, a new family, a wider
    window. Seen live on BlueWave: a 2022 funding round and a Feb 2026
    acquisition each written twice, one row per run, every copy expiring on the
    same day and every copy counted as a separate conclusion.
    """

    async def _extract(self, session, world, evidence, *, summary="Series B closed"):
        return await store_batch(
            session,
            account_id=world["account"].id,
            batch=SignalBatch(signals=[
                ExtractedSignal(
                    signal_type="funding", summary=summary, strength="high",
                    confidence=0.9, observed_at=date(2026, 8, 1),
                    evidence_ids=[str(evidence.id)],
                )
            ]),
        )

    async def test_the_second_reading_is_counted_not_stored(self, session, world):
        ev = await _evidence(session, world["account"].id)
        first = await self._extract(session, world, ev)
        second = await self._extract(session, world, ev, summary="They closed a Series B")

        assert (first.stored, first.duplicates) == (1, 0)
        assert (second.stored, second.duplicates) == (0, 1), "wrote the same fact twice"
        assert await _count(session, Signal) == 1

    async def test_a_different_date_is_a_different_fact(self, session, world):
        ev = await _evidence(session, world["account"].id)
        await self._extract(session, world, ev)
        later = await store_batch(
            session,
            account_id=world["account"].id,
            batch=SignalBatch(signals=[
                ExtractedSignal(
                    signal_type="funding", summary="Series C closed", strength="high",
                    confidence=0.9, observed_at=date(2026, 9, 1),
                    evidence_ids=[str(ev.id)],
                )
            ]),
        )
        assert later.stored == 1
        assert await _count(session, Signal) == 2

    async def test_a_different_passage_on_the_same_day_is_a_different_fact(
        self, session, world
    ):
        """Two appointments announced on one day are two signals. Type and date
        alone would collapse them; the shared citation is what makes a
        duplicate a duplicate."""
        first_ev = await _evidence(session, world["account"].id, excerpt="A joined as CTO.")
        second_ev = await _evidence(session, world["account"].id, excerpt="B joined as CFO.")
        await self._extract(session, world, first_ev, summary="A joined")
        outcome = await self._extract(session, world, second_ev, summary="B joined")

        assert (outcome.stored, outcome.duplicates) == (1, 0)
        assert await _count(session, Signal) == 2


class TestWhatCountsAsOnePage:
    def test_spelling_of_a_url_is_not_a_different_page(self):
        assert page_of("HTTPS://www.CBTS.com/newsroom/award/") == page_of(
            "https://www.cbts.com/newsroom/award#top"
        )

    def test_a_query_string_can_be_the_page(self):
        assert page_of("https://x.test/news?id=1") != page_of("https://x.test/news?id=2")

    def test_no_url_is_no_page(self):
        assert page_of(None) is None
        assert page_of("   ") is None


class TestTheThresholdAgainstTheRealPairs:
    """The pairs that set it, word for word as extraction wrote them."""

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            (
                "Bluewave announced an initial capital raise of $75 million led by Columbia Capital.",
                "Bluewave Technology Group secured an initial capital raise of $75 million led by "
                "Columbia Capital.",
            ),
            (
                "CBTS named Bluewave Technology Group as 2024 Strategic Growth Partner of the Year.",
                "CBTS named Bluewave Technology Group as its 2024 Strategic Growth Partner of the Year.",
            ),
        ],
    )
    def test_one_fact_worded_twice_is_above_it(self, a, b):
        assert similarity(words_of(a), words_of(b)) >= SAME_FACT_SIMILARITY

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            (
                "Bluewave appointed Drew Cather as Chief Revenue Officer.",
                "Bluewave Technology Group acquired CloudZen Partners and appointed multiple key "
                "executives including a new Chief Revenue Officer.",
            ),
            ("A joined", "B joined"),
        ],
    )
    def test_two_facts_from_one_release_are_below_it(self, a, b):
        assert similarity(words_of(a), words_of(b)) < SAME_FACT_SIMILARITY


@requires_db
class TestTheSameFactFromTheSamePage:
    """Seen live on BlueWave: the CBTS award quoted differently on two runs was
    stored as two passages, shared no citation, and so became two signals.
    Every passage from `_evidence` is on one page, which is the case here."""

    async def _store(self, session, world, evidence, summary, *, signal_type="funding",
                     contact_id=None):
        return await store_batch(
            session,
            account_id=world["account"].id,
            batch=SignalBatch(signals=[
                ExtractedSignal(
                    signal_type=signal_type, summary=summary, strength="high",
                    confidence=0.9, observed_at=date(2026, 8, 1),
                    evidence_ids=[str(evidence.id)], contact_id=contact_id,
                )
            ]),
        )

    async def test_one_fact_quoted_twice_from_one_page_is_one_signal(self, session, world):
        account_id = world["account"].id
        first = await _evidence(session, account_id, excerpt="CBTS names Bluewave partner of the year.")
        second = await _evidence(session, account_id, excerpt="Bluewave recognised by CBTS as partner.")
        await self._store(
            session, world, first,
            "CBTS named Bluewave Technology Group as 2024 Strategic Growth Partner of the Year.",
        )
        outcome = await self._store(
            session, world, second,
            "CBTS named Bluewave Technology Group as its 2024 Strategic Growth Partner of the Year.",
        )
        assert (outcome.stored, outcome.duplicates) == (0, 1), "the CBTS award, twice"
        assert await _count(session, Signal) == 1

    async def test_two_facts_from_one_release_stay_two(self, session, world):
        """An acquisition and an appointment, one press release, one day."""
        account_id = world["account"].id
        first = await _evidence(session, account_id, excerpt="Drew Cather joins as CRO.")
        second = await _evidence(session, account_id, excerpt="Bluewave acquires CloudZen.")
        await self._store(session, world, first, "Bluewave appointed Drew Cather as Chief Revenue Officer.")
        outcome = await self._store(
            session, world, second,
            "Bluewave Technology Group acquired CloudZen Partners and appointed multiple key "
            "executives including a new Chief Revenue Officer.",
        )
        assert (outcome.stored, outcome.duplicates) == (1, 0)
        assert await _count(session, Signal) == 2

    async def test_two_people_in_one_article_are_two_signals(self, session, world):
        """Even citing the very same passage. The shared citation used to make
        the second person a duplicate of the first."""
        account_id = world["account"].id
        other = Contact(account_id=account_id, full_name="Sam Lee")
        session.add(other)
        await session.flush()
        article = await _evidence(session, account_id, excerpt="Dana Reyes and Sam Lee join as VPs.")
        await self._store(session, world, article, "Dana Reyes joined as VP Engineering.",
                          signal_type="role_change", contact_id=world["contact"].id)
        outcome = await self._store(session, world, article, "Sam Lee joined as VP Engineering.",
                                    signal_type="role_change", contact_id=other.id)
        assert (outcome.stored, outcome.duplicates) == (1, 0)
        assert await _count(session, Signal) == 2

    async def test_one_batch_cannot_hold_the_fact_twice(self, session, world):
        account_id = world["account"].id
        first = await _evidence(session, account_id, excerpt="Series B, one.")
        second = await _evidence(session, account_id, excerpt="Series B, two.")
        signals = [
            ExtractedSignal(
                signal_type="funding", summary=summary, strength="high", confidence=0.9,
                observed_at=date(2026, 8, 1), evidence_ids=[str(ev.id)],
            )
            for ev, summary in (
                (first, "Meridian Cloud raised a $40m Series B led by Northpoint."),
                (second, "Meridian Cloud closed a $40m Series B led by Northpoint."),
            )
        ]
        outcome = await store_batch(
            session, account_id=account_id, batch=SignalBatch(signals=signals)
        )
        assert (outcome.stored, outcome.duplicates) == (1, 1)


@requires_db
class TestAnOngoingThemeIsOneLiveSignal:
    """Seen live on BlueWave: four `public_focus` signals about one run of blog
    posts, dated 11 Aug, 13 Aug, 25 Aug and 10 Sep — another on nearly every
    re-read, because dedupe keyed on a date an ongoing theme does not have."""

    @pytest.fixture
    async def theme(self, session):
        row = SignalType(
            key="public_focus", label="Public focus", scope="company", default_ttl_days=90,
            kind="theme",
        )
        session.add(row)
        await session.flush()
        return row

    async def _read(self, session, world, observed, *, excerpt, summary="Publishing on AI networks."):
        ev = await _evidence(session, world["account"].id, excerpt=excerpt)
        return await store_batch(
            session,
            account_id=world["account"].id,
            batch=SignalBatch(signals=[
                ExtractedSignal(
                    signal_type="public_focus", summary=summary, strength="medium",
                    confidence=0.8, observed_at=observed, evidence_ids=[str(ev.id)],
                )
            ]),
        )

    async def test_an_older_reading_is_a_duplicate(self, session, world, theme):
        """Whatever it says: a theme is one theme, and an older date is not news."""
        await self._read(session, world, date(2026, 9, 10), excerpt="post of 10 Sep")
        outcome = await self._read(
            session, world, date(2026, 8, 11), excerpt="post of 11 Aug",
            summary="Entirely different words about network readiness.",
        )
        assert (outcome.stored, outcome.duplicates) == (0, 1)
        assert await _count(session, Signal) == 1

    async def test_the_same_date_is_a_duplicate(self, session, world, theme):
        await self._read(session, world, date(2026, 9, 10), excerpt="first quote")
        outcome = await self._read(session, world, date(2026, 9, 10), excerpt="second quote")
        assert (outcome.stored, outcome.duplicates) == (0, 1)

    async def test_a_newer_reading_moves_the_theme_forward(self, session, world, theme):
        """Stored, and the old reading stops counting — so the theme's expiry
        runs from its newest post rather than lapsing while it continues."""
        await self._read(session, world, date(2026, 8, 25), excerpt="post of 25 Aug")
        outcome = await self._read(session, world, date(2026, 9, 10), excerpt="post of 10 Sep")
        assert outcome.stored == 1
        old, new = (await session.execute(select(Signal).order_by(Signal.observed_at))).scalars().all()
        await session.refresh(old)
        assert old.superseded_by == new.id
        assert new.superseded_by is None
        assert new.expires_at == date(2026, 12, 9), "10 Sep + 90 days"

    async def test_only_the_newest_reading_is_live(self, session, world, theme):
        from app.services.context import live_signals

        await self._read(session, world, date(2026, 8, 25), excerpt="post of 25 Aug")
        await self._read(session, world, date(2026, 9, 10), excerpt="post of 10 Sep")
        live = await live_signals(session, world["account"].id, today=date(2026, 9, 13))
        assert [s.observed_at for s in live] == [date(2026, 9, 10)]

    async def test_copies_from_before_it_was_a_theme_are_all_superseded(self, session, world, theme):
        """A type switched to a theme after collecting copies: the next newer
        reading retires every one of them, not only the latest."""
        theme.kind = "event"
        await session.flush()
        await self._read(session, world, date(2026, 8, 11), excerpt="11 Aug", summary="A")
        await self._read(session, world, date(2026, 8, 25), excerpt="25 Aug", summary="B")
        theme.kind = "theme"
        await session.flush()

        await self._read(session, world, date(2026, 9, 10), excerpt="10 Sep", summary="C")
        rows = (await session.execute(select(Signal).order_by(Signal.observed_at))).scalars().all()
        for row in rows:
            await session.refresh(row)
        newest = rows[-1]
        assert [r.superseded_by for r in rows[:-1]] == [newest.id, newest.id]
        assert newest.superseded_by is None

    async def test_two_people_keep_their_own_themes(self, session, world):
        """A theme is per person as well as per type."""
        session.add(
            SignalType(key="talks_about", label="Talks about", scope="contact",
                       default_ttl_days=90, kind="theme")
        )
        other = Contact(account_id=world["account"].id, full_name="Sam Lee")
        session.add(other)
        await session.flush()
        for contact, excerpt in ((world["contact"], "Dana posts"), (other, "Sam posts")):
            ev = await _evidence(session, world["account"].id, excerpt=excerpt)
            outcome = await store_batch(
                session,
                account_id=world["account"].id,
                batch=SignalBatch(signals=[
                    ExtractedSignal(
                        signal_type="talks_about", summary="Posts about QA", strength="low",
                        confidence=0.7, observed_at=date(2026, 9, 1),
                        evidence_ids=[str(ev.id)], contact_id=contact.id,
                    )
                ]),
            )
            assert outcome.stored == 1


@requires_db
class TestASignalMayNotBeBornAlreadyExpired:
    """The exact per-type gate.

    `expiry_for` is arithmetic and nothing compared its answer to today, so a
    stale document produced a signal whose `expires_at` was already in the
    past: filtered out of every prompt by `context.live_signals`, visible on
    the screen, and paid for. Five of the first eight signals held were this.

    Evidence intake applies the widest window across all active types, because
    one document is read against all of them. Here the type is known, so the
    window is its own — which is the whole reason both gates exist.
    """

    async def test_a_signal_dated_beyond_its_type_durability_is_dropped(self, session, world):
        ev = await _evidence(session, world["account"].id)
        # funding: ttl 300, so durability 900. Live example that motivated this
        # was mgt_change at 638 days against a 540-day durability.
        outcome = await store_batch(
            session,
            account_id=world["account"].id,
            batch=SignalBatch(signals=[
                _signal(observed_at=date.today() - timedelta(days=901),
                        evidence_ids=[str(ev.id)])
            ]),
        )
        assert outcome.stored == 0
        assert len(outcome.dropped) == 1
        assert "durability" in outcome.dropped[0].reason

    async def test_the_window_is_the_types_own_not_a_shared_one(self, session, world):
        """A date that is stale for one type and fine for another.

        600 days: past `role_change`'s 540 at ttl 180, inside `funding`'s 900
        at ttl 300. A single shared window could not get both of these right,
        which is why the gate reads the type.
        """
        ev = await _evidence(session, world["account"].id, excerpt="Dated six hundred days ago.")
        session.add(
            SignalType(key="brief_type", label="Brief", scope="company", default_ttl_days=180)
        )
        await session.flush()
        observed = date.today() - timedelta(days=600)

        outcome = await store_batch(
            session,
            account_id=world["account"].id,
            batch=SignalBatch(signals=[
                _signal(observed_at=observed, evidence_ids=[str(ev.id)]),
                _signal(signal_type="brief_type", summary="Too old for this type",
                        observed_at=observed, evidence_ids=[str(ev.id)]),
            ]),
        )
        assert outcome.stored == 1, "the long-durability signal should survive"
        assert [d.signal_type for d in outcome.dropped] == ["brief_type"]

    async def test_an_explicit_durability_overrides_the_default(self, session, world):
        """The escape hatch: an acquisition is permanently true."""
        session.add(
            SignalType(key="acquisition", label="Acquisition", scope="company",
                       default_ttl_days=180, durability_days=3650)
        )
        await session.flush()
        ev = await _evidence(session, world["account"].id, excerpt="Acquired in 2021.")

        outcome = await store_batch(
            session,
            account_id=world["account"].id,
            batch=SignalBatch(signals=[
                _signal(signal_type="acquisition", summary="Acquired by Simplicity",
                        observed_at=date.today() - timedelta(days=1200),
                        evidence_ids=[str(ev.id)])
            ]),
        )
        assert outcome.stored == 1, "1200 days is inside an explicit 3650-day durability"

    async def test_a_signal_inside_its_durability_is_stored_expired_but_kept(
        self, session, world
    ):
        """Past the TTL is not past the durability.

        The RFP360 case: `tech_adoption` observed 582 days ago, ttl 365, so
        expired as a trigger and still true as background. The gate must not
        become a second expiry check — that would throw away exactly the
        durable facts durability exists to keep.
        """
        ev = await _evidence(session, world["account"].id, excerpt="They selected RFP360.")
        observed = date.today() - timedelta(days=400)

        outcome = await store_batch(
            session,
            account_id=world["account"].id,
            batch=SignalBatch(signals=[
                _signal(observed_at=observed, evidence_ids=[str(ev.id)])
            ]),
        )
        assert outcome.stored == 1
        row = (await session.execute(
            select(Signal).where(Signal.observed_at == observed)
        )).scalar_one()
        assert row.expires_at < date.today(), "expired as a hook"
