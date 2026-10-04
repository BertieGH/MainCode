"""Signal type lifecycle: active → paused → active, and → deprecated (terminal).

The distinction is the point. Pause takes a noisy type out of extraction while
it is tuned and expects it back. Deprecate retires it for good. Collapsing them
would mean the only way to silence a type is to retire it permanently.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.config import SignalType

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


async def _make(session, key: str = "funding") -> SignalType:
    row = SignalType(key=key, label="Test", scope="company", default_ttl_days=90)
    session.add(row)
    await session.flush()
    return row


@requires_db
class TestPauseIsReversible:
    async def test_pause_sets_status_and_timestamp(self, session):
        row = await _make(session)
        row.status, row.paused_at = "paused", datetime.now(UTC)
        await session.flush()
        assert row.status == "paused"
        assert row.paused_at is not None

    async def test_resume_returns_to_active_and_clears_the_timestamp(self, session):
        row = await _make(session)
        row.status, row.paused_at = "paused", datetime.now(UTC)
        await session.flush()

        row.status, row.paused_at = "active", None
        await session.flush()

        assert row.status == "active"
        assert row.paused_at is None, "a resumed type must not keep a stale paused-since"

    async def test_pausing_does_not_set_deprecated_at(self, session):
        """Pause and deprecate are independent. Conflating the timestamps would
        make a paused type look retired in every report."""
        row = await _make(session)
        row.status, row.paused_at = "paused", datetime.now(UTC)
        await session.flush()
        assert row.deprecated_at is None


@requires_db
class TestConstraintsKeepStateHonest:
    async def test_paused_without_a_timestamp_is_rejected(self, session):
        row = await _make(session)
        row.status = "paused"  # paused_at deliberately left null
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_active_with_a_paused_timestamp_is_rejected(self, session):
        row = await _make(session)
        row.paused_at = datetime.now(UTC)  # status still 'active'
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_an_unknown_status_is_rejected(self, session):
        row = await _make(session)
        row.status = "archived"
        with pytest.raises(IntegrityError):
            await session.flush()


@requires_db
class TestDeletionIsOnlyForTypesWithNoHistory:
    """The deprecate-never-delete rule protects explainability, so it binds
    exactly where there is something to explain.

    A type with zero signals has nothing citing it: deleting it removes a
    registry row and no history at all. A mistyped type caught the same
    afternoon should not be a permanent tombstone in the registry.
    """

    async def test_an_unused_type_can_be_removed(self, session):
        row = await _make(session, "typo_type")
        await session.delete(row)
        await session.flush()

        found = (
            await session.execute(select(SignalType).where(SignalType.key == "typo_type"))
        ).scalar_one_or_none()
        assert found is None

    async def test_deleting_a_deprecated_but_unused_type_is_allowed(self, session):
        """Deprecating something by mistake must not trap it in the registry."""
        row = await _make(session, "typo_type")
        row.status, row.deprecated_at = "deprecated", datetime.now(UTC)
        await session.flush()

        await session.delete(row)
        await session.flush()
        assert (
            await session.execute(select(SignalType).where(SignalType.key == "typo_type"))
        ).scalar_one_or_none() is None


@requires_db
class TestDeprecationIsTerminal:
    async def test_deprecating_a_paused_type_clears_paused_at(self, session):
        """Both consistency checks have to hold at once.

        Leaving paused_at set while status becomes 'deprecated' violates the
        paused-consistency constraint, so the transition must clear it.
        """
        row = await _make(session)
        row.status, row.paused_at = "paused", datetime.now(UTC)
        await session.flush()

        row.status = "deprecated"
        row.deprecated_at = datetime.now(UTC)
        row.paused_at = None
        await session.flush()

        assert row.status == "deprecated"
        assert row.paused_at is None
        assert row.deprecated_at is not None

    async def test_the_row_survives_every_transition(self, session):
        """Nothing in this lifecycle deletes. A qualification decided partly on
        this type must still be able to explain itself afterwards."""
        row = await _make(session, "press_mention")
        row_id = row.id

        row.status, row.paused_at = "paused", datetime.now(UTC)
        await session.flush()
        row.status, row.paused_at, row.deprecated_at = "deprecated", None, datetime.now(UTC)
        await session.flush()

        found = (
            await session.execute(select(SignalType).where(SignalType.id == row_id))
        ).scalar_one()
        assert found.key == "press_mention"
        assert found.label == "Test", "the row was replaced rather than transitioned"
