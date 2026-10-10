"""Sales prep reads facts, and says which kind of fact each one is.

The whole screen exists to stop a rep walking into a call believing something
the data does not support, so most of what is asserted here is about the
*labelling* rather than the values: that an absence is not reported as a
finding, that an inference is not reported as a record, and that a rung of the
engagement ladder nobody can observe is not reported as zero.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_session
from app.main import create_app
from app.models.account import Account, Contact
from app.models.campaign import OutreachCampaign, OutreachSequence
from app.models.config import ProofPoint, ServiceCatalog, SignalType
from app.models.content import Touch
from app.models.context import Qualification
from app.models.execution import OutreachEvent
from app.models.signal import Signal

TEST_DB = os.environ.get("TEST_DATABASE_URL", "")
requires_db = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL is not set")

pytestmark = requires_db


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DB)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
        await s.rollback()
    await engine.dispose()


@pytest.fixture
async def api(session):
    app = create_app()

    async def override():
        yield session

    app.dependency_overrides[get_session] = override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.fixture
async def contact(session):
    # `signal` carries a composite FK to `signal_type`, so a type has to exist
    # before a signal citing it can.
    session.add(
        SignalType(
            key="product_launch",
            label="Product launch",
            scope="company",
            default_ttl_days=90,
            produced_by=["company_site"],
        )
    )
    account = Account(
        name="Doist",
        domain="doist.com",
        resolution_status="resolved",
        research_status="complete",
        research_completed_at=datetime.now(UTC) - timedelta(days=1),
    )
    session.add(account)
    await session.flush()
    person = Contact(
        account_id=account.id,
        full_name="Amir Salihefendic",
        title="Founder and CEO",
        seniority="c_level",
        email="a@example.invalid",
        email_status="unverified",
    )
    session.add(person)
    await session.flush()
    return person


async def _get(api, contact) -> dict:
    r = await api.get(f"/api/prep/{contact.id}")
    assert r.status_code == 200, r.text
    return r.json()


class TestFreshnessIsThreeQuestions:
    """Research, signals, engagement. Measured on one real account: researched
    today, newest signal one day old, oldest nine months, nothing ever sent.
    One number would have read "fresh" and been wrong twice over."""

    async def test_all_three_are_reported(self, api, contact):
        body = await _get(api, contact)
        assert [f["kind"] for f in body["freshness"]] == [
            "research",
            "signals",
            "engagement",
        ]

    async def test_never_is_none_not_zero(self, api, session, contact):
        """A screen rendering both as 0 tells a rep research is current when
        nobody has looked."""
        account = await session.get(Account, contact.account_id)
        account.research_completed_at = None
        account.research_status = "not_started"
        await session.flush()

        body = await _get(api, contact)
        research = next(f for f in body["freshness"] if f["kind"] == "research")
        assert research["days"] is None
        assert "nobody has looked" in research["detail"]

    async def test_signal_age_is_not_research_age(self, api, session, contact):
        """The distinction the whole panel exists for: a fresh look at a stale
        picture."""
        session.add_all(
            [
                Signal(
                    account_id=contact.account_id,
                    signal_type="product_launch",
                    scope="company",
                    summary="Shipped an MCP server.",
                    strength="medium",
                    confidence=0.95,
                    observed_at=date.today() - timedelta(days=1),
                    lifecycle_state="discovered",
                ),
                Signal(
                    account_id=contact.account_id,
                    signal_type="product_launch",
                    scope="company",
                    summary="Shipped a speech feature.",
                    strength="high",
                    confidence=0.95,
                    observed_at=date.today() - timedelta(days=270),
                    lifecycle_state="discovered",
                ),
            ]
        )
        await session.flush()

        body = await _get(api, contact)
        research = next(f for f in body["freshness"] if f["kind"] == "research")
        signals = next(f for f in body["freshness"] if f["kind"] == "signals")
        assert research["days"] == 1
        assert signals["days"] == 1, "newest signal drives the headline age"
        # And the spread is still visible, which is the point.
        assert "oldest 270d" in signals["detail"]


class TestTheEngagementLadder:
    """A drafted message is not approved, approved is not sent, sent is not
    delivered, delivered is not interest. A rep who believes the prospect read
    something they never received has been actively misled."""

    async def test_nothing_sent_says_so_and_claims_nothing(self, api, contact):
        body = await _get(api, contact)
        assert body["engagement"]["reached"] is None
        assert body["engagement"]["counts"]["sent"] == 0
        assert "no conversation to be aware of" in body["engagement"]["detail"]

    async def test_unobservable_rungs_are_named_not_zeroed(self, api, contact):
        """Zero and "we cannot see this" are different claims."""
        body = await _get(api, contact)
        assert set(body["engagement"]["unobservable"]) == {"delivered", "replied"}

    async def test_delivery_is_never_observable_and_says_why(self, api, contact):
        """LGM's vocabulary is message_sent and message_received. It never
        reports delivery, so this rung is not waiting on the webhook receiver
        — it is a thing the provider will not tell us, and the brief must not
        imply it is coming."""
        body = await _get(api, contact)
        why = body["engagement"]["unobservable_why"]
        assert "delivered" in why
        assert "never delivery" in why["delivered"]
        assert "delivered" not in body["engagement"]["counts"], (
            "a rung that can never be filled must not be counted"
        )

    async def test_mode_follows_the_ladder_rather_than_a_choice(self, api, contact):
        """Nothing sent means there is no conversation, so the brief must be
        written as a cold approach."""
        body = await _get(api, contact)
        assert body["mode"] == "pre_engagement"

    async def test_a_reply_flips_the_mode(self, api, session, contact):
        session.add(
            OutreachEvent(
                source="lgm",
                received_via="webhook",
                event_type="reply",
                channel="email",
                direction="received",
                occurred_at=datetime.now(UTC),
                contact_id=contact.id,
                preview="We are exploring MCP, but it is still experimental.",
            )
        )
        await session.flush()

        body = await _get(api, contact)
        assert body["mode"] == "engagement_aware"
        assert body["engagement"]["reached"] == "replied"
        # Replies become observable once events arrive. Delivery does not, and
        # must not quietly drop off the list once something else works.
        assert body["engagement"]["unobservable"] == ["delivered"]

    async def test_a_drafted_touch_is_not_a_sent_one(self, api, session, contact):
        campaign = OutreachCampaign(label="Q4", status="draft")
        session.add(campaign)
        await session.flush()
        sequence = OutreachSequence(
            campaign_id=campaign.id, contact_id=contact.id, status="draft"
        )
        session.add(sequence)
        await session.flush()
        session.add(
            Touch(
                sequence_id=sequence.id,
                step_no=1,
                channel="email",
                status="pending",
                content_written_at=datetime.now(UTC),
            )
        )
        await session.flush()

        body = await _get(api, contact)
        counts = body["engagement"]["counts"]
        assert counts["drafted"] == 1
        assert counts["sent"] == 0
        assert body["engagement"]["reached"] == "drafted"
        assert body["mode"] == "pre_engagement", "a draft is not a conversation"


class TestTheScoreIsUnpacked:
    """"49, low" is not a verdict on the account when two of its six
    dimensions are zero for reasons that say nothing about the company."""

    @pytest.fixture
    async def qualified(self, session, contact):
        session.add(
            Qualification(
                account_id=contact.account_id,
                fit_score=0,
                opportunity_score=75,
                buyer_score=50,
                commercial_score=75,
                intent_score=75,
                engagement_score=0,
                priority_score=48.75,
                priority_band="low",
                scoring_config_version=8,
                man_money="strong",
                man_authority="moderate",
                man_need="strong",
                reasons={
                    "fit": {
                        "basis": "no_evidence",
                        "score": 0.0,
                        "reason": "nothing on the account to compare",
                        "evidence_ids": [],
                    },
                    "opportunity": {
                        "basis": "evidence",
                        "score": 75.0,
                        "reason": "AI-native integrations",
                        "evidence_ids": [str(uuid.uuid4()) for _ in range(4)],
                    },
                    "buyer": {
                        "basis": "contacts",
                        "score": 50.0,
                        "reason": "economic and technical buyer present",
                        "evidence_ids": [],
                    },
                    "commercial": {
                        "basis": "evidence",
                        "score": 75.0,
                        "reason": "estimated ARR",
                        "evidence_ids": [str(uuid.uuid4()) for _ in range(2)],
                    },
                    "intent": {
                        "basis": "evidence",
                        "score": 75.0,
                        "reason": "multiple 2026 releases",
                        "evidence_ids": [str(uuid.uuid4()) for _ in range(4)],
                    },
                    "engagement": {
                        "basis": "outreach",
                        "score": 0.0,
                        "reason": "nothing has been sent to anyone here",
                        "evidence_ids": [],
                    },
                },
            )
        )
        await session.flush()

    async def test_every_dimension_carries_its_basis(self, api, contact, qualified):
        body = await _get(api, contact)
        by_name = {d["dimension"]: d for d in body["qualification"]["dimensions"]}
        assert by_name["fit"]["basis"] == "no_evidence"
        assert by_name["opportunity"]["basis"] == "evidence"
        assert by_name["opportunity"]["evidence_count"] == 4
        assert by_name["buyer"]["basis"] == "contacts"

    async def test_an_absence_is_not_averaged_in_as_a_finding(
        self, api, contact, qualified
    ):
        """`fit` had nothing to compare and `engagement` is structurally zero
        until a campaign runs. Averaging them in pulled 68.75 down to 55 and
        made an under-researched account look like a weak one."""
        qual = (await _get(api, contact))["qualification"]
        assert qual["priority_score"] == 48.75
        assert qual["priority_band"] == "low"
        assert sorted(qual["unassessed"]) == ["engagement", "fit"]
        assert qual["assessed_average"] == 68.75

    async def test_a_real_basis_stays_in_the_average(self, api, contact, qualified):
        """`contacts` is a genuine basis, so buyer's 50 belongs in it — the
        rule is about absence, not about evidence rows specifically."""
        qual = (await _get(api, contact))["qualification"]
        assert "buyer" not in qual["unassessed"]


class TestThePersonaSaysWhereItCameFrom:
    """The first version returned "inferred from job title" for every contact
    with a title while `persona_role` was null — asserting an inference nobody
    had made, which is the exact failure the labelling exists to prevent."""

    async def test_a_derived_persona_says_it_was_derived(self, api, contact):
        body = await _get(api, contact)
        assert body["persona_role"] == "economic buyer"
        assert body["persona_basis"] == "inferred from job title"

    async def test_a_stored_persona_says_it_was_stored(self, api, session, contact):
        contact.persona_role = "technical buyer"
        await session.flush()
        body = await _get(api, contact)
        assert body["persona_role"] == "technical buyer"
        assert body["persona_basis"] == "recorded on the contact"

    async def test_an_unrecognised_title_claims_nothing(self, api, session, contact):
        contact.title = "Head of Partnerships"
        await session.flush()
        body = await _get(api, contact)
        assert body["persona_role"] is None
        assert "not established" in body["persona_basis"]


class TestWhatTheBriefMayCite:
    async def test_only_approved_proof_is_offered(self, api, session, contact):
        service = ServiceCatalog(code="eia", name="Enterprise Intelligence", description="EIA")
        session.add(service)
        await session.flush()
        session.add_all(
            [
                ProofPoint(
                    service_id=service.id,
                    kind="case_study",
                    title="Approved, with a number",
                    body="9 days to 3.",
                    metrics={"before": 9, "after": 3},
                    is_approved=True,
                ),
                ProofPoint(
                    service_id=service.id,
                    kind="case_study",
                    title="Not approved",
                    body="Should never appear.",
                    is_approved=False,
                ),
            ]
        )
        await session.flush()

        body = await _get(api, contact)
        titles = [p["title"] for p in body["proof"]]
        assert "Approved, with a number" in titles
        assert "Not approved" not in titles

    async def test_proof_says_whether_it_has_a_measured_outcome(
        self, api, session, contact
    ):
        """A case study with no metric may describe a capability but must not
        claim a result, and the screen has to know which it holds."""
        service = ServiceCatalog(code="eia2", name="EIA", description="EIA")
        session.add(service)
        await session.flush()
        session.add(
            ProofPoint(
                service_id=service.id,
                kind="case_study",
                title="Capability only",
                body="Discovers intelligence across silos.",
                is_approved=True,
            )
        )
        await session.flush()

        body = await _get(api, contact)
        row = next(p for p in body["proof"] if p["title"] == "Capability only")
        assert row["has_metric"] is False

    async def test_no_email_address_reaches_the_response(self, api, contact):
        """Invariant 9, and a prep brief needs no address: the status is
        carried so the screen can say "unreachable" without the value."""
        r = await api.get(f"/api/prep/{contact.id}")
        assert "a@example.invalid" not in r.text
        assert r.json()["email_status"] == "unverified"


class TestTheIndex:
    async def test_an_unknown_contact_is_a_404(self, api):
        r = await api.get(f"/api/prep/{uuid.uuid4()}")
        assert r.status_code == 404

    async def test_a_contact_with_no_trigger_still_appears(self, api, contact):
        """The queue is a convenience, not a gate — a rep preparing before
        there is a calendar invite must not be blocked by the data model."""
        r = await api.get("/api/prep")
        assert r.status_code == 200
        body = r.json()
        row = next(x for x in body["results"] if x["contact_id"] == str(contact.id))
        assert row["why_now"] == "No active signal"
        assert row["why_now_kind"] == "none"

    async def test_the_empty_queue_explains_itself(self, api, contact):
        """"No event can arrive yet" is a build state; "nobody has replied" is
        a sales fact. The screen must not show one as the other."""
        body = (await api.get("/api/prep")).json()
        assert body["queue"] == []
        assert "No event has ever been received" in body["queue_blocked"]

    async def test_search_matches_the_company_too(self, api, contact):
        body = (await api.get("/api/prep?q=doist")).json()
        assert [x["contact_id"] for x in body["results"]] == [str(contact.id)]

    async def test_the_newest_signal_is_the_reason(self, api, session, contact):
        session.add(
            Signal(
                account_id=contact.account_id,
                signal_type="product_launch",
                scope="company",
                summary="Released todoist-mcp.",
                strength="medium",
                confidence=0.95,
                observed_at=date.today(),
                lifecycle_state="discovered",
            )
        )
        await session.flush()
        body = (await api.get("/api/prep?q=doist")).json()
        row = body["results"][0]
        assert row["why_now"] == "Released todoist-mcp."
        assert row["why_now_kind"] == "signal"
