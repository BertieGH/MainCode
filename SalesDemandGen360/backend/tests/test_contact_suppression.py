"""Do-not-contact: every door it closes, and the history it keeps.

Deleting a person was the alternative and it is the wrong tool — their signals,
evidence and outreach history cite them. Suppression keeps all of that and stops
anything that would spend money on them or reach them: enrichment, research,
queueing and execution.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.account import Account, AccountList, AccountListMember, Contact
from app.models.campaign import CadenceShape, CampaignQueue
from app.services import preflight, promotion, research, verification

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"),
]


def tag() -> str:
    return uuid.uuid4().hex[:6]


@pytest.fixture
async def session():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
        await s.rollback()
    await engine.dispose()


async def world(session, *, suppressed_reason="asked us to stop"):
    """A list with one company and two people, one of them suppressed."""
    lst = AccountList(label=f"l-{tag()}", source="csv", created_by="tests")
    account = Account(name=f"Datadog {tag()}", domain=f"dd-{tag()}.example", resolution_status="resolved")
    session.add_all([lst, account])
    await session.flush()
    session.add(AccountListMember(list_id=lst.id, account_id=account.id))
    off = Contact(
        account_id=account.id, full_name="Enrico Bergamo", title="CTO", buying_role="technical_buyer",
        email=f"e{tag()}@{account.domain}", email_status="verified",
        do_not_contact=True, do_not_contact_reason=suppressed_reason, do_not_contact_at=datetime.now(UTC),
    )
    ok = Contact(
        account_id=account.id, full_name="Ada Lovelace", title="VP Engineering",
        buying_role="technical_buyer", email=f"a{tag()}@{account.domain}", email_status="unverified",
    )
    session.add_all([off, ok])
    await session.flush()
    return lst, account, off, ok


class TestTheFlagItself:
    async def test_a_reason_is_required(self, session):
        account = Account(name=f"A {tag()}", domain=f"a-{tag()}.example", resolution_status="resolved")
        session.add(account)
        await session.flush()
        session.add(Contact(account_id=account.id, full_name="No Reason", do_not_contact=True))
        with pytest.raises(IntegrityError, match="dnc_carries_a_reason"):
            await session.flush()


class TestTheDoorsItCloses:
    async def test_enrichment_does_not_spend_on_them(self, session):
        lst, _, off, ok = await world(session)
        found = await verification.unverified_contacts(session, list_id=lst.id)
        assert [c.id for c in found] == [ok.id], "the suppressed person is not asked about"

        off.email_status = "unverified"
        await session.flush()
        found = await verification.unverified_contacts(session, list_id=lst.id, contact_ids=[off.id])
        assert found == [], "not even when picked by name"

    async def test_research_passes_over_them(self, session):
        _, account, off, ok = await world(session)
        ok.email_status = "verified"
        await session.flush()
        people = await research.contacts_to_research(
            session, account.id, targets=("technical_buyer", "CTO", "VP Engineering")
        )
        assert off.id not in {c.id for c in people}
        assert ok.id in {c.id for c in people}

    async def test_a_queue_refuses_them_by_name(self, session):
        _, _, off, _ = await world(session)
        queue = CampaignQueue(label="q", status="draft")
        session.add(queue)
        await session.flush()
        with pytest.raises(promotion.NotEligibleError, match="do not contact — asked us to stop"):
            await promotion.add_contact(session, queue_id=queue.id, contact_id=off.id)

    async def test_preflight_blocks_a_campaign_that_still_holds_one(self, session):
        _, _, off, _ = await world(session)
        off.do_not_contact = False
        off.do_not_contact_reason = None
        await session.flush()

        queue = CampaignQueue(label="q", status="draft")
        shape = CadenceShape(
            lgm_audience_name="Gen360 · Tests", key=f"shape_{tag()}", label="Standard", lgm_campaign_id="lgm-1", touch_count=6,
            span_days=15, attribute_map={str(i): f"custom_attribute_{i}" for i in range(1, 7)},
            attributes_used=6, verified_at=datetime.now(UTC) - timedelta(days=2),
            verified_by="tests", lgm_status="active", active=True,
        )
        session.add_all([queue, shape])
        await session.flush()
        await promotion.add_contact(session, queue_id=queue.id, contact_id=off.id)
        campaign = await promotion.promote(
            session, queue_ids=[queue.id], label="C", cadence_shape_id=shape.id
        )

        result = await preflight.run(session, campaign.id)
        assert len(result.checks) == 10
        check = next(c for c in result.checks if c.key == "do_not_contact")
        assert check.passed, "nobody is suppressed yet"

        # Marked after promotion, which is the usual order: the campaign is
        # why somebody asked to be left alone.
        off.do_not_contact = True
        off.do_not_contact_reason = "asked us to stop"
        await session.flush()
        check = next(
            c for c in (await preflight.run(session, campaign.id)).checks if c.key == "do_not_contact"
        )
        assert not check.passed
        assert "Enrico Bergamo (asked us to stop)" in check.detail


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


class TestTheRoute:
    async def test_marking_needs_a_reason_and_is_reversible(self, api):
        async with api.maker() as s:
            lst, _, _, ok = await world(s)
            await s.commit()
            ids = {"list": lst.id, "contact": ok.id}

        refused = await api.post(
            "/api/contacts/suppression", json={"contact_ids": [str(ids["contact"])]}
        )
        assert refused.status_code == 422

        marked = await api.post(
            "/api/contacts/suppression",
            json={"contact_ids": [str(ids["contact"]), str(uuid.uuid4())],
                  "do_not_contact": True, "reason": "left the company"},
        )
        assert marked.status_code == 200, marked.text
        assert marked.json() == {"updated": 1, "not_found": 1}

        rows = (await api.get(f"/api/lists/{ids['list']}/contacts")).json()
        [row] = [r for r in rows if r["id"] == str(ids["contact"])]
        assert (row["do_not_contact"], row["do_not_contact_reason"]) == (True, "left the company")

        allowed = await api.post(
            "/api/contacts/suppression",
            json={"contact_ids": [str(ids["contact"])], "do_not_contact": False},
        )
        assert allowed.status_code == 200
        rows = (await api.get(f"/api/lists/{ids['list']}/contacts")).json()
        [row] = [r for r in rows if r["id"] == str(ids["contact"])]
        assert row["do_not_contact"] is False and row["do_not_contact_reason"] is None
