"""Versioning behaviour against a live database.

Marked ``db`` and skipped when TEST_DATABASE_URL is unset, so the suite still
runs in CI without Postgres.

The concurrency test is the one that matters. Every other assertion here would
also pass with a check-then-write in Python; only that one distinguishes a real
database constraint from application code that merely looks careful.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.config import SalesRules, ScoringConfig, SignalType
from app.services.versioning import activate_new_version, get_active

pytestmark = pytest.mark.db

TEST_DB = os.getenv("TEST_DATABASE_URL")
requires_db = pytest.mark.skipif(
    not TEST_DB, reason="TEST_DATABASE_URL not set — see backend/.env"
)

RULES = dict(
    priority_threshold=65,
    persona_weight_threshold=50,
    max_concurrent_threads=2,
    thread_start_offset_days=3,
    signal_ttl_days={"funding": 270},
)


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DB, poolclass=None)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
        await s.rollback()
    await engine.dispose()


@requires_db
class TestVersioning:
    async def test_first_activation_is_version_one(self, session):
        row = await activate_new_version(session, SalesRules, dict(RULES))
        assert row.version == 1
        assert row.is_active is True

    async def test_second_activation_supersedes_the_first(self, session):
        first = await activate_new_version(session, SalesRules, dict(RULES))
        second = await activate_new_version(
            session, SalesRules, {**RULES, "priority_threshold": 70}
        )
        await session.refresh(first)

        assert second.version == first.version + 1
        assert second.is_active is True
        assert first.is_active is False, "the previous version must be deactivated"

    async def test_the_old_row_is_kept_not_overwritten(self, session):
        """A change writes a new row. The old one must survive intact.

        A qualification computed against version 1 has to stay explainable after
        version 2 exists.
        """
        first = await activate_new_version(session, SalesRules, dict(RULES))
        first_id = first.id
        await activate_new_version(session, SalesRules, {**RULES, "priority_threshold": 70})

        kept = (
            await session.execute(select(SalesRules).where(SalesRules.id == first_id))
        ).scalar_one()
        assert kept.priority_threshold == 65, "the original value was mutated"

    async def test_exactly_one_active_row_after_several_changes(self, session):
        for threshold in (65, 70, 75, 80):
            await activate_new_version(
                session, SalesRules, {**RULES, "priority_threshold": threshold}
            )
        count = (
            await session.execute(
                select(func.count()).select_from(SalesRules).where(SalesRules.is_active)
            )
        ).scalar_one()
        assert count == 1

    async def test_get_active_returns_the_newest(self, session):
        await activate_new_version(session, SalesRules, dict(RULES))
        await activate_new_version(session, SalesRules, {**RULES, "priority_threshold": 88})
        active = await get_active(session, SalesRules)
        assert active is not None
        assert active.priority_threshold == 88

    async def test_llm_config_scopes_active_per_scenario(self, session):
        """One active row *per scenario*, not one overall."""
        from app.models.config import LlmConfig

        base = dict(effort="high", max_tokens=16000, output_contract="X")
        await activate_new_version(
            session, LlmConfig, {**base, "scenario": "signal_extraction"},
            scope_field="scenario",
        )
        await activate_new_version(
            session, LlmConfig, {**base, "scenario": "strategy_synthesis"},
            scope_field="scenario",
        )
        count = (
            await session.execute(
                select(func.count()).select_from(LlmConfig).where(LlmConfig.is_active)
            )
        ).scalar_one()
        assert count == 2, "scenarios must not deactivate each other"


@requires_db
class TestDatabaseEnforcesTheInvariant:
    async def test_two_concurrent_activations_cannot_both_win(self):
        """The point of the partial unique index.

        Two sessions activate at the same time. A check-then-write in Python
        lets both through — each sees no conflicting active row before either
        commits. The index means exactly one commit succeeds.
        """
        engine = create_async_engine(TEST_DB)
        maker = async_sessionmaker(engine, expire_on_commit=False)

        async def activate(threshold: int) -> bool:
            async with maker() as s:
                try:
                    await activate_new_version(
                        s, ScoringConfig,
                        dict(
                            dimension_weights={"fit": 20},
                            band_cutoffs={"high": 75},
                        ),
                    )
                    await s.commit()
                    return True
                except Exception:  # noqa: BLE001 - any failure means this racer lost
                    await s.rollback()
                    return False

        results = await asyncio.gather(activate(1), activate(2), return_exceptions=True)
        succeeded = sum(1 for r in results if r is True)

        async with maker() as s:
            active = (
                await s.execute(
                    select(func.count())
                    .select_from(ScoringConfig)
                    .where(ScoringConfig.is_active)
                )
            ).scalar_one()
        await engine.dispose()

        assert succeeded >= 1, "at least one activation should succeed"
        assert active == 1, f"expected exactly 1 active row, found {active}"


@requires_db
class TestSignalTypeRetirement:
    async def test_deprecating_keeps_the_row(self, session):
        """Retire by deprecating, never deleting."""
        from datetime import UTC, datetime

        st = SignalType(
            key="press_mention", label="Press mention", scope="company",
            default_ttl_days=90,
        )
        session.add(st)
        await session.flush()

        st.status = "deprecated"
        st.deprecated_at = datetime.now(UTC)
        await session.flush()

        found = (
            await session.execute(
                select(SignalType).where(SignalType.key == "press_mention")
            )
        ).scalar_one()
        assert found.status == "deprecated"
        assert found.deprecated_at is not None

    async def test_deprecated_without_a_timestamp_is_rejected(self, session):
        """The CHECK keeps status and deprecated_at in step."""
        from sqlalchemy.exc import IntegrityError

        session.add(
            SignalType(
                key="bad_state", label="Bad", scope="company",
                default_ttl_days=30, status="deprecated",
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
