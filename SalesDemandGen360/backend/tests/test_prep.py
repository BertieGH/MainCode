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
from sqlalchemy import select
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

# `db` so the autouse fixture truncates between tests. Rollback alone is not
# enough here: the generate route commits, which is the point of it, and a
# committed brief would otherwise leak into the next test.
pytestmark = [pytest.mark.db, requires_db]


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DB)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
        await s.rollback()
    await engine.dispose()


def _flatten(app):
    """Every route, through the router wrappers `app.routes` actually holds.

    `app.routes` is a list of `_IncludedRouter` objects rather than routes, so
    a flat scan finds nothing and silently does nothing — which is how the
    first version of the gate override passed over the route it meant to
    disable.
    """
    found = []
    stack = list(app.routes)
    seen = set()
    while stack:
        item = stack.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        # An included router is wrapped; its own routes hang off
        # `original_router`, not off the wrapper.
        inner = getattr(item, "original_router", None)
        if inner is not None:
            stack.extend(getattr(inner, "routes", []))
        stack.extend(getattr(item, "routes", []) if inner is None else [])
        if hasattr(item, "path"):
            found.append(item)
    return found


@pytest.fixture
async def api(session):
    app = create_app()

    async def override():
        yield session

    app.dependency_overrides[get_session] = override

    # **The setup gate is bypassed here, and asserted separately.** It is a
    # route dependency bound at import, so it cannot be monkeypatched; and
    # seeding a real model credential would make every test in this file
    # depend on the credential store to check something about prep. The gate
    # has its own tests, and `test_generation_is_gated_on_a_model` below
    # asserts this route still carries it.
    for route in _flatten(app):
        for dep in getattr(route, "dependencies", []):
            if getattr(dep.dependency, "__name__", "") == "_gate":
                app.dependency_overrides[dep.dependency] = lambda: None
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


def _brief(**over) -> dict:
    """A payload that satisfies the contract, so a test can vary one thing."""
    base = {
        "what_to_find_out": "Whether the AI surface work has created a constraint, and who owns it.",
        "what_not_to_attempt": "Convincing him he has an ingestion problem.",
        "problem_is_unproven": (
            "We think the AI rollout strains engineering. Nothing establishes he agrees."
        ),
        "openings": [
            {
                "label": "Honest outsider",
                "words": "I can't tell from the outside whether this is easy or a headache.",
                "use_when": "Lowest pressure — best if you are new.",
                "why_it_works": "Cannot be contradicted, and invites a real answer.",
            }
        ],
        "listen_for": ["who owns the context layer"],
        "next_steps": [{"condition": "A constraint is confirmed", "action": "Propose discovery."}],
        "what_we_know": ["Four AI releases since January."],
        "what_we_suspect": ["Engineering may be split across both."],
        "what_we_do_not_know": ["Whether any bottleneck exists."],
        "do_not_assume": ["That he has a problem."],
        "elevator_pitch": "Four AI surfaces in nine months is a roadmap question.",
        "pitch_structure": {
            "situation": "Four AI surfaces since January.",
            "complication": "Each widens the ingestion surface.",
            "angle": "Engineering backing for context integration.",
            "proof": "9 days to 3.",
            "ask": "Worth a conversation?",
        },
        "discovery_questions": [
            {
                "question": "Who owns the shared context layer?",
                "listening_for": "Whether the work has its own headcount.",
                "changes": "Identifies the real technical stakeholder.",
                "branches": ["If borrowed, the capacity hypothesis is live."],
            }
        ],
        "objections": [],
        "already_said": [],
        "their_replies": [],
        "open_questions": [],
    }
    base.update(over)
    return base


@pytest.fixture
def stubbed(monkeypatch):
    from types import SimpleNamespace

    from app.api import prep as prep_api
    from app.schemas.prep import SalesPrepPayload

    seen: dict = {}

    async def fake(session, **kw):
        seen.update(kw)
        return SimpleNamespace(parsed=SalesPrepPayload.model_validate(_brief()))

    monkeypatch.setattr(prep_api.stages, "generate_prep", fake)
    return seen


class TestGeneratingTheBrief:
    """The stage is stubbed: these are about what the route does with a brief,
    not about what the model writes."""

    async def test_generation_is_gated_on_a_model(self):
        """Bypassed in these tests, so its presence is checked rather than
        assumed: an ungated generate route would spend on an installation that
        has not finished setting up."""
        from app.main import create_app

        gated = [
            r
            for r in _flatten(create_app())
            if getattr(r, "path", "").endswith("/prep/{contact_id}/generate")
        ]
        assert gated, "the generate route is missing"
        names = [
            getattr(d.dependency, "__name__", "") for d in gated[0].dependencies
        ]
        assert "_gate" in names

    async def test_a_brief_is_stored_with_what_it_was_written_from(
        self, api, session, contact, stubbed
    ):
        r = await api.post(f"/api/prep/{contact.id}/generate")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["mode"] == "pre_engagement"
        assert body["brief"]["what_to_find_out"]

        from app.models.prep import SalesPrep

        row = (await session.execute(select(SalesPrep))).scalars().one()
        # The context travels with the brief, so a later review can tell a
        # wrongly reasoned brief from a merely under-informed one.
        assert row.research_completed_at is not None
        assert row.touches_sent == 0
        assert row.replies_seen == 0

    async def test_the_model_is_given_the_gaps_not_only_the_conclusions(
        self, api, session, contact, stubbed
    ):
        """Given only conclusions it writes a confident brief; given what the
        scorer could not assess, an honest one."""
        session.add(
            Qualification(
                account_id=contact.account_id,
                fit_score=0,
                opportunity_score=75,
                priority_score=48.75,
                priority_band="low",
                scoring_config_version=8,
                reasons={
                    "fit": {"basis": "no_evidence", "score": 0.0, "reason": "nothing",
                            "evidence_ids": []},
                    "opportunity": {"basis": "evidence", "score": 75.0, "reason": "ai",
                                    "evidence_ids": [str(uuid.uuid4())]},
                },
            )
        )
        await session.flush()
        await api.post(f"/api/prep/{contact.id}/generate")
        assert "fit" in stubbed["qualification"]["unassessed"]
        assert stubbed["mode"] == "pre_engagement"

    async def test_a_quota_refusal_is_a_503_not_a_500(
        self, api, contact, monkeypatch
    ):
        from app.api import prep as prep_api
        from app.services.llm import LlmUnavailableError

        async def refuse(session, **kw):
            raise LlmUnavailableError(
                "Gemini returned HTTP 429, quota RESOURCE_EXHAUSTED",
                rate_limited=True,
                quota="RESOURCE_EXHAUSTED",
            )

        monkeypatch.setattr(prep_api.stages, "generate_prep", refuse)
        r = await api.post(f"/api/prep/{contact.id}/generate")
        assert r.status_code == 503
        assert "RESOURCE_EXHAUSTED" in r.json()["detail"]

    async def test_the_verdict_comes_back_to_the_brief(
        self, api, session, contact, stubbed
    ):
        prep_id = (await api.post(f"/api/prep/{contact.id}/generate")).json()["prep_id"]
        r = await api.post(
            f"/api/prep/{prep_id}/verdict",
            json={"hypothesis_verdict": "rejected", "outcome": "no_need_now"},
        )
        assert r.status_code == 200

        from app.models.prep import SalesPrep

        row = await session.get(SalesPrep, uuid.UUID(prep_id))
        await session.refresh(row)
        assert row.hypothesis_verdict == "rejected"
        assert row.outcome == "no_need_now"

    async def test_an_unrecognised_verdict_is_refused(self, api, contact, stubbed):
        """The vocabulary is a CHECK constraint; a typo is a 400, not a 500."""
        prep_id = (await api.post(f"/api/prep/{contact.id}/generate")).json()["prep_id"]
        r = await api.post(
            f"/api/prep/{prep_id}/verdict", json={"hypothesis_verdict": "sort of"}
        )
        assert r.status_code == 400


class TestTheContractRefusesAnOverconfidentBrief:
    """Validation is where the honesty rules are enforced, because a brief that
    reads well and claims too much is the failure mode."""

    async def test_a_brief_naming_nothing_to_doubt_is_refused(self):
        from pydantic import ValidationError

        from app.schemas.prep import SalesPrepPayload

        with pytest.raises(ValidationError, match="must not assume"):
            SalesPrepPayload.model_validate(_brief(do_not_assume=[]))

    async def test_an_objection_cannot_be_observed_without_a_reply(self):
        """Otherwise the model promotes its own guess to something they said,
        and a rep answers an objection nobody raised."""
        from pydantic import ValidationError

        from app.schemas.prep import SalesPrepPayload

        objection = {
            "objection": "We build this in-house.",
            "pre_empt": "That makes sense.",
            "kind": "observed",
        }
        with pytest.raises(ValidationError, match="observed"):
            SalesPrepPayload.model_validate(_brief(objections=[objection]))

        # The same objection, honestly labelled, is fine.
        ok = SalesPrepPayload.model_validate(
            _brief(objections=[{**objection, "kind": "anticipated"}])
        )
        assert ok.objections[0].kind == "anticipated"

    async def test_a_question_that_changes_nothing_cannot_be_asked(self):
        from pydantic import ValidationError

        from app.schemas.prep import SalesPrepPayload

        with pytest.raises(ValidationError):
            SalesPrepPayload.model_validate(
                _brief(
                    discovery_questions=[
                        {"question": "How are you?", "listening_for": "tone"}
                    ]
                )
            )


class TestAStoredBriefComesBackWithIt:
    """A generated brief that vanishes on reload has cost a model call for
    nothing, and a brief shown beside facts that have moved on is worse than
    one labelled as older than them."""

    async def test_the_newest_brief_is_returned(self, api, contact, stubbed):
        assert (await _get(api, contact))["brief"] is None
        await api.post(f"/api/prep/{contact.id}/generate")
        body = await _get(api, contact)
        assert body["brief"]["what_to_find_out"]
        assert body["brief_generated_at"]
        assert body["brief_mode"] == "pre_engagement"

    async def test_a_fresh_brief_is_not_stale(self, api, contact, stubbed):
        await api.post(f"/api/prep/{contact.id}/generate")
        assert (await _get(api, contact))["brief_is_stale"] is False

    async def test_a_new_signal_makes_the_brief_older_than_the_facts(
        self, api, session, contact, stubbed
    ):
        """Staleness is measured against what was true when it was written,
        not against the clock: an hour-old brief with nothing new since is not
        stale, and a minute-old one written before three signals arrived is."""
        await api.post(f"/api/prep/{contact.id}/generate")
        session.add(
            Signal(
                account_id=contact.account_id,
                signal_type="product_launch",
                scope="company",
                summary="Something new happened after the brief was written.",
                strength="medium",
                confidence=0.9,
                observed_at=date.today(),
                lifecycle_state="discovered",
            )
        )
        await session.flush()
        assert (await _get(api, contact))["brief_is_stale"] is True


class TestTheContractRefusesAPitchGoal:
    """Three briefs running, the objective came back as what to *say*.

    Prose did not move it, so the rule stopped being advice. The field is no
    longer called an objective — the model was reading the field name, and
    "call objective" means a pitch goal everywhere else in sales — and the
    contract now rejects a sentence that talks about us.
    """

    def test_a_sentence_about_us_is_refused(self):
        from pydantic import ValidationError

        from app.schemas.prep import SalesPrepPayload

        with pytest.raises(ValidationError, match="reads as a pitch goal"):
            SalesPrepPayload.model_validate(
                _brief(
                    what_to_find_out=(
                        "Validate whether their AI rollout is pulling engineering off "
                        "the roadmap, and introduce our EIA services as a way to build "
                        "capability faster."
                    )
                )
            )

    def test_the_pronoun_is_what_catches_it(self):
        """Checked by pronoun rather than by product name: it needs no
        catalogue and cannot be dodged by inventing a new offering."""
        from pydantic import ValidationError

        from app.schemas.prep import SalesPrepPayload

        for bad in (
            "Find out if they need what we sell.",
            "Establish whether our framework would fit.",
            "See if they would buy from us.",
        ):
            with pytest.raises(ValidationError):
                SalesPrepPayload.model_validate(_brief(what_to_find_out=bad))

    def test_a_question_about_them_passes(self):
        from app.schemas.prep import SalesPrepPayload

        ok = SalesPrepPayload.model_validate(
            _brief(
                what_to_find_out=(
                    "Whether the run of AI launches has created an engineering or "
                    "roadmap constraint, and who owns it."
                )
            )
        )
        assert ok.what_to_find_out.startswith("Whether")

    def test_a_word_merely_containing_us_is_not_a_false_positive(self):
        """`us` inside `focus` or `customers` must not trip the rule."""
        from app.schemas.prep import SalesPrepPayload

        ok = SalesPrepPayload.model_validate(
            _brief(
                what_to_find_out=(
                    "Which customers their current focus is aimed at, and whether "
                    "usage has shifted."
                )
            )
        )
        assert ok.what_to_find_out


class TestTheHypothesisCannotBeForgotten:
    """It was an item in `do_not_assume` and was dropped from every brief.

    An item in a list is optional in practice however firmly the prompt asks.
    A required field is not.
    """

    def test_a_brief_without_it_is_refused(self):
        from pydantic import ValidationError

        from app.schemas.prep import SalesPrepPayload

        payload = _brief()
        del payload["problem_is_unproven"]
        with pytest.raises(ValidationError):
            SalesPrepPayload.model_validate(payload)

    def test_it_cannot_be_blank(self):
        from pydantic import ValidationError

        from app.schemas.prep import SalesPrepPayload

        with pytest.raises(ValidationError):
            SalesPrepPayload.model_validate(_brief(problem_is_unproven=""))


class TestARepCanJudgeASignal:
    """The loop closing: every other verdict in the system is the model's own.

    A rep who reads the passage and says it is outdated knows something no
    evaluator does, and until this there was nowhere to put it.
    """

    @pytest.fixture
    async def signal(self, session, contact):
        # Evidence first: a database trigger enforces invariant 1, so a bare
        # signal cannot be committed. These tests commit, which is how the
        # trigger found the fixture.
        from app.models.signal import Evidence, signal_evidence

        ev = Evidence(
            account_id=contact.account_id,
            source_type="web",
            source_url="https://example.invalid/mcp",
            source_name="Doist blog",
            excerpt="A set of tools to connect AI agents to Todoist.",
            observed_at=date.today(),
            source_hash="a" * 64,
            excerpt_hash="b" * 64,
            raw_status="unavailable",
        )
        row = Signal(
            account_id=contact.account_id,
            signal_type="product_launch",
            scope="company",
            summary="Released todoist-mcp.",
            strength="medium",
            confidence=0.95,
            observed_at=date.today(),
            lifecycle_state="discovered",
        )
        session.add_all([ev, row])
        await session.flush()
        await session.execute(
            signal_evidence.insert().values(signal_id=row.id, evidence_id=ev.id)
        )
        await session.flush()
        return row

    async def test_a_verdict_is_recorded_where_evaluations_live(
        self, api, session, contact, signal
    ):
        from app.models.governance import Evaluation

        r = await api.post(
            f"/api/prep/signals/{signal.id}/verdict", json={"verdict": "outdated"}
        )
        assert r.status_code == 200, r.text

        row = (await session.execute(select(Evaluation))).scalars().one()
        assert row.subject_type == "signal" and row.method == "rep"
        # Three values cannot carry five, so the word is kept beside them.
        assert row.verdict == "fail"
        assert row.scores["rep_verdict"] == "outdated"
        assert row.issues[0]["kind"] == "outdated"

    async def test_outdated_is_not_inaccurate(self, api, session, contact, signal):
        """One says the refresh cadence is wrong, the other that the reading
        is. Flattened to `fail` the evaluation layer cannot tell us which to
        fix, which is the only reason either is worth collecting."""
        from app.models.governance import Evaluation

        await api.post(
            f"/api/prep/signals/{signal.id}/verdict", json={"verdict": "inaccurate"}
        )
        row = (await session.execute(select(Evaluation))).scalars().one()
        assert row.verdict == "fail"
        assert row.scores["rep_verdict"] == "inaccurate"

    async def test_an_accurate_verdict_survives_a_reload(
        self, api, session, contact, signal
    ):
        """`accurate` maps to `pass`, and a pass stores no issues. Read back
        from `issues` it came out as "pass" — a value no button matches — so a
        recorded verdict silently vanished when the screen reloaded."""
        await api.post(
            f"/api/prep/signals/{signal.id}/verdict", json={"verdict": "accurate"}
        )
        body = await _get(api, contact)
        found = next(s for s in body["signals"] if s["id"] == str(signal.id))
        assert found["rep_verdict"] == "accurate"

    async def test_an_unknown_verdict_is_refused(self, api, signal):
        r = await api.post(
            f"/api/prep/signals/{signal.id}/verdict", json={"verdict": "rubbish"}
        )
        assert r.status_code == 400
        assert "accurate" in r.json()["detail"]

    async def test_the_newest_verdict_is_the_one_shown(
        self, api, session, contact, signal
    ):
        """A rep may change their mind; the record keeps both."""
        from app.models.governance import Evaluation

        for verdict in ("inaccurate", "accurate"):
            await api.post(
                f"/api/prep/signals/{signal.id}/verdict", json={"verdict": verdict}
            )
        body = await _get(api, contact)
        found = next(s for s in body["signals"] if s["id"] == str(signal.id))
        assert found["rep_verdict"] == "accurate"
        kept = (await session.execute(select(Evaluation))).scalars().all()
        assert len(kept) == 2, "an evaluation is a record, not a setting"

    async def test_the_evidence_carries_both_dates(self, api, session, contact, signal):
        """When it happened, and when we read it. A nine-month-old post read
        this morning is fresh research into a stale fact."""
        from app.models.signal import Evidence, signal_evidence

        ev = Evidence(
            account_id=contact.account_id,
            source_type="web",
            source_url="https://example.invalid/post",
            source_name="Doist blog",
            excerpt="A set of tools to connect AI agents to Todoist.",
            observed_at=date.today() - timedelta(days=270),
            source_hash="h" * 64,
            excerpt_hash="e" * 64,
            raw_status="unavailable",
        )
        session.add(ev)
        await session.flush()
        await session.execute(
            signal_evidence.insert().values(signal_id=signal.id, evidence_id=ev.id)
        )
        await session.flush()

        body = await _get(api, contact)
        found = next(s for s in body["signals"] if s["id"] == str(signal.id))
        old = next(
            e for e in found["evidence"] if e["source_url"].endswith("/post")
        )
        assert old["excerpt"].startswith("A set of tools")
        assert old["source_name"] == "Doist blog"
        # Dated nine months ago, retrieved just now.
        assert old["observed_at"] != str(date.today())
        assert old["retrieved_at"].startswith(str(date.today()))
