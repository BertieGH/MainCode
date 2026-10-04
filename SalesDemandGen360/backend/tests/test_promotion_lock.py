"""Phase 7: queue locking, cadence drift, and the enrolment lock under a race.

`docs/08` is explicit that the lock must be tested with genuine concurrency —
an application-level check passes a sequential test and fails in production. So
the race test below uses two independent engines, two independent sessions, and
two real COMMITs.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.account import Account, Contact
from app.models.campaign import (
    CadenceShape,
    CampaignQueue,
    CampaignQueueMember,
    LgmIdentity,
    OutreachCampaign,
    OutreachSequence,
)
from app.models.config import ServiceCatalog
from app.models.strategy import Strategy, StrategyThread
from app.services.cadence import (
    VERIFICATION_BACKSTOP_DAYS,
    SelectionInput,
    check_enrolment,
    enrolment_warnings,
    may_enrol,
    select_shape_key,
)
from app.services.promotion import (
    QueueLockedError,
    add_member,
    clone_queue,
    promote,
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


async def _queue(session, label="Sept push") -> CampaignQueue:
    row = CampaignQueue(label=label, status="draft")
    session.add(row)
    await session.flush()
    return row


async def _account(session, name="Meridian Cloud") -> Account:
    # Resolved: these tests are about locking, and `add_member` now refuses an
    # unconfirmed account before the lock is ever consulted.
    row = Account(
        name=name,
        domain=f"{name.replace(' ', '').upper()}.IO",
        resolution_status="resolved",
    )
    session.add(row)
    await session.flush()
    return row


@requires_db
class TestPromotionLocksTheQueue:
    async def test_promoting_locks_and_stamps_the_campaign(self, session):
        queue = await _queue(session)
        campaign = await promote(session, queue_ids=[queue.id], label="Sept EIA push")

        assert queue.status == "locked"
        assert queue.locked_at is not None
        assert queue.promoted_to_campaign_id == campaign.id

    async def test_a_locked_queue_refuses_new_members(self, session):
        queue = await _queue(session)
        account = await _account(session)
        await promote(session, queue_ids=[queue.id], label="Sept")

        with pytest.raises(QueueLockedError, match="clone it"):
            await add_member(session, queue_id=queue.id, account_id=account.id)

    async def test_a_queue_cannot_be_promoted_twice(self, session):
        """"Which version of the queue did campaign 2 use?" has to stay
        answerable, and it does not if one queue feeds two campaigns."""
        queue = await _queue(session)
        await promote(session, queue_ids=[queue.id], label="First")

        with pytest.raises(QueueLockedError, match="already promoted"):
            await promote(session, queue_ids=[queue.id], label="Second")

    async def test_locked_and_locked_at_cannot_disagree(self, session):
        session.add(CampaignQueue(label="bad", status="locked"))
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_the_sources_are_recorded_at_promotion(self, session):
        a, b = await _queue(session, "A"), await _queue(session, "B")
        campaign = await promote(session, queue_ids=[a.id, b.id], label="Merged")

        from app.models.campaign import OutreachCampaignSource

        sources = list(
            (
                await session.execute(
                    select(OutreachCampaignSource).where(
                        OutreachCampaignSource.campaign_id == campaign.id
                    )
                )
            ).scalars()
        )
        assert {s.queue_id for s in sources} == {a.id, b.id}


@requires_db
class TestCloningIsTheOnlyWayBack:
    async def test_a_clone_is_a_fresh_draft_carrying_the_members(self, session):
        queue = await _queue(session)
        account = await _account(session)
        await add_member(session, queue_id=queue.id, account_id=account.id)
        await promote(session, queue_ids=[queue.id], label="Sept")

        clone = await clone_queue(session, queue.id, label="Sept v2")

        assert clone.status == "draft"
        assert clone.cloned_from_queue_id == queue.id
        members = list(
            (
                await session.execute(
                    select(CampaignQueueMember).where(
                        CampaignQueueMember.queue_id == clone.id
                    )
                )
            ).scalars()
        )
        assert [m.account_id for m in members] == [account.id]

    async def test_the_original_stays_locked(self, session):
        queue = await _queue(session)
        await promote(session, queue_ids=[queue.id], label="Sept")
        await clone_queue(session, queue.id, label="Sept v2")
        assert queue.status == "locked"

    async def test_an_account_added_twice_is_counted_once(self, session):
        """A queue built from overlapping lists must not double-count."""
        queue = await _queue(session)
        account = await _account(session)
        assert await add_member(session, queue_id=queue.id, account_id=account.id)
        assert await add_member(session, queue_id=queue.id, account_id=account.id) is None

    async def test_provenance_survives_the_source_list_being_deleted(self, session):
        """`source_list_id` is a stamp with no behaviour, and nullable so the
        member outlives its list."""
        from app.models.account import AccountList

        lst = AccountList(label="Q3", source="csv", created_by="bertie")
        session.add(lst)
        await session.flush()

        queue = await _queue(session)
        account = await _account(session)
        member = await add_member(
            session, queue_id=queue.id, account_id=account.id, source_list_id=lst.id
        )
        assert member.source_list_id == lst.id

        await session.delete(lst)
        await session.flush()
        await session.refresh(member)
        assert member.source_list_id is None, "ON DELETE SET NULL keeps the member"


@requires_db
class TestTheEnrolmentLockIsAnIndexNotACheck:
    async def _thread(self, session, *, identity: LgmIdentity, name="Dana") -> StrategyThread:
        account = await _account(session, f"Co {uuid.uuid4().hex[:6]}")
        service = ServiceCatalog(code=f"s{uuid.uuid4().hex[:6]}", name="QA", description="d")
        session.add(service)
        await session.flush()
        contact = Contact(
            account_id=account.id, full_name=name, lgm_identity_id=identity.id
        )
        strategy = Strategy(account_id=account.id, version=1)
        session.add_all([contact, strategy])
        await session.flush()
        thread = StrategyThread(
            strategy_id=strategy.id,
            contact_id=contact.id,
            service_id=service.id,
            weight=60,
            rank=1,
            thread_status="active_primary",
            problem_hypothesis="h",
            trigger_summary="t",
            trigger_signal_ids=[str(uuid.uuid4())],
            positioning="p",
            channel_sequence=["email"],
            cta="c",
        )
        session.add(thread)
        await session.flush()
        return thread

    async def test_a_second_live_sequence_for_one_identity_is_rejected(self, session):
        identity = LgmIdentity(email="dana@meridian.io")
        session.add(identity)
        await session.flush()
        campaign = OutreachCampaign(label="C", status="draft")
        session.add(campaign)
        await session.flush()

        t1 = await self._thread(session, identity=identity)
        t2 = await self._thread(session, identity=identity, name="Dana again")

        session.add(
            OutreachSequence(
                thread_id=t1.id, campaign_id=campaign.id,
                lgm_identity_id=identity.id, status="pending_approval",
            )
        )
        await session.flush()

        session.add(
            OutreachSequence(
                thread_id=t2.id, campaign_id=campaign.id,
                lgm_identity_id=identity.id, status="pending_approval",
            )
        )
        with pytest.raises(IntegrityError, match="one_active_sequence_per_lgm_identity"):
            await session.flush()

    async def test_a_terminal_sequence_releases_the_lock(self, session):
        identity = LgmIdentity(email="dana@meridian.io")
        session.add(identity)
        await session.flush()
        campaign = OutreachCampaign(label="C", status="draft")
        session.add(campaign)
        await session.flush()

        t1 = await self._thread(session, identity=identity)
        t2 = await self._thread(session, identity=identity, name="Later")

        first = OutreachSequence(
            thread_id=t1.id, campaign_id=campaign.id,
            lgm_identity_id=identity.id, status="executing",
        )
        session.add(first)
        await session.flush()

        first.status = "completed"
        await session.flush()

        session.add(
            OutreachSequence(
                thread_id=t2.id, campaign_id=campaign.id,
                lgm_identity_id=identity.id, status="pending_approval",
            )
        )
        await session.flush()  # must not raise

    async def test_paused_still_holds_the_lock(self, session):
        """A paused sequence has unsent touches whose copy sits in the lead's
        attributes. Releasing on pause would let a second campaign overwrite
        them."""
        identity = LgmIdentity(email="dana@meridian.io")
        session.add(identity)
        await session.flush()
        campaign = OutreachCampaign(label="C", status="draft")
        session.add(campaign)
        await session.flush()

        t1 = await self._thread(session, identity=identity)
        t2 = await self._thread(session, identity=identity, name="Second")

        session.add(
            OutreachSequence(
                thread_id=t1.id, campaign_id=campaign.id,
                lgm_identity_id=identity.id, status="paused",
            )
        )
        await session.flush()
        session.add(
            OutreachSequence(
                thread_id=t2.id, campaign_id=campaign.id,
                lgm_identity_id=identity.id, status="pending_approval",
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()


@requires_db
class TestTheLockHoldsUnderGenuineConcurrency:
    """Two engines, two sessions, two real commits.

    A sequential test cannot distinguish an index from an application check.
    This one can: both coroutines read an empty table, both decide to insert,
    and exactly one commit survives.
    """

    async def test_two_concurrent_promotions_of_one_contact(self, session):
        identity = LgmIdentity(email="race@meridian.io")
        session.add(identity)
        campaign = OutreachCampaign(label="Race", status="draft")
        session.add_all([identity, campaign])
        await session.flush()

        helper = TestTheEnrolmentLockIsAnIndexNotACheck()
        t1 = await helper._thread(session, identity=identity, name="A")
        t2 = await helper._thread(session, identity=identity, name="B")
        await session.commit()

        ids = (identity.id, campaign.id, t1.id, t2.id)
        barrier = asyncio.Barrier(2)

        async def enrol(thread_id):
            engine = create_async_engine(TEST_DB)
            maker = async_sessionmaker(engine, expire_on_commit=False)
            try:
                async with maker() as s:
                    # Both read the same empty state before either writes —
                    # this is the window an application-level check loses in.
                    existing = (
                        await s.execute(
                            select(OutreachSequence).where(
                                OutreachSequence.lgm_identity_id == ids[0],
                                OutreachSequence.status == "pending_approval",
                            )
                        )
                    ).scalars().all()
                    assert existing == [], "the race window did not open"

                    await barrier.wait()
                    s.add(
                        OutreachSequence(
                            thread_id=thread_id, campaign_id=ids[1],
                            lgm_identity_id=ids[0], status="pending_approval",
                        )
                    )
                    try:
                        await s.commit()
                        return "committed"
                    except IntegrityError as exc:
                        assert "one_active_sequence_per_lgm_identity" in str(exc.orig)
                        return "rejected"
            finally:
                await engine.dispose()

        results = await asyncio.gather(enrol(t1.id), enrol(t2.id))

        assert sorted(results) == ["committed", "rejected"], (
            f"expected exactly one winner, got {results} — the index is not "
            "enforcing the lock"
        )

        rows = list(
            (
                await session.execute(
                    select(OutreachSequence).where(
                        OutreachSequence.lgm_identity_id == identity.id
                    )
                )
            ).scalars()
        )
        assert len(rows) == 1
        await session.execute(
            OutreachSequence.__table__.delete().where(
                OutreachSequence.lgm_identity_id == identity.id
            )
        )
        await session.commit()


def shape(**over) -> CadenceShape:
    base = dict(
        key="standard_6_15",
        label="Standard 6/15",
        lgm_campaign_id="lgm-1",
        touch_count=6,
        span_days=15,
        attribute_map={str(i): f"custom_attribute_{i}" for i in range(1, 7)},
        attributes_used=6,
        verified_at=datetime.now(UTC),
        verified_by="bertie",
        lgm_status="active",
        # LGM enrols by audience membership; a shape without one cannot send.
        lgm_audience_name="Gen360 · Tests",
        active=True,
    )
    return CadenceShape(**{**base, **over})


class TestCadenceDriftBlocksEnrolment:
    def test_a_clean_registration_enrols(self):
        assert may_enrol(shape())

    def test_a_campaign_changed_after_verification_blocks(self):
        """The dangerous case, and a silent one: a reordered step means the
        copy lands in a different message. Nothing errors, and the right person
        receives a real message saying the wrong thing."""
        blocked = shape(
            verified_at=datetime.now(UTC) - timedelta(days=2),
            lgm_updated_at=datetime.now(UTC) - timedelta(days=1),
        )
        reasons = [b.reason for b in check_enrolment(blocked)]
        assert "changed_in_lgm" in reasons

    def test_a_change_before_verification_does_not_block(self):
        ok = shape(
            verified_at=datetime.now(UTC),
            lgm_updated_at=datetime.now(UTC) - timedelta(days=5),
        )
        assert may_enrol(ok)

    def test_a_never_verified_shape_blocks(self):
        reasons = [b.reason for b in check_enrolment(shape(verified_at=None, verified_by=None))]
        assert "never_verified" in reasons

    def test_verification_expires_on_the_backstop(self):
        """A poll that has been quietly failing looks exactly like a campaign
        nobody edited."""
        old = shape(verified_at=datetime.now(UTC) - timedelta(days=VERIFICATION_BACKSTOP_DAYS + 1))
        assert "stale_verification" in [b.reason for b in check_enrolment(old)]


class TestACampaignDeletedInLgm:
    """A registration is a copy of something somebody else owns.

    Found live: a campaign was registered, then deleted in LGM. The row here
    still said verified, two steps, audience named — and pre-flight reported
    the whole campaign ready to execute. Nothing stored could have known.
    Executing would have written people and their approved copy into the
    audience of a campaign that no longer exists.
    """

    def test_a_missing_campaign_blocks_enrolment(self):
        assert not may_enrol(shape(lgm_status="missing"))

    def test_and_says_what_to_do_about_it(self):
        [block] = [b for b in check_enrolment(shape(lgm_status="missing")) if b.blocking]
        assert block.reason == "missing_in_lgm"
        assert "no longer exists" in block.detail
        assert block.blocking, "a warning here would let approved copy go nowhere"


class TestTheFirstLaunchIsNotADeadlock:
    """A campaign nobody has launched still takes its people.

    Found against a live account. LGM refuses to launch a campaign whose
    audience is empty; a campaign runs over an audience, and writing a lead
    into that audience *is* enrolling them. So the write is what makes the
    launch possible — and blocking it until the campaign had launched left both
    ends waiting on the other, with an error message telling the rep to go and
    do the thing they could not do.
    """

    def test_a_never_launched_campaign_still_accepts_its_people(self):
        assert may_enrol(shape(lgm_status="ready"))

    def test_and_says_plainly_that_nothing_sends_yet(self):
        [warning] = enrolment_warnings(shape(lgm_status="ready"))
        assert warning.reason == "never_launched"
        assert not warning.blocking
        assert "nothing sends until it does" in warning.detail.lower()

    def test_a_paused_campaign_is_still_refused(self):
        """Different case: it has been launched, and a pause is a decision."""
        assert not may_enrol(shape(lgm_status="paused"))

    def test_an_archived_campaign_is_still_refused(self):
        assert not may_enrol(shape(lgm_status="archived"))

    def test_a_real_blocker_is_not_softened_by_the_warning(self):
        """Never launched *and* never verified is still a refusal."""
        both = shape(lgm_status="ready", verified_at=None, verified_by=None)
        assert not may_enrol(both)
        assert "never_verified" in [b.reason for b in check_enrolment(both) if b.blocking]

    def test_a_paused_lgm_campaign_blocks(self):
        assert "lgm_status" in [b.reason for b in check_enrolment(shape(lgm_status="paused"))]

    def test_an_archived_lgm_campaign_blocks(self):
        assert "lgm_status" in [b.reason for b in check_enrolment(shape(lgm_status="archived"))]

    def test_an_inactive_shape_blocks(self):
        assert "inactive" in [b.reason for b in check_enrolment(shape(active=False))]

    def test_an_incompletely_mapped_shape_blocks(self):
        """Unmapped steps would send whatever LGM already holds."""
        partial = shape(attribute_map={"1": "custom_attribute_1"}, attributes_used=1)
        assert "incomplete_map" in [b.reason for b in check_enrolment(partial)]

    def test_every_block_is_reported_not_just_the_first(self):
        bad = shape(active=False, lgm_status="paused", verified_at=None, verified_by=None)
        assert len(check_enrolment(bad)) >= 3

    def test_a_block_explains_itself_in_words(self):
        blocked = shape(
            verified_at=datetime.now(UTC) - timedelta(days=2),
            lgm_updated_at=datetime.now(UTC),
        )
        detail = next(b for b in check_enrolment(blocked) if b.reason == "changed_in_lgm").detail
        assert "wrong step" in detail


class TestShapeSelectionIsDeterministic:
    def test_an_unverified_email_forces_linkedin_only(self):
        key, log = select_shape_key(
            SelectionInput(email_status="unverified", size_band="large", priority_band="high")
        )
        assert key == "linkedin_only_5_15"
        assert log["rule"] == "unverified_email"

    def test_size_band_beats_priority_band(self):
        key, _ = select_shape_key(
            SelectionInput(email_status="verified", size_band="large", priority_band="medium")
        )
        assert key == "enterprise_8_23"

    def test_a_small_company_gets_the_short_sequence(self):
        key, _ = select_shape_key(
            SelectionInput(email_status="verified", size_band="small", priority_band="low")
        )
        assert key == "startup_5_11"

    def test_the_default_applies_when_nothing_else_matches(self):
        """`mid` is a real band that deliberately maps to no shape of its own."""
        key, log = select_shape_key(
            SelectionInput(email_status="verified", size_band="mid", priority_band="high")
        )
        assert key == "standard_6_15"
        assert log["rule"] == "default"

    def test_an_unsized_account_still_gets_a_shape(self):
        """`unknown` is the absence of a headcount, and must not stall a
        promotion — it falls through to the default like any other band that
        maps to no shape."""
        key, log = select_shape_key(
            SelectionInput(email_status="verified", size_band="unknown", priority_band="high")
        )
        assert key == "standard_6_15"
        assert log["rule"] == "default"

    def test_the_log_records_the_fact_that_decided_it(self):
        """"Why did this account get the enterprise cadence?" has to be
        answerable from the row, months later."""
        _, log = select_shape_key(
            SelectionInput(email_status="verified", size_band="large", priority_band="low")
        )
        assert log["fact"] == {"size_band": "large"}

    def test_our_band_names_are_not_lgm_shape_names(self):
        """The shapes are registered in LGM and are not ours to rename.

        Mapping `large` onto `enterprise_8_23` across the gap keeps the two
        vocabularies uncoupled; naming both `enterprise` would tie them together
        by coincidence, and the day LGM renames a shape is the day that breaks.
        """
        from app.services import sizing

        assert "enterprise" not in sizing.BANDS
        assert "startup" not in sizing.BANDS

    def test_the_same_facts_always_pick_the_same_shape(self):
        facts = SelectionInput(email_status="verified", size_band="small", priority_band="high")
        assert select_shape_key(facts) == select_shape_key(facts)


class TestTimingIsNotOurs:
    def test_the_span_derived_rule_is_gone(self):
        """It computed a drafting rule from a number a rep typed.

        LGM exposes no step timing, so there was nothing behind the span but
        somebody's recollection of the campaign — and drafting then checked the
        model's invented day offsets against it. Two guesses agreeing is not a
        check. Gone rather than deprecated, so nothing calls it by habit.
        """
        from app.services import cadence

        assert not hasattr(cadence, "durable_from_step")
