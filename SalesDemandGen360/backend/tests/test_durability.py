"""How far back it is worth looking, and what each gate is responsible for.

Three gates, deliberately. The search prompt is a request, evidence intake is
the deterministic coarse rule, and extraction is the exact per-type one. The
tests that matter are the ones pinning the division of labour, because the
tempting simplification — one per-family window — is wrong for a reason that is
easy to forget: a source says what research *opens*, and every document it
returns is read against every active type.

Measured before any of this existed: five of the eight signals held were
already past `expires_at` on the day they were created.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.schemas.config import SignalTypeIn
from app.services.durability import (
    DEFAULT_DURABILITY_MULTIPLE,
    FALLBACK_DURABILITY_DAYS,
    cutoff_for_prompt,
    durability_of,
    research_cutoff,
    widest_durability,
)


@dataclass
class FakeType:
    default_ttl_days: int
    durability_days: int | None = None


class TestDurabilityDefaultsToThreeTimesTheTtl:
    def test_an_unset_durability_is_three_ttls(self):
        assert durability_of(FakeType(default_ttl_days=180)) == 540

    def test_an_explicit_value_wins(self):
        """The escape hatch for a type whose facts outlive the multiple — an
        acquisition is permanently true, a funding round is not."""
        assert durability_of(FakeType(default_ttl_days=180, durability_days=3650)) == 3650

    def test_the_multiple_is_not_hardcoded_in_the_caller(self):
        ttl = 123
        assert (
            durability_of(FakeType(default_ttl_days=ttl))
            == ttl * DEFAULT_DURABILITY_MULTIPLE
        )


class TestTheResearchWindowIsTheWidest:
    def test_the_window_is_the_longest_durability_not_the_shortest(self):
        """The whole design rests on this.

        `news` feeds `mgt_change` (540) and `partnership` (540), but a news
        document is also read against `tech_adoption` (1095). Taking the min —
        or the family's own feeds — would silently cost every `tech_adoption`
        signal that lives in a news article older than 540 days.
        """
        types = [
            FakeType(default_ttl_days=60),  # 180
            FakeType(default_ttl_days=365),  # 1095
            FakeType(default_ttl_days=180),  # 540
        ]
        assert widest_durability(types) == 1095

    def test_an_explicit_durability_can_widen_the_window(self):
        types = [FakeType(default_ttl_days=90, durability_days=4000)]
        assert widest_durability(types) == 4000

    def test_no_active_types_leaves_the_gate_open(self):
        """Research with no active types has nothing to look for. The gate must
        not be the thing that decides that, or an empty registry would read as
        "everything is too old" rather than "nothing is configured"."""
        assert widest_durability([]) == FALLBACK_DURABILITY_DAYS


class TestTheCutoffInThePromptIsRoundedToAMonth:
    def test_two_days_in_one_month_produce_the_same_string(self):
        """A cutoff that moves daily moves the prompt daily, and a prompt that
        differs byte-for-byte between runs never hits cache — the same trap as
        a timestamp in serialised config."""
        assert cutoff_for_prompt(date(2023, 10, 1)) == cutoff_for_prompt(date(2023, 10, 28))

    def test_it_still_says_which_month(self):
        assert cutoff_for_prompt(date(2023, 10, 1)) == "October 2023"


class TestDurabilityMayNotBeShorterThanTheTtl:
    """A type like this could never produce a usable signal: its evidence would
    be refused before the signal stopped counting, so expiry is unreachable
    because nothing can be stored to reach it."""

    def test_the_schema_refuses_it(self):
        with pytest.raises(ValueError, match="at least default_ttl_days"):
            SignalTypeIn(
                key="too_brief",
                label="Too brief",
                scope="company",
                default_ttl_days=180,
                durability_days=90,
            )

    def test_equal_is_allowed(self):
        row = SignalTypeIn(
            key="exactly",
            label="Exactly",
            scope="company",
            default_ttl_days=180,
            durability_days=180,
        )
        assert row.durability_days == 180

    def test_unset_is_allowed(self):
        row = SignalTypeIn(
            key="unset", label="Unset", scope="company", default_ttl_days=180
        )
        assert row.durability_days is None


# --------------------------------------------------------------------------
# The gates, against the database
# --------------------------------------------------------------------------
pytest_db = [
    pytest.mark.db,
    pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"),
]


@pytest.fixture
async def session():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
        await s.rollback()
    await engine.dispose()


@pytest.mark.db
@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")
class TestEvidenceIntakeRefusesWhatNoTypeCouldUse:
    async def test_a_dated_passage_beyond_the_window_is_refused(self, session):
        from app.schemas.evidence import EvidenceBatch, FoundEvidence
        from app.services.evidence import store_found

        account_id = await _an_account(session)
        cutoff = await research_cutoff(session)
        outcome = await store_found(
            session,
            account_id=account_id,
            batch=EvidenceBatch(
                evidence=[
                    FoundEvidence(
                        source_type="news",
                        source_url="https://example.test/old",
                        excerpt="They appointed a new benefits lead.",
                        observed_at=cutoff - timedelta(days=1),
                    )
                ]
            ),
        )
        assert outcome.count == 0
        assert outcome.stale == 1

    async def test_an_undated_passage_is_kept(self, session):
        """Half the evidence held when this was written carried no date at all
        — every provider and job-board row. Treating undated as stale would
        throw all of it away."""
        from app.schemas.evidence import EvidenceBatch, FoundEvidence
        from app.services.evidence import store_found

        account_id = await _an_account(session)
        outcome = await store_found(
            session,
            account_id=account_id,
            batch=EvidenceBatch(
                evidence=[
                    FoundEvidence(
                        source_type="provider",
                        source_url=f"https://example.test/{uuid.uuid4()}",
                        excerpt="Undated, and still worth keeping.",
                        observed_at=None,
                    )
                ]
            ),
        )
        assert outcome.count == 1
        assert outcome.stale == 0

    async def test_a_passage_inside_the_window_is_kept(self, session):
        from app.schemas.evidence import EvidenceBatch, FoundEvidence
        from app.services.evidence import store_found

        account_id = await _an_account(session)
        cutoff = await research_cutoff(session)
        outcome = await store_found(
            session,
            account_id=account_id,
            batch=EvidenceBatch(
                evidence=[
                    FoundEvidence(
                        source_type="news",
                        source_url=f"https://example.test/{uuid.uuid4()}",
                        excerpt="Recent enough to matter.",
                        observed_at=cutoff + timedelta(days=1),
                    )
                ]
            ),
        )
        assert outcome.count == 1
        assert outcome.stale == 0


async def _an_account(session) -> uuid.UUID:
    row = await session.execute(
        text("INSERT INTO account (name) VALUES ('Durability Test Co') RETURNING id")
    )
    await session.flush()
    return row.scalar_one()
