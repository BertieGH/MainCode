"""`account_context` versioning and immutability."""

from __future__ import annotations

import os
import uuid
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.account import Account
from app.models.config import SignalType
from app.models.context import AccountContext
from app.models.signal import Evidence
from app.schemas.signal import SignalBatch
from app.services.context import build_context, build_payload, live_signals
from app.services.extraction import store_batch

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
async def account(session):
    row = Account(name="Meridian Cloud", domain="MERIDIANCLOUD.IO")
    session.add(row)
    session.add(
        SignalType(key="funding", label="Funding", scope="company", default_ttl_days=300)
    )
    await session.flush()
    return row


async def _signal(session, account, *, observed: date, summary="Raised a Series B"):
    ev = Evidence(
        account_id=account.id, source_type="news", excerpt=summary,
        source_hash="d", excerpt_hash=f"h-{summary}-{observed}", raw_ref="s3://x",
    )
    session.add(ev)
    await session.flush()
    await store_batch(
        session,
        account_id=account.id,
        batch=SignalBatch(
            signals=[
                {
                    "signal_type": "funding", "summary": summary, "strength": "high",
                    "confidence": 0.9, "observed_at": observed.isoformat(),
                    "evidence_ids": [str(ev.id)],
                }
            ]
        ),
    )


@requires_db
class TestVersioningNeverEditsInPlace:
    async def test_the_first_build_is_version_one(self, session, account):
        ctx = await build_context(session, account_id=account.id)
        assert ctx.version == 1
        assert ctx.parent_version is None

    async def test_a_rebuild_makes_a_new_version_and_leaves_the_old_one(self, session, account):
        """A strategy, a draft and an approval all point at a version. Editing
        one underneath them would leave an approved message justified by a
        context that no longer says what it said."""
        first = await build_context(session, account_id=account.id)
        first_payload = dict(first.payload)

        await _signal(session, account, observed=date(2026, 8, 1))
        second = await build_context(session, account_id=account.id)

        assert second.version == 2
        assert second.parent_version == 1

        rows = list(
            (
                await session.execute(
                    select(AccountContext).where(AccountContext.account_id == account.id)
                )
            ).scalars()
        )
        assert len(rows) == 2, "the rebuild replaced the earlier version"
        kept = next(r for r in rows if r.version == 1)
        assert kept.payload == first_payload

    async def test_two_rows_cannot_share_a_version(self, session, account):
        await build_context(session, account_id=account.id)
        session.add(
            AccountContext(
                account_id=account.id, version=1, payload={}, signal_ids=[]
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_a_parent_must_precede_its_child(self, session, account):
        session.add(
            AccountContext(
                account_id=account.id, version=1, parent_version=3,
                payload={}, signal_ids=[],
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_the_module_offers_no_way_to_edit_one(self):
        import app.services.context as mod

        assert not [n for n in dir(mod) if "update" in n or "edit" in n]


@requires_db
class TestWhatGoesIntoTheContext:
    async def test_expired_signals_are_left_out(self, session, account):
        """A funding round from three years ago is not a trigger."""
        await _signal(session, account, observed=date(2020, 1, 1), summary="Old round")
        await _signal(session, account, observed=date(2026, 8, 1), summary="Recent round")

        live = await live_signals(session, account.id, today=date(2026, 9, 5))
        assert [s.summary for s in live] == ["Recent round"]

    async def test_the_signal_ids_in_scope_are_recorded(self, session, account):
        """Stored rather than recomputed, so a context built last week can
        still explain itself after those signals expire."""
        await _signal(session, account, observed=date(2026, 8, 1))
        ctx = await build_context(session, account_id=account.id, today=date(2026, 9, 5))

        signals = await live_signals(session, account.id, today=date(2026, 9, 5))
        assert ctx.signal_ids == [str(s.id) for s in signals]
        assert len(ctx.signal_ids) == 1

    async def test_an_account_with_no_signals_still_builds(self, session, account):
        """A context is a statement about what we know, including nothing."""
        ctx = await build_context(session, account_id=account.id)
        assert ctx.payload["signal_count"] == 0
        assert ctx.signal_ids == []


class TestThePayloadIsCacheSafe:
    def test_ordering_does_not_depend_on_row_order(self):
        """The payload reaches a prompt. Unstable ordering would change the
        bytes between builds and silently cost the cache."""

        class Fake:
            def __init__(self, i, day):
                self.id = uuid.UUID(int=i)
                self.signal_type = "funding"
                self.scope = "company"
                self.summary = f"s{i}"
                self.business_implication = None
                self.strength = "high"
                self.confidence = 0.9
                self.observed_at = date(2026, 8, day)
                self.is_hypothesis = False
                self.contact_id = None

        rows = [Fake(1, 1), Fake(2, 2), Fake(3, 3)]
        assert build_payload(rows) == build_payload(list(reversed(rows)))

    def test_no_timestamp_is_baked_into_the_payload(self):
        from app.services.prompt import stable_json

        # stable_json raises on a datetime, so this passing means none is there.
        assert stable_json(build_payload([]))
