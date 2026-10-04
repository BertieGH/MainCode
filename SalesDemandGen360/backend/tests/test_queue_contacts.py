"""Campaigns built from people: queueing contacts, promoting them, and the strategy gate.

Enrichment and research are company-wide; outreach is to people. A queue holds
the contacts a rep chose — whole companies can still be queued alongside — and
promotion gives each person a sequence whether or not a strategy exists yet.
The strategy is required before execution, and pre-flight says so by name.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.account import Account, AccountList, AccountListMember, Contact
from app.models.campaign import (
    CadenceShape,
    CampaignQueue,
    CampaignQueueContact,
    DeferredEnrolment,
    LgmIdentity,
    OutreachCampaign,
    OutreachSequence,
)
from app.models.config import ServiceCatalog
from app.models.strategy import Strategy, StrategyThread
from app.services import preflight
from app.services.promotion import (
    NotEligibleError,
    QueueLockedError,
    add_contact,
    add_member,
    clone_queue,
    person_of,
    promote,
)

pytestmark = [
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


def tag() -> str:
    return uuid.uuid4().hex[:6]


async def company(session, *, status="resolved", name=None) -> Account:
    row = Account(name=name or f"Datadog {tag()}", domain=f"dd-{tag()}.example", resolution_status=status)
    session.add(row)
    await session.flush()
    return row


async def person(session, account, *, email_status="verified", linkedin=None, email=True, name="Enrico Bergamo"):
    row = Contact(
        account_id=account.id, full_name=name, title="Head of IT",
        email=f"{tag()}@{account.domain}" if email else None,
        email_status=email_status if email else "unverified",
        linkedin_url=linkedin,
    )
    session.add(row)
    await session.flush()
    return row


async def queue(session, label="People push") -> CampaignQueue:
    row = CampaignQueue(label=label, status="draft")
    session.add(row)
    await session.flush()
    return row


async def shape(session) -> CadenceShape:
    row = CadenceShape(
        lgm_audience_name="Gen360 · Tests", key=f"shape_{tag()}", label="Standard", lgm_campaign_id="lgm-1", touch_count=6, span_days=15,
        attribute_map={str(i): f"custom_attribute_{i}" for i in range(1, 7)}, attributes_used=6,
        verified_at=datetime.now(UTC) - timedelta(days=2), verified_by="tests", lgm_status="active",
        active=True,
    )
    session.add(row)
    await session.flush()
    return row


async def pursued_thread(session, contact) -> StrategyThread:
    service = ServiceCatalog(code=f"s{tag()}", name="EIA", description="d")
    strategy = Strategy(account_id=contact.account_id, version=1)
    session.add_all([service, strategy])
    await session.flush()
    thread = StrategyThread(
        strategy_id=strategy.id, contact_id=contact.id, service_id=service.id, weight=60, rank=1,
        thread_status="active_primary", problem_hypothesis="IT is stretched", trigger_summary="t",
        trigger_signal_ids=[str(uuid.uuid4())], positioning="p", channel_sequence=["email"], cta="c",
    )
    session.add(thread)
    await session.flush()
    return thread


async def sequences_of(session, campaign) -> list[OutreachSequence]:
    return list(
        (await session.execute(select(OutreachSequence).where(OutreachSequence.campaign_id == campaign.id))).scalars()
    )


class TestWhoCanBeQueued:
    async def test_a_verified_email_or_a_linkedin_profile_is_enough(self, session):
        acc = await company(session)
        q = await queue(session)
        by_email = await person(session, acc)
        by_linkedin = await person(session, acc, email=False, linkedin="https://www.linkedin.com/in/enrico", name="Other Person")
        assert await add_contact(session, queue_id=q.id, contact_id=by_email.id)
        assert await add_contact(session, queue_id=q.id, contact_id=by_linkedin.id)

    async def test_someone_with_neither_is_refused_with_the_reason(self, session):
        acc = await company(session)
        q = await queue(session)
        guessed = await person(session, acc, email_status="risky")
        with pytest.raises(NotEligibleError, match="verified email or LinkedIn"):
            await add_contact(session, queue_id=q.id, contact_id=guessed.id)

    async def test_the_company_rule_still_applies(self, session):
        acc = await company(session, status="needs_review")
        q = await queue(session)
        enrico = await person(session, acc)
        with pytest.raises(NotEligibleError, match="identity not confirmed"):
            await add_contact(session, queue_id=q.id, contact_id=enrico.id)

    async def test_added_twice_is_counted_once_and_a_locked_queue_refuses(self, session):
        acc = await company(session)
        q = await queue(session)
        enrico = await person(session, acc)
        assert await add_contact(session, queue_id=q.id, contact_id=enrico.id)
        assert await add_contact(session, queue_id=q.id, contact_id=enrico.id) is None
        await promote(session, queue_ids=[q.id], label="C", cadence_shape_id=(await shape(session)).id)
        other = await person(session, acc, name="Late Comer")
        with pytest.raises(QueueLockedError):
            await add_contact(session, queue_id=q.id, contact_id=other.id)


class TestPromotingPeople:
    async def test_each_person_gets_a_sequence_without_a_strategy(self, session):
        acc = await company(session)
        q = await queue(session)
        enrico = await person(session, acc)
        await add_contact(session, queue_id=q.id, contact_id=enrico.id)
        campaign = await promote(session, queue_ids=[q.id], label="People", cadence_shape_id=(await shape(session)).id)

        [sequence] = await sequences_of(session, campaign)
        assert sequence.contact_id == enrico.id and sequence.thread_id is None
        assert sequence.status == "draft" and sequence.lgm_identity_id is not None
        assert not campaign.promotion_notes

    async def test_a_person_also_covered_by_their_company_gets_one_sequence(self, session):
        acc = await company(session)
        q = await queue(session)
        enrico = await person(session, acc)
        thread = await pursued_thread(session, enrico)
        await add_member(session, queue_id=q.id, account_id=acc.id)
        await add_contact(session, queue_id=q.id, contact_id=enrico.id)
        campaign = await promote(session, queue_ids=[q.id], label="Both", cadence_shape_id=(await shape(session)).id)

        [sequence] = await sequences_of(session, campaign)
        assert sequence.contact_id == enrico.id and sequence.thread_id == thread.id

    async def test_the_enrolment_lock_still_holds_for_a_person_promoted_by_name(self, session):
        """Promotion makes drafts; the lock bites when a second live sequence
        for the same person is sent for approval — as for company members."""
        from sqlalchemy.exc import IntegrityError

        acc = await company(session)
        q = await queue(session)
        enrico = await person(session, acc)
        identity = LgmIdentity(email=enrico.email)
        other = OutreachCampaign(label="Earlier", status="draft")
        session.add_all([identity, other])
        await session.flush()
        enrico.lgm_identity_id = identity.id
        session.add(OutreachSequence(contact_id=enrico.id, campaign_id=other.id,
                                     lgm_identity_id=identity.id, status="pending_approval"))
        await session.flush()

        await add_contact(session, queue_id=q.id, contact_id=enrico.id)
        campaign = await promote(session, queue_ids=[q.id], label="Later", cadence_shape_id=(await shape(session)).id)
        [draft] = await sequences_of(session, campaign)
        assert draft.status == "draft" and draft.lgm_identity_id == identity.id

        draft.status = "pending_approval"
        with pytest.raises(IntegrityError, match="one_active_sequence_per_lgm_identity"):
            await session.flush()

    async def test_a_clone_carries_the_people(self, session):
        acc = await company(session)
        q = await queue(session)
        enrico = await person(session, acc)
        await add_contact(session, queue_id=q.id, contact_id=enrico.id)
        await promote(session, queue_ids=[q.id], label="C", cadence_shape_id=(await shape(session)).id)
        clone = await clone_queue(session, q.id, label="C v2")
        people = (await session.execute(select(CampaignQueueContact.contact_id).where(CampaignQueueContact.queue_id == clone.id))).scalars().all()
        assert people == [enrico.id]


class TestStrategyIsNeededBeforeExecuting:
    async def test_preflight_names_the_people_without_a_strategy_and_links_one_once_built(self, session):
        acc = await company(session)
        q = await queue(session)
        enrico = await person(session, acc)
        await add_contact(session, queue_id=q.id, contact_id=enrico.id)
        campaign = await promote(session, queue_ids=[q.id], label="C", cadence_shape_id=(await shape(session)).id)

        check = next(c for c in (await preflight.run(session, campaign.id)).checks if c.key == "strategy")
        assert not check.passed and "Enrico Bergamo" in check.detail

        thread = await pursued_thread(session, enrico)
        check = next(c for c in (await preflight.run(session, campaign.id)).checks if c.key == "strategy")
        assert check.passed
        [sequence] = await sequences_of(session, campaign)
        assert sequence.thread_id == thread.id, "the strategy built later is linked"

    async def test_the_person_is_read_from_the_sequence_either_way(self, session):
        acc = await company(session)
        enrico = await person(session, acc)
        campaign = OutreachCampaign(label="C", status="draft")
        session.add(campaign)
        await session.flush()
        sequence = OutreachSequence(contact_id=enrico.id, campaign_id=campaign.id, status="draft")
        session.add(sequence)
        await session.flush()
        contact, thread = await person_of(session, sequence)
        assert contact.id == enrico.id and thread is None


class TestAQueuedPersonKeepsTheirCompany:
    async def test_deleting_the_list_leaves_the_company_live(self, session):
        from app.services import anchoring

        acc = await company(session)
        lst = AccountList(label=f"l-{tag()}", source="csv", created_by="tests")
        session.add(lst)
        await session.flush()
        session.add(AccountListMember(list_id=lst.id, account_id=acc.id))
        q = await queue(session)
        enrico = await person(session, acc)
        await add_contact(session, queue_id=q.id, contact_id=enrico.id)
        assessment = await anchoring.assess(session, [acc.id], ignoring_list=lst.id, delete_empty=True)
        assert assessment.in_queues == {acc.id}


@pytest.fixture
async def api():
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


class TestTheRoutes:
    async def test_add_list_and_remove_people(self, api):
        async with api.maker() as s:
            acc = await company(s)
            q = await queue(s)
            ok = await person(s, acc)
            bad = await person(s, acc, email_status="unverified", name="No Route")
            await s.commit()
            ids = {"queue": q.id, "ok": ok.id, "bad": bad.id}

        r = await api.post(f"/api/queues/{ids['queue']}/contacts/bulk",
                           json={"contact_ids": [str(ids["ok"]), str(ids["bad"]), str(uuid.uuid4())]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert (body["added"], body["already"]) == (1, 0)
        assert sorted(x["reason"].split(" —")[0] for x in body["refused"]) == sorted([
            "contact no longer exists", "no verified email or LinkedIn profile",
        ])

        people = (await api.get(f"/api/queues/{ids['queue']}/contacts")).json()
        assert [p["full_name"] for p in people] == ["Enrico Bergamo"]
        assert people[0]["reachable_by"] == "email"

        assert (await api.delete(f"/api/queues/{ids['queue']}/contacts/{ids['ok']}")).status_code == 204
        assert (await api.get(f"/api/queues/{ids['queue']}/contacts")).json() == []
