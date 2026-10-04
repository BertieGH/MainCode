"""Deleting a campaign that has never reached LGM.

Same rule as a queue, one layer along — but the line is *not* the status badge.
A campaign can sit at `pending_approval` with sequences already written to LGM
leads, and it can sit at `draft` having committed to nothing. What decides it is
whether anything left this system, which is three separate facts:

* the campaign's own status,
* whether any sequence carries an LGM id,
* whether any execution record exists.

The dangerous half is not the refusal — it is the *success* path. A campaign
deleted without its sequences leaves rows at `pending_approval`, and the
enrolment lock is a partial unique index over exactly those statuses. Every
affected contact is then silently barred from every future campaign, with
nothing on any screen to say why. So the tests below assert what gets taken
down, not only what gets refused.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database import get_session
from app.models.account import Account, Contact
from app.models.campaign import (
    CampaignQueue,
    LgmIdentity,
    OutreachCampaign,
    OutreachSequence,
)
from app.models.content import Touch
from app.models.governance import Approval, ApprovalSample
from app.models.strategy import Strategy, StrategyThread

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.getenv("TEST_DATABASE_URL"),
        reason="TEST_DATABASE_URL not set — this exercises real cascades",
    ),
]


@pytest.fixture
async def api(app):
    """A client bound to the test database rather than the stub session."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _session():
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        c.maker = maker  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


async def _campaign_with_sequence(
    maker, *, status: str = "draft", lgm_lead_id: str | None = None
):
    """A campaign with one sequence, one touch, and a source queue.

    Built through the ORM rather than through the API because the states worth
    testing — enrolled, executed — are ones the API deliberately makes hard to
    reach by accident.
    """
    async with maker() as s:
        account = Account(name="Northwind", domain="northwind.example")
        s.add(account)
        await s.flush()

        contact = Contact(account_id=account.id, full_name="Dana Reyes", seniority="vp")
        s.add(contact)

        campaign = OutreachCampaign(label="Sept push", status=status)
        s.add(campaign)
        await s.flush()

        queue = CampaignQueue(
            label="Sept queue",
            status="locked",
            locked_at=datetime.now(UTC),
            promoted_to_campaign_id=campaign.id,
        )
        s.add(queue)

        strategy = Strategy(account_id=account.id, version=1)
        s.add(strategy)
        await s.flush()

        # An identity is a *person* in LGM, not a contact row — it carries
        # the identifiers a lead is matched on, and the check constraint
        # requires at least one of them.
        identity = LgmIdentity(linkedin_slug=f"dana-reyes-{uuid.uuid4().hex[:8]}")
        s.add(identity)
        await s.flush()
        contact.lgm_identity_id = identity.id

        thread = StrategyThread(
            strategy_id=strategy.id,
            contact_id=contact.id,
            service_id=await _a_service(s),
            weight=60,
            rank=1,
            thread_status="active_primary",
            problem_hypothesis="Release quality is slipping.",
            trigger_summary="Six QA roles opened.",
            # A thread must cite a trigger — the table refuses an empty list,
            # because a thread with no trigger is a pitch with no reason for now.
            trigger_signal_ids=[str(uuid.uuid4())],
            positioning="Managed QA pods.",
            channel_sequence=["linkedin_connect"],
            cta="Worth 20 minutes?",
        )
        s.add(thread)
        await s.flush()

        sequence = OutreachSequence(
            thread_id=thread.id,
            campaign_id=campaign.id,
            lgm_identity_id=identity.id,
            status="pending_approval",
            lgm_lead_id=lgm_lead_id,
        )
        s.add(sequence)
        await s.flush()

        s.add(
            Touch(
                sequence_id=sequence.id,
                step_no=1,
                day_offset=0,
                channel="linkedin_connect",
                purpose="open",
            )
        )
        s.add(
            ApprovalSample(
                campaign_id=campaign.id,
                sequence_ids=[str(sequence.id)],
                stratum_size=1,
                sample_size=1,
            )
        )
        s.add(
            Approval(
                subject_type="outreach_sequence",
                subject_id=sequence.id,
                decision="approve",
                reviewer_id="rep@cgvak.example",
            )
        )
        await s.commit()
        return campaign.id, sequence.id, queue.id, identity.id


async def _a_service(session) -> uuid.UUID:
    from app.models.config import ServiceCatalog

    row = ServiceCatalog(
        code=f"svc-{uuid.uuid4().hex[:6]}",
        name="QA engineering",
        description="Testing",
    )
    session.add(row)
    await session.flush()
    return row.id


class TestWhatIsRefused:
    async def test_an_executing_campaign_cannot_be_deleted(self, api):
        campaign_id, *_ = await _campaign_with_sequence(api.maker, status="executing")
        r = await api.delete(f"/api/campaigns/{campaign_id}")
        assert r.status_code == 409
        assert "record of what was sent" in r.json()["detail"]

    async def test_an_enrolled_sequence_blocks_deletion(self, api):
        """Deleting our row does not delete theirs.

        The status here is `draft` — the badge says safe and the LGM id says
        otherwise. This is exactly the case a status-only check waves through.
        """
        campaign_id, *_ = await _campaign_with_sequence(
            api.maker, status="draft", lgm_lead_id="lgm-lead-9931"
        )
        r = await api.delete(f"/api/campaigns/{campaign_id}")
        assert r.status_code == 409
        assert "La Growth Machine" in r.json()["detail"]

    async def test_an_unknown_campaign_is_404_not_204(self, api):
        r = await api.delete(f"/api/campaigns/{uuid.uuid4()}")
        assert r.status_code == 404


class TestWhatIsTakenDownWithIt:
    async def test_the_sequences_go_too_so_the_enrolment_lock_releases(self, api):
        """The failure mode that has no symptom.

        A sequence orphaned at `pending_approval` sits inside the partial
        unique index on `lgm_identity_id`, so the contact is barred from every
        later campaign — and nothing anywhere says a deleted campaign is the
        reason.
        """
        campaign_id, sequence_id, _, identity_id = await _campaign_with_sequence(
            api.maker
        )
        assert (await api.delete(f"/api/campaigns/{campaign_id}")).status_code == 204

        async with api.maker() as s:
            assert await s.get(OutreachSequence, sequence_id) is None
            # The identity itself survives — it is the person, not the campaign.
            assert await s.get(LgmIdentity, identity_id) is not None
            blocking = (
                await s.execute(
                    select(OutreachSequence).where(
                        OutreachSequence.lgm_identity_id == identity_id
                    )
                )
            ).scalars().all()
            assert blocking == [], "the contact is still locked out"

    async def test_touches_and_approvals_do_not_survive_the_sequence(self, api):
        campaign_id, sequence_id, _, _ = await _campaign_with_sequence(api.maker)
        assert (await api.delete(f"/api/campaigns/{campaign_id}")).status_code == 204

        async with api.maker() as s:
            touches = (
                await s.execute(
                    select(Touch).where(Touch.sequence_id == sequence_id)
                )
            ).scalars().all()
            assert touches == []
            approvals = (
                await s.execute(
                    select(Approval).where(Approval.subject_id == sequence_id)
                )
            ).scalars().all()
            assert approvals == []
            samples = (
                await s.execute(
                    select(ApprovalSample).where(
                        ApprovalSample.campaign_id == campaign_id
                    )
                )
            ).scalars().all()
            assert samples == []

    async def test_the_source_queue_is_unlocked_and_becomes_editable_again(self, api):
        """The lock protects an answer, and the question is now gone.

        "Which version of this queue fed campaign 2?" only needs answering
        while campaign 2 exists. Deletion is permitted only when nothing was
        ever sent, so the unlock rides on the same precondition rather than
        being a separate loosening of the rule.
        """
        campaign_id, _, queue_id, _ = await _campaign_with_sequence(api.maker)
        assert (await api.delete(f"/api/campaigns/{campaign_id}")).status_code == 204

        async with api.maker() as s:
            queue = await s.get(CampaignQueue, queue_id)
            assert queue is not None
            assert queue.status == "draft"
            # Both move or the `locked_at_consistent` check rejects the row.
            assert queue.locked_at is None
            assert queue.promoted_to_campaign_id is None

    async def test_an_unlocked_queue_can_then_be_deleted(self, api):
        """The point of the unlock: the queue is usable again, not just tidy."""
        campaign_id, _, queue_id, _ = await _campaign_with_sequence(api.maker)
        assert (await api.delete(f"/api/campaigns/{campaign_id}")).status_code == 204
        assert (await api.delete(f"/api/queues/{queue_id}")).status_code == 204
        async with api.maker() as s:
            assert await s.get(CampaignQueue, queue_id) is None

    async def test_a_queue_still_feeding_another_campaign_stays_locked(self, api):
        """That campaign's question is still live."""
        from app.models.campaign import OutreachCampaignSource

        campaign_id, _, queue_id, _ = await _campaign_with_sequence(api.maker)
        async with api.maker() as s:
            other = OutreachCampaign(label="Other push", status="executing")
            s.add(other)
            await s.flush()
            s.add(OutreachCampaignSource(campaign_id=other.id, queue_id=queue_id))
            await s.commit()

        assert (await api.delete(f"/api/campaigns/{campaign_id}")).status_code == 204
        async with api.maker() as s:
            queue = await s.get(CampaignQueue, queue_id)
            assert queue.status == "locked"
            assert queue.locked_at is not None

    async def test_the_campaign_row_is_gone(self, api):
        campaign_id, *_ = await _campaign_with_sequence(api.maker)
        assert (await api.delete(f"/api/campaigns/{campaign_id}")).status_code == 204
        async with api.maker() as s:
            assert await s.get(OutreachCampaign, campaign_id) is None
