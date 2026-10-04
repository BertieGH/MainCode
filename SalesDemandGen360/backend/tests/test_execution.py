"""Phase 10: pre-flight, the outbound interlock, freezing, and the stop paths.

The three conditions `docs/08` sets, plus the guard that matters more than any
of them: nothing reaches a recipient without a human approval row, enforced by
a trigger rather than by code that could be bypassed.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.account import Account, Contact
from app.models.campaign import CadenceShape, LgmIdentity, OutreachCampaign, OutreachSequence
from app.models.config import SalesRules, ServiceCatalog
from app.models.content import Touch
from app.models.execution import ExecutionRecord
from app.models.governance import Approval
from app.models.strategy import Strategy, StrategyThread
from app.schemas.draft import DraftSet, TouchDraft
from app.services import preflight
from app.services.drafting import store_arc
from app.services.execution import (
    ContentFrozenError,
    PreflightFailedError,
    assert_editable,
    check_interlock,
    execute,
    stop_campaign,
    stop_sequence,
)
from app.services.lgm import ATTRIBUTE_BUDGET, LgmError, StubLgmAdapter

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


def _arc(count: int = 6) -> DraftSet:
    days = [1, 3, 6, 8, 12, 15][:count]
    return DraftSet(
        touches=[
            TouchDraft(
                step_no=i + 1,
                day_offset=days[i],
                channel="email" if i % 2 else "linkedin_message",
                purpose=f"step {i + 1}",
                body=f"Body {i + 1}",
                signal_dependence="durable",
            )
            for i in range(count)
        ]
    )


@pytest.fixture
async def world(session):
    """A campaign with one approved, fully drafted, enrollable sequence."""
    account = Account(
        name="Meridian Cloud", domain="MERIDIANCLOUD.EXEC", status="researching"
    )
    service = ServiceCatalog(code=f"s{uuid.uuid4().hex[:6]}", name="QA", description="d")
    shape = CadenceShape(
        lgm_audience_name="Gen360 · Tests", key=f"shape_{uuid.uuid4().hex[:6]}", label="Standard",
        lgm_campaign_id="lgm-exec-1", touch_count=6, span_days=15,
        attribute_map={str(i): f"custom_attribute_{i}" for i in range(1, 7)},
        attributes_used=6, verified_at=datetime.now(UTC) - timedelta(days=2),
        verified_by="bertie", lgm_status="active", active=True,
    )
    session.add_all([account, service, shape])
    await session.flush()

    identity = LgmIdentity(email=f"dana-{uuid.uuid4().hex[:6]}@meridian.exec")
    session.add(identity)
    await session.flush()

    contact = Contact(
        account_id=account.id, full_name="Dana Reyes", email=identity.email,
        email_status="verified", lgm_identity_id=identity.id,
    )
    strategy = Strategy(account_id=account.id, version=1)
    campaign = OutreachCampaign(
        label="Exec test", status="pending_approval", cadence_shape_id=shape.id
    )
    session.add_all([contact, strategy, campaign])
    await session.flush()

    thread = StrategyThread(
        strategy_id=strategy.id, contact_id=contact.id, service_id=service.id,
        weight=60, rank=1, thread_status="active_primary",
        problem_hypothesis="h", trigger_summary="t",
        trigger_signal_ids=[str(uuid.uuid4())], positioning="p",
        channel_sequence=["email"], cta="c",
    )
    session.add(thread)
    await session.flush()

    sequence = OutreachSequence(
        thread_id=thread.id, campaign_id=campaign.id, cadence_shape_id=shape.id,
        lgm_identity_id=identity.id, status="draft",
    )
    session.add(sequence)
    await session.flush()

    await store_arc(session, sequence=sequence, draft_set=_arc(), shape=shape)
    sequence.status = "approved"
    session.add(
        Approval(
            subject_type="outreach_sequence", subject_id=sequence.id,
            decision="approve", reviewer_id="bertie", review_depth="individual",
        )
    )
    await session.flush()

    return {
        "account": account, "contact": contact, "campaign": campaign,
        "sequence": sequence, "shape": shape, "thread": thread, "identity": identity,
    }


async def _disqualify(session, account) -> None:
    """A disqualified account must carry a reason — the CHECK insists, and it
    is right to: a disqualification nobody can explain is one nobody can undo."""
    account.status = "disqualified"
    account.disqualified_reason = "competitor"
    await session.flush()


async def _no_go(session, domain: str):
    rules = (
        await session.execute(select(SalesRules).where(SalesRules.is_active.is_(True)))
    ).scalar_one_or_none()
    if rules is None:
        rules = SalesRules(
            version=1, priority_threshold=65, persona_weight_threshold=30,
            max_concurrent_threads=2, thread_start_offset_days=3,
            signal_ttl_days={}, sample_rate=0.4, is_active=True,
        )
        session.add(rules)
    rules.no_go = {"domains": [domain]}
    await session.flush()


@pytest.fixture
async def api():
    from httpx import ASGITransport, AsyncClient

    from app.api.deps import get_session
    from app.main import create_app

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    maker = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app()

    async def _session():
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.maker = maker  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


@requires_db
class TestTheWayOutOfACampaignThatCannotRun:
    """Stopping is for a campaign in flight. One that never sent has nothing
    to stop, and the Execute tab offered only Stop — a dead end with no exit.

    The approval payload now carries whether deleting is allowed, so the button
    can say so before it is pressed rather than after a refusal.
    """

    async def _campaign(self, api, status: str) -> str:
        """A committed campaign the API's own session can see."""
        async with api.maker() as s:
            campaign = OutreachCampaign(label=f"Deletable {uuid.uuid4().hex[:6]}", status=status)
            s.add(campaign)
            await s.commit()
            return str(campaign.id)

    async def test_a_draft_campaign_says_it_can_be_deleted(self, api):
        campaign_id = await self._campaign(api, "draft")
        body = (await api.get(f"/api/campaigns/{campaign_id}/approval")).json()
        assert body["campaign_status"] == "draft"
        assert body["deletable"] is True

    async def test_an_executing_campaign_does_not(self, api):
        """It is the record of what was sent and to whom."""
        campaign_id = await self._campaign(api, "executing")
        body = (await api.get(f"/api/campaigns/{campaign_id}/approval")).json()
        assert body["campaign_status"] == "executing"
        assert body["deletable"] is False

    async def test_a_cancelled_campaign_can_still_go(self, api):
        """Nothing was sent, so there is no record to protect."""
        campaign_id = await self._campaign(api, "cancelled")
        body = (await api.get(f"/api/campaigns/{campaign_id}/approval")).json()
        assert body["deletable"] is True


class TestEveryPreflightItemBlocks:
    async def test_a_clean_campaign_passes_every_check(self, session, world):
        result = await preflight.run(session, world["campaign"].id)
        assert result.passed, result.summary()
        assert len(result.checks) == 10  # threads, strategy, approved, cadence, budget, lock, screened, dnc, one_cadence, content

    async def test_an_unapproved_thread_blocks(self, session, world):
        await session.execute(
            Approval.__table__.delete().where(Approval.subject_id == world["sequence"].id)
        )
        await session.flush()

        result = await preflight.run(session, world["campaign"].id)
        failed = {c.key for c in result.failures}
        assert "approved" in failed
        assert not result.passed

    async def test_a_changed_in_lgm_cadence_blocks(self, session, world):
        world["shape"].lgm_updated_at = datetime.now(UTC)
        await session.flush()

        result = await preflight.run(session, world["campaign"].id)
        cadence = next(c for c in result.checks if c.key == "cadence")
        assert not cadence.passed
        assert "changed_in_lgm" in cadence.subjects

    async def test_an_over_budget_arc_blocks(self, session, world):
        """LGM refuses the write, which would fail the campaign mid-enrolment."""
        # The cap is twenty, so twelve is comfortably inside it. Pushed over
        # by giving the sequence more steps than any real cadence would have —
        # the check is about the ceiling, not about how it is reached.
        touches = list(
            (
                await session.execute(
                    select(Touch).where(Touch.sequence_id == world["sequence"].id)
                )
            ).scalars()
        )
        for touch in touches:
            touch.subject_source = "custom_attribute"
        for extra in range(len(touches) + 1, 12):
            session.add(
                Touch(
                    sequence_id=world["sequence"].id, step_no=extra, channel="email",
                    purpose="filler", subject_source="custom_attribute",
                )
            )
        # 11 bodies + 11 subjects = 22, over the cap of 20.
        await session.flush()

        result = await preflight.run(session, world["campaign"].id)
        attrs = next(c for c in result.checks if c.key == "attributes")
        assert not attrs.passed
        assert str(ATTRIBUTE_BUDGET) in attrs.detail

    async def test_a_contact_held_by_another_campaign_blocks(self, session, world):
        """Two *live* sequences for one identity are unrepresentable — the
        partial unique index sees to that. The state this check exists for is a
        not-yet-live sequence here while another campaign already holds the
        lock: without the check, execute() would move it to 'executing' and the
        index would reject it mid-run, leaving the campaign half-enrolled."""
        world["sequence"].status = "draft"
        await session.flush()

        other = OutreachCampaign(label="Other", status="executing")
        session.add(other)
        await session.flush()
        session.add(
            OutreachSequence(
                thread_id=world["thread"].id, campaign_id=other.id,
                lgm_identity_id=world["identity"].id, status="executing",
            )
        )
        await session.flush()

        result = await preflight.run(session, world["campaign"].id)
        lock = next(c for c in result.checks if c.key == "enrolment_lock")
        assert not lock.passed
        assert "another campaign" in lock.detail

    async def test_a_no_go_domain_blocks(self, session, world):
        await _no_go(session, "MERIDIANCLOUD.EXEC")
        result = await preflight.run(session, world["campaign"].id)
        screened = next(c for c in result.checks if c.key == "screened")
        assert not screened.passed
        assert "no-go" in screened.detail

    async def test_a_disqualified_account_blocks(self, session, world):
        await _disqualify(session, world["account"])

        result = await preflight.run(session, world["campaign"].id)
        assert "screened" in {c.key for c in result.failures}

    async def test_an_unmapped_step_blocks(self, session, world):
        touch = (
            await session.execute(
                select(Touch).where(Touch.sequence_id == world["sequence"].id).limit(1)
            )
        ).scalar_one()
        touch.lgm_attribute = None
        await session.flush()

        result = await preflight.run(session, world["campaign"].id)
        assert "content_ready" in {c.key for c in result.failures}

    async def test_an_empty_campaign_blocks(self, session):
        empty = OutreachCampaign(label="Empty", status="draft")
        session.add(empty)
        await session.flush()

        result = await preflight.run(session, empty.id)
        assert not result.passed
        assert "has_threads" in {c.key for c in result.failures}

    async def test_every_check_runs_even_when_one_fails(self, session, world):
        """A rep fixing a campaign needs the whole list, not one problem at a
        time across four round trips."""
        await _disqualify(session, world["account"])
        world["shape"].lgm_updated_at = datetime.now(UTC)
        await session.execute(
            Approval.__table__.delete().where(Approval.subject_id == world["sequence"].id)
        )
        await session.flush()

        result = await preflight.run(session, world["campaign"].id)
        assert len(result.failures) >= 3
        assert len(result.checks) == 10  # threads, strategy, approved, cadence, budget, lock, screened, dnc, one_cadence, content

    async def test_a_failing_check_says_what_to_do(self, session, world):
        await session.execute(
            Approval.__table__.delete().where(Approval.subject_id == world["sequence"].id)
        )
        await session.flush()

        result = await preflight.run(session, world["campaign"].id)
        approved = next(c for c in result.checks if c.key == "approved")
        assert "1 of 1" in approved.detail
        assert approved.subjects == [str(world["sequence"].id)]


@requires_db
class TestNothingSendsWithoutApproval:
    async def test_the_database_refuses_a_sent_record_with_no_approval(self, session, world):
        """The interlock, in a trigger rather than in code. If a future path can
        reach a send by forgetting a check, nothing upstream matters."""
        await session.execute(
            Approval.__table__.delete().where(Approval.subject_id == world["sequence"].id)
        )
        await session.flush()

        session.add(
            ExecutionRecord(
                sequence_id=world["sequence"].id, status="sent",
                sent_at=datetime.now(UTC), action="enrol",
            )
        )
        with pytest.raises((IntegrityError, ProgrammingError), match="no approval"):
            await session.flush()

    async def test_a_skip_may_be_recorded_without_an_approval(self, session, world):
        """A skip records that we did *not* send. Requiring approval for it
        would leave the system unable to record correctly refusing."""
        await session.execute(
            Approval.__table__.delete().where(Approval.subject_id == world["sequence"].id)
        )
        await session.flush()

        session.add(
            ExecutionRecord(
                sequence_id=world["sequence"].id, status="skipped",
                skip_reason="no_go_list", action="enrol",
            )
        )
        await session.flush()

    async def test_an_approved_sequence_may_record_a_send(self, session, world):
        session.add(
            ExecutionRecord(
                sequence_id=world["sequence"].id, status="sent",
                sent_at=datetime.now(UTC), action="enrol",
            )
        )
        await session.flush()

    async def test_a_rejection_is_not_an_approval(self, session, world):
        await session.execute(
            Approval.__table__.delete().where(Approval.subject_id == world["sequence"].id)
        )
        session.add(
            Approval(
                subject_type="outreach_sequence", subject_id=world["sequence"].id,
                decision="reject", reject_reason="poor_message", reviewer_id="bertie",
            )
        )
        await session.flush()

        session.add(
            ExecutionRecord(
                sequence_id=world["sequence"].id, status="sent",
                sent_at=datetime.now(UTC), action="enrol",
            )
        )
        with pytest.raises((IntegrityError, ProgrammingError), match="no approval"):
            await session.flush()


@requires_db
class TestExecution:
    async def test_execute_enrols_and_writes_every_attribute(self, session, world):
        lgm = StubLgmAdapter()
        outcome = await execute(session, campaign_id=world["campaign"].id, lgm=lgm)

        assert outcome.enrolled == [world["sequence"].id]
        assert world["sequence"].status == "executing"
        assert world["sequence"].lgm_lead_id
        assert world["campaign"].status == "executing"

        lead = next(iter(lgm.leads.values()))
        assert len(lead.attributes) == 6, "one attribute per touch"

    async def test_every_touch_shares_one_written_timestamp(self, session, world):
        await execute(session, campaign_id=world["campaign"].id, lgm=StubLgmAdapter())
        touches = list(
            (
                await session.execute(
                    select(Touch).where(Touch.sequence_id == world["sequence"].id)
                )
            ).scalars()
        )
        assert all(t.content_sync_status == "written" for t in touches)
        assert len({t.content_written_at for t in touches}) == 1

    async def test_execute_refuses_when_preflight_fails(self, session, world):
        await _disqualify(session, world["account"])

        with pytest.raises(PreflightFailedError, match="disqualified"):
            await execute(session, campaign_id=world["campaign"].id, lgm=StubLgmAdapter())

        assert world["sequence"].status == "approved", "nothing was enrolled"

    async def test_preflight_is_rechecked_inside_execute(self, session, world):
        """The checklist the rep looked at may be minutes old."""
        clean = await preflight.run(session, world["campaign"].id)
        assert clean.passed

        await _disqualify(session, world["account"])

        with pytest.raises(PreflightFailedError):
            await execute(session, campaign_id=world["campaign"].id, lgm=StubLgmAdapter())

    async def test_a_provider_failure_costs_one_sequence_not_the_campaign(self, session, world):
        lgm = StubLgmAdapter(available=False)
        with pytest.raises(LgmError):
            await lgm.upsert_lead(email="x@y.z", linkedin_url=None, attributes={})

        outcome = await execute(session, campaign_id=world["campaign"].id, lgm=lgm)
        assert outcome.enrolled == []
        assert str(world["sequence"].id) in outcome.failed
        assert world["campaign"].status == "pending_approval", "no partial start"

    async def test_a_failed_enrolment_is_recorded(self, session, world):
        await execute(
            session, campaign_id=world["campaign"].id, lgm=StubLgmAdapter(available=False)
        )
        record = (
            await session.execute(
                select(ExecutionRecord).where(
                    ExecutionRecord.sequence_id == world["sequence"].id
                )
            )
        ).scalar_one()
        assert record.status == "failed"
        assert record.error


@requires_db
class TestTheSendTimeInterlock:
    async def test_a_clean_sequence_proceeds(self, session, world):
        verdict = await check_interlock(session, world["sequence"], channel="email")
        assert verdict.proceed

    async def test_a_disqualified_account_stops_the_touch(self, session, world):
        await _disqualify(session, world["account"])
        verdict = await check_interlock(session, world["sequence"])
        assert not verdict.proceed
        assert verdict.reason == "account_disqualified"

    async def test_a_no_go_domain_stops_the_touch(self, session, world):
        """The one deliberate exception to 'nothing flows backward': a campaign
        is decoupled from its queue, so a company added to no-go today would
        otherwise keep receiving touches."""
        await _no_go(session, "MERIDIANCLOUD.EXEC")
        verdict = await check_interlock(session, world["sequence"])
        assert verdict.reason == "no_go_list"

    async def test_an_unverified_email_stops_only_email_touches(self, session, world):
        world["contact"].email_status = "unverified"
        await session.flush()

        assert (await check_interlock(session, world["sequence"], channel="email")).reason == (
            "contact_unverified"
        )
        assert (
            await check_interlock(session, world["sequence"], channel="linkedin_message")
        ).proceed

    async def test_a_stopped_sequence_stops(self, session, world):
        world["sequence"].status = "stopped"
        await session.flush()
        assert not (await check_interlock(session, world["sequence"])).proceed

    async def test_the_verdict_records_what_it_saw(self, session, world):
        """So a skip can be explained months later without re-deriving state."""
        verdict = await check_interlock(session, world["sequence"])
        assert verdict.snapshot["account_status"] == "researching"
        assert "checked_at" in verdict.snapshot


@requires_db
class TestContentIsFrozenAfterEnrolment:
    async def test_editing_after_enrolment_is_refused(self, session, world):
        await execute(session, campaign_id=world["campaign"].id, lgm=StubLgmAdapter())

        with pytest.raises(ContentFrozenError, match="frozen"):
            await assert_editable(session, world["sequence"].id)

    async def test_editing_before_enrolment_is_allowed(self, session, world):
        await assert_editable(session, world["sequence"].id)

    async def test_written_content_freezes_even_if_status_lags(self, session, world):
        """Belt and braces: the lead holds the copy the moment the attributes
        are written, whatever our own status column says."""
        for touch in (
            await session.execute(
                select(Touch).where(Touch.sequence_id == world["sequence"].id)
            )
        ).scalars():
            touch.content_sync_status = "written"
            touch.content_written_at = datetime.now(UTC)
        await session.flush()

        with pytest.raises(ContentFrozenError, match="already been written"):
            await assert_editable(session, world["sequence"].id)


@requires_db
class TestStopPaths:
    async def test_stop_sequence_halts_pending_touches(self, session, world):
        await execute(session, campaign_id=world["campaign"].id, lgm=StubLgmAdapter())
        lgm = StubLgmAdapter()

        stopped = await stop_sequence(
            session, sequence_id=world["sequence"].id, lgm=lgm, reason="reply_received"
        )

        assert stopped.status == "stopped"
        touches = list(
            (
                await session.execute(
                    select(Touch).where(Touch.sequence_id == world["sequence"].id)
                )
            ).scalars()
        )
        assert all(t.status == "skipped" for t in touches)
        assert all(t.stop_reason == "reply_received" for t in touches)

    async def test_a_stop_is_recorded_even_when_the_provider_fails(self, session, world):
        """A stop that silently did not happen is worse than one that errored:
        the sequence keeps sending while the UI shows it stopped."""
        await execute(session, campaign_id=world["campaign"].id, lgm=StubLgmAdapter())

        stopped = await stop_sequence(
            session, sequence_id=world["sequence"].id, lgm=StubLgmAdapter(available=False)
        )
        assert stopped.status == "stopped", "local state must move regardless"

        records = list(
            (
                await session.execute(
                    select(ExecutionRecord).where(
                        ExecutionRecord.sequence_id == world["sequence"].id,
                        ExecutionRecord.status == "failed",
                    )
                )
            ).scalars()
        )
        assert records and records[-1].error

    async def test_stopping_releases_the_enrolment_lock(self, session, world):
        """A stopped sequence is terminal, so the contact can be enrolled
        elsewhere."""
        await execute(session, campaign_id=world["campaign"].id, lgm=StubLgmAdapter())
        await stop_sequence(session, sequence_id=world["sequence"].id, lgm=StubLgmAdapter())

        session.add(
            OutreachSequence(
                thread_id=world["thread"].id, campaign_id=world["campaign"].id,
                lgm_identity_id=world["identity"].id, status="pending_approval",
            )
        )
        await session.flush()  # must not raise

    async def test_stop_campaign_stops_every_live_sequence(self, session, world):
        await execute(session, campaign_id=world["campaign"].id, lgm=StubLgmAdapter())
        lgm = StubLgmAdapter()

        count = await stop_campaign(session, campaign_id=world["campaign"].id, lgm=lgm)

        assert count == 1
        assert world["campaign"].status == "cancelled"
        assert world["sequence"].status == "stopped"
        assert world["shape"].lgm_campaign_id in lgm.stopped_campaigns


class TestTheAdapterSurfaceCannotEditContent:
    def test_there_is_no_step_editor_and_no_post_enrolment_write(self):
        """`docs/02`: Gen360 never authors a cadence, and content is frozen at
        enrolment. Methods that do not exist cannot be called by mistake."""
        from app.services.lgm import LgmAdapter

        surface = {m for m in dir(LgmAdapter) if not m.startswith("_")}
        assert surface == {
            "campaign_meta", "upsert_lead", "enrol", "stop_lead", "stop_campaign"
        }

    @pytest.mark.parametrize(
        "forbidden", ["edit_step", "update_attributes", "add_step", "reorder_steps"]
    )
    def test_named_editors_are_absent(self, forbidden):
        from app.services.lgm import LgmAdapter

        assert not hasattr(LgmAdapter, forbidden)

    async def test_the_stub_refuses_an_over_budget_write(self):
        """Faithful to LGM, which refuses rather than truncates.

        The stub used to discard the overflow in silence because the API
        documentation said LGM did. A live account says otherwise: attributes
        11, 15 and 20 all store, and a 21st is refused. A stub that loses a
        touch where the real thing refuses would hide the failure in tests and
        produce it in production.
        """
        lgm = StubLgmAdapter()
        # There is no 21st attribute to exceed the budget *with*: going over
        # means naming one LGM does not have, and that is what it refuses.
        with pytest.raises(LgmError, match="outside the 20 attributes"):
            await lgm.upsert_lead(
                email="a@b.c", linkedin_url=None,
                attributes={f"custom_attribute_{i}": "x" for i in range(1, 25)},
            )

    async def test_the_stub_accepts_a_full_twenty(self):
        lgm = StubLgmAdapter()
        lead = await lgm.upsert_lead(
            email="a@b.c", linkedin_url=None,
            attributes={f"custom_attribute_{i}": "x" for i in range(1, 21)},
        )
        assert len(lead.attributes) == ATTRIBUTE_BUDGET
