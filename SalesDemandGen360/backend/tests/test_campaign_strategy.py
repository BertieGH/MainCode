"""Qualification and strategy per campaign, against the campaign's service and ICP.

The service and ICP are chosen with the queue and copied into the campaign.
The sales rules decide who is pursued by default; a rep may pursue someone the
rules leave out, or allow a strategy without a live signal — both recorded on
the thread, and both send the sequence to be read in approval.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.account import Account, Contact
from app.models.campaign import CadenceShape, CampaignQueue, OutreachSequence
from app.models.config import IcpProfile, IcpProfileVersion, ProofPoint, ServiceCatalog, service_icp_link
from app.models.context import AccountContext
from app.models.strategy import Strategy, StrategyThread
from app.models.strategy import StrategyAngle as StrategyAngle_
from app.schemas.strategy import PersonAngles, StrategyAngle, StrategyProposal
from app.services import approval, campaign_drafts, campaign_strategy, promotion
from app.services.campaign_strategy import NotReadyError, Rules

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"),
]

SIGNAL = uuid.uuid4()


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


@pytest.fixture(autouse=True)
def rules(monkeypatch):
    async def fixed(_session):
        return Rules(threshold=20, cap=2, offset=3, role_weights={"technical_buyer": 60, "influencer": 10})

    monkeypatch.setattr(campaign_strategy, "sales_rules", fixed)


def fake_signal(signal_id=None, *, contact_id=None):
    """A live signal as `context.live_signals` returns it — enough fields for
    `strategy_context` to rank and describe it."""
    return SimpleNamespace(
        id=signal_id or uuid.uuid4(), strength="high", contact_id=contact_id, confidence=0.8,
        observed_at=date.today(), signal_type="funding_growth_milestone", summary="Raised a Series B",
        business_implication="Hiring ahead of the roadmap", is_hypothesis=False,
    )


@pytest.fixture
def live(monkeypatch):
    """A live company signal by default; set `.signals = []` for none."""
    state = SimpleNamespace(signals=[fake_signal(SIGNAL)])

    async def signals(_session, _account_id, **_):
        return state.signals

    monkeypatch.setattr(campaign_strategy.context_service, "live_signals", signals)
    return state


async def targets(session, *, link=True):
    service = ServiceCatalog(code=f"s{tag()}", name="EIA", description="d")
    profile = IcpProfile(name=f"icp-{tag()}")
    session.add_all([service, profile])
    await session.flush()
    session.add(IcpProfileVersion(
        icp_profile_id=profile.id, version=1, is_active=True,
        definition={"personas": [{"buying_role": "technical_buyer", "titles": ["CTO"]}]},
    ))
    if link:
        await session.execute(service_icp_link.insert().values(service_id=service.id, icp_profile_id=profile.id))
    await session.flush()
    return service, profile


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


async def queue_for(session, service, profile, label="EIA push") -> CampaignQueue:
    row = CampaignQueue(label=label, status="draft", service_id=service.id,
                        icp_profile_id=profile.id, icp_version=1)
    session.add(row)
    await session.flush()
    return row


async def campaign_world(session):
    """A campaign with a CTO (pursued by the rules) and an end user (below threshold)."""
    service, profile = await targets(session)
    account = Account(name=f"Datadog {tag()}", domain=f"dd-{tag()}.example", resolution_status="resolved")
    session.add(account)
    await session.flush()
    session.add(AccountContext(account_id=account.id, version=1, payload={}, signal_ids=[]))
    cto = Contact(account_id=account.id, full_name="Enrico Bergamo", title="CTO", buying_role="technical_buyer",
                  email=f"e{tag()}@{account.domain}", email_status="verified")
    user = Contact(account_id=account.id, full_name="Ada User", title="Analyst", buying_role="influencer",
                   email=f"a{tag()}@{account.domain}", email_status="verified")
    session.add_all([cto, user])
    await session.flush()
    q = await queue_for(session, service, profile)
    for c in (cto, user):
        await promotion.add_contact(session, queue_id=q.id, contact_id=c.id)
    campaign = await promotion.promote(session, queue_ids=[q.id], label="EIA", cadence_shape_id=(await shape(session)).id)
    return SimpleNamespace(service=service, profile=profile, account=account, cto=cto, user=user, campaign=campaign)


def angles_for(people, *, hypothesis=lambda p: f"hurts differently for {p['contact_id']}"):
    """The model's answer, shaped as the contract wants it: one angle each."""
    return StrategyProposal(people=[
        PersonAngles(
            contact_id=p["contact_id"],
            angles=[StrategyAngle(
                angle="the obvious way in", problem_hypothesis=hypothesis(p), why_now="Series B",
                trigger_signal_ids=[] if p["may_cite_no_live_signal"] else [str(SIGNAL)],
                positioning="p", cta="15 minutes",
            )],
            recommended_order=[0], why_this_order="the only angle",
        )
        for p in people
    ], account_angle="A company in a hurry.")


def proposer(calls=None):
    async def synthesise(*, account, payload, people):
        if calls is not None:
            calls.append(payload)
        return SimpleNamespace(parsed=angles_for(people))
    return synthesise


def _about_a_stranger() -> StrategyProposal:
    """A schema-valid proposal that answers nobody we asked about.

    The contract floors `threads` at one, so a model cannot come back empty any
    more. What it can still do is argue a case for a `contact_id` that was
    never in the request — and the service has to treat that as a provider
    failure rather than silently dropping it and telling the rep nothing came
    back for their person.
    """
    return angles_for(
        [{"contact_id": str(uuid.uuid4()), "may_cite_no_live_signal": False}],
        hypothesis=lambda _p: "about somebody else entirely",
    )


def reasons(out) -> dict[str, str]:
    return {e["name"]: e["reason"] for e in out.excluded}


async def thread_of(session, w, contact) -> StrategyThread | None:
    [sequence] = (await session.execute(select(OutreachSequence).where(
        OutreachSequence.campaign_id == w.campaign.id, OutreachSequence.contact_id == contact.id))).scalars().all()
    return await session.get(StrategyThread, sequence.thread_id) if sequence.thread_id else None


class TestTargets:
    async def test_an_icp_not_linked_to_the_service_is_refused(self, session):
        service, _ = await targets(session)
        _, other = await targets(session, link=False)
        with pytest.raises(NotReadyError, match="not linked"):
            await campaign_strategy.choose_targets(session, service.id, other.id)

    async def test_promotion_copies_them_and_refuses_queues_built_for_different_ones(self, session):
        s1, p1 = await targets(session)
        s2, p2 = await targets(session)
        q1 = await queue_for(session, s1, p1)
        campaign = await promotion.promote(session, queue_ids=[q1.id], label="C", cadence_shape_id=(await shape(session)).id)
        assert (campaign.service_id, campaign.icp_profile_id, campaign.icp_version) == (s1.id, p1.id, 1)

        a, b = await queue_for(session, s1, p1), await queue_for(session, s2, p2)
        with pytest.raises(promotion.MixedTargetsError):
            await promotion.promote(session, queue_ids=[a.id, b.id], label="Mixed")

    async def test_a_campaign_without_them_says_so_and_can_be_given_them(self, session, live):
        from app.models.campaign import OutreachCampaign

        service, profile = await targets(session)
        campaign = OutreachCampaign(label="Old", status="draft")
        session.add(campaign)
        await session.flush()
        with pytest.raises(NotReadyError, match="no service and ICP"):
            await campaign_strategy.people_view(session, campaign)
        await campaign_strategy.set_targets(session, campaign, service.id, profile.id)
        assert (await campaign_strategy.people_view(session, campaign))["icp_version"] == 1


class TestDefaults:
    async def test_the_rules_pursue_the_buyer_and_leave_the_end_user_out(self, session, live):
        w = await campaign_world(session)
        view = await campaign_strategy.people_view(session, w.campaign)
        decisions = {p["full_name"]: p["default_decision"] for p in view["people"]}
        assert decisions == {"Enrico Bergamo": "pursue", "Ada User": "below_threshold"}
        assert all(p["live_signals"] == 1 for p in view["people"])


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
    # The capability gate asks whether a model provider is configured. It is
    # not, in a test database, and that is a question about setup rather than
    # about the route under test.
    from app.services import readiness

    async def _ready(_session, *_kinds):
        return None

    monkey = pytest.MonkeyPatch()
    monkey.setattr(readiness, "require_ready", _ready)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.maker = maker  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()
    monkey.undo()
    await engine.dispose()


class TestBuildingManyAtOnce:
    """One request, several companies, run concurrently.

    The browser ran these one at a time so the progress line could say "3 of
    8". Honest, and unusable at scale: a hundred contacts across sixty
    companies meant sixty calls end to end before drafting even began.
    """

    @staticmethod
    def _stub_build(monkeypatch, seen: list | None = None):
        """The orchestration is what is under test, not the argument itself."""
        async def build(session, campaign, account, **kw):
            if seen is not None:
                seen.append(account.id)
            return campaign_strategy.BuildOutcome(
                account.id, account.name, built=True, version=1, pursued=[account.name],
            )

        monkeypatch.setattr(campaign_strategy, "build", build)

    async def test_one_failure_does_not_cost_the_companies_beside_it(
        self, session, live, api, monkeypatch
    ):
        """Each company gets its own session, so a rollback is its own."""
        self._stub_build(monkeypatch)
        async with api.maker() as s:
            w = await campaign_world(s)
            await s.commit()
            ids = {"campaign": w.campaign.id, "account": w.account.id}

        r = await api.post(
            f"/api/campaigns/{ids['campaign']}/strategy/batch",
            json={
                "account_ids": [str(ids["account"]), str(uuid.uuid4())],
                "pursue_anyway": [],
                "allow_without_signal": [],
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["built"] == 1, "the real company was built"
        assert body["failed"] == 1, "the unknown one failed, alone"
        assert isinstance(body["seconds"], (int, float))

    async def test_the_same_company_twice_is_built_once(
        self, session, live, api, monkeypatch
    ):
        seen: list = []
        self._stub_build(monkeypatch, seen)
        async with api.maker() as s:
            w = await campaign_world(s)
            await s.commit()
            ids = {"campaign": w.campaign.id, "account": w.account.id}

        r = await api.post(
            f"/api/campaigns/{ids['campaign']}/strategy/batch",
            json={"account_ids": [str(ids["account"]), str(ids["account"])]},
        )
        assert r.status_code == 200
        assert len(seen) == 1, "a repeated company is a repeated bill, not a repeated build"

    def test_the_concurrency_is_bounded(self):
        """Each call is a paid request against a rate limit, and a failure
        should cost a few calls rather than a hundred."""
        from app.api.campaign_strategy import BUILD_CONCURRENCY

        assert 1 < BUILD_CONCURRENCY <= 10


class TestBuilding:
    async def test_by_default_only_the_pursued_get_a_strategy(self, session, live):
        w = await campaign_world(session)
        out = await campaign_strategy.build(session, w.campaign, w.account, synthesise=proposer())
        assert out.built and out.pursued == ["Enrico Bergamo"]
        assert [e["name"] for e in out.excluded] == ["Ada User"]
        assert "below the threshold" in out.excluded[0]["reason"]

        thread = await thread_of(session, w, w.cto)
        assert thread is not None and not thread.chosen_by_rep and not thread.without_live_trigger
        strategy = await session.get(Strategy, thread.strategy_id)
        assert (strategy.campaign_id, strategy.service_id, strategy.icp_profile_id) == (
            w.campaign.id, w.service.id, w.profile.id)
        assert await thread_of(session, w, w.user) is None

    async def test_pursue_anyway_is_recorded_and_read_in_approval(self, session, live):
        w = await campaign_world(session)
        out = await campaign_strategy.build(
            session, w.campaign, w.account, pursue_anyway={w.user.id}, synthesise=proposer())
        assert out.overridden == ["Ada User"]
        thread = await thread_of(session, w, w.user)
        assert thread.chosen_by_rep and thread.thread_status == "active_secondary"
        reasons = approval.flag_reasons(approval.Candidate(sequence_id=uuid.uuid4(), chosen_by_rep=True))
        assert any("chosen by a rep" in r for r in reasons)

    async def test_an_answer_about_nobody_we_asked_for_is_retried_once(self, session, live):
        """Measured, not assumed: the same request returned one sound thread on
        411 output tokens and nothing usable on 790, minutes apart.

        "Nothing usable" used to mean an empty `threads` list. `min_length=1`
        on the contract now refuses that at parse time, so the useless answer
        that remains is one carrying threads for somebody we never asked
        about — it satisfies the schema, is discarded, and leaves the rep told
        that nothing came back for their person."""
        w = await campaign_world(session)
        calls: list = []
        good = proposer()

        async def flaky(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return SimpleNamespace(parsed=_about_a_stranger())
            return await good(**kwargs)

        out = await campaign_strategy.build(
            session, w.campaign, w.account, synthesise=flaky)
        assert len(calls) == 2, "the first empty answer was retried"
        assert out.built and out.pursued == ["Enrico Bergamo"]

    async def test_two_useless_answers_are_reported_as_the_provider_failing(self, session, live):
        """Not "no case was argued for them", which reads as a judgement and
        sends a rep looking for their own mistake."""
        w = await campaign_world(session)

        async def always_empty(**kwargs):
            return SimpleNamespace(parsed=_about_a_stranger())

        out = await campaign_strategy.build(
            session, w.campaign, w.account, synthesise=always_empty)
        assert not out.built
        reason = next(e["reason"] for e in out.excluded if e["name"] == "Enrico Bergamo")
        assert "provider failure" in reason
        assert "not a decision about this person" in reason

    async def test_a_withdrawn_person_is_not_argued_for(self, session, live):
        """Found live: a rep withdrew somebody, then could not build for them.

        The Strategy tab listed them like anybody else, the build asked the
        model for their case anyway, the model declined — and the only
        explanation offered was "the model returned no case for them". The
        withdrawal was the answer the whole time, and nothing said so.
        """
        w = await campaign_world(session)
        seq = (await session.execute(
            select(OutreachSequence).where(
                OutreachSequence.campaign_id == w.campaign.id,
                OutreachSequence.contact_id == w.cto.id,
            )
        )).scalar_one()
        await promotion.withdraw(session, seq, reason="wrong person")

        out = await campaign_strategy.build(
            session, w.campaign, w.account, synthesise=proposer())
        excluded = {e["name"]: e["reason"] for e in out.excluded}
        assert "Enrico Bergamo" in excluded
        assert "withdrawn from this campaign" in excluded["Enrico Bergamo"]
        assert "wrong person" in excluded["Enrico Bergamo"]
        assert await thread_of(session, w, w.cto) is None

    async def test_an_override_cannot_pull_a_withdrawn_person_back_in(self, session, live):
        """Withdrawal is a decision, not a score to be overridden."""
        w = await campaign_world(session)
        seq = (await session.execute(
            select(OutreachSequence).where(
                OutreachSequence.campaign_id == w.campaign.id,
                OutreachSequence.contact_id == w.user.id,
            )
        )).scalar_one()
        await promotion.withdraw(session, seq, reason="left the company")

        out = await campaign_strategy.build(
            session, w.campaign, w.account, pursue_anyway={w.user.id}, synthesise=proposer())
        assert "Ada User" not in out.pursued and "Ada User" not in out.overridden
        assert any("withdrawn" in e["reason"] for e in out.excluded if e["name"] == "Ada User")

    async def test_the_people_view_says_who_is_withdrawn(self, session, live):
        w = await campaign_world(session)
        seq = (await session.execute(
            select(OutreachSequence).where(
                OutreachSequence.campaign_id == w.campaign.id,
                OutreachSequence.contact_id == w.user.id,
            )
        )).scalar_one()
        await promotion.withdraw(session, seq, reason="duplicate")

        view = await campaign_strategy.people_view(session, w.campaign)
        rows = {p["full_name"]: p for p in view["people"]}
        assert rows["Ada User"]["withdrawn"] is True
        assert rows["Ada User"]["withdraw_reason"] == "duplicate"
        assert rows["Enrico Bergamo"]["withdrawn"] is False

    async def test_the_model_is_not_told_who_the_rules_left_out(self, session, live):
        """It dropped them when it knew. The flag is governance, not an instruction."""
        w = await campaign_world(session)
        calls: list = []
        await campaign_strategy.build(
            session, w.campaign, w.account, pursue_anyway={w.user.id}, synthesise=proposer(calls))
        [asked] = calls
        people = asked["people"]
        assert {p["contact_id"] for p in people} == {str(w.cto.id), str(w.user.id)}, "everyone chosen is argued"
        # The gates decide who proceeds and stop there (docs/18): no override,
        # no weight, no rank, no thread status reaches the model.
        for gate in ("chosen_by_rep", "weight", "rank", "thread_status", "start_offset_days"):
            assert all(gate not in p for p in people), gate
        assert (await thread_of(session, w, w.user)).chosen_by_rep, "still recorded on the thread"

    async def test_without_a_live_signal_nobody_is_built_unless_allowed(self, session, live):
        w = await campaign_world(session)
        live.signals = []
        out = await campaign_strategy.build(session, w.campaign, w.account, synthesise=proposer())
        assert not out.built and "no live signal" in reasons(out)["Enrico Bergamo"]

        out = await campaign_strategy.build(
            session, w.campaign, w.account, allow_without_signal={w.cto.id}, synthesise=proposer())
        assert out.built and out.without_trigger == ["Enrico Bergamo"]
        thread = await thread_of(session, w, w.cto)
        assert thread.without_live_trigger and thread.trigger_signal_ids == []

    async def test_a_cited_trigger_that_is_not_live_is_not_accepted(self, session, live):
        w = await campaign_world(session)
        live.signals = [fake_signal()]
        out = await campaign_strategy.build(session, w.campaign, w.account, synthesise=proposer())
        assert not out.built and "cited no live signal" in reasons(out)["Enrico Bergamo"]

    async def test_a_rebuild_supersedes_and_unlinks_whoever_it_leaves_out(self, session, live):
        w = await campaign_world(session)
        first = await campaign_strategy.build(
            session, w.campaign, w.account, pursue_anyway={w.user.id}, synthesise=proposer())
        old = (await thread_of(session, w, w.user)).strategy_id
        second = await campaign_strategy.build(session, w.campaign, w.account, synthesise=proposer())
        assert second.version == first.version + 1
        assert (await session.get(Strategy, old)).status == "superseded"
        assert await thread_of(session, w, w.user) is None

    async def test_the_campaign_strategy_wins_over_a_company_wide_one(self, session, live):
        w = await campaign_world(session)
        legacy = Strategy(account_id=w.account.id, version=1)
        session.add(legacy)
        await session.flush()
        old = StrategyThread(
            strategy_id=legacy.id, contact_id=w.cto.id, service_id=w.service.id, weight=60, rank=1,
            thread_status="active_primary", problem_hypothesis="old", trigger_summary="t",
            trigger_signal_ids=[str(uuid.uuid4())], positioning="p", channel_sequence=["email"], cta="c",
        )
        session.add(old)
        await session.flush()
        assert (await promotion.pursued_thread_for(session, w.cto, campaign_id=w.campaign.id)).id == old.id

        await campaign_strategy.build(session, w.campaign, w.account, synthesise=proposer())
        current = await promotion.pursued_thread_for(session, w.cto, campaign_id=w.campaign.id)
        assert current.id != old.id and current.problem_hypothesis.startswith("hurts")
        assert (await promotion.pursued_thread_for(session, w.cto)).id == old.id


# ---------------------------------------------------------------------------
# ranked angles (docs/18)
# ---------------------------------------------------------------------------
def _angle(name, *, signal=SIGNAL, proof=(), confidence=0.5):
    return StrategyAngle(
        angle=name, problem_hypothesis=f"h-{name}", why_now=f"w-{name}",
        trigger_signal_ids=[str(signal)], positioning=f"p-{name}", cta="c",
        proof_point_ids=[str(p) for p in proof], confidence=confidence,
    )


def _answer(people, angles, order, account_angle=None):
    return SimpleNamespace(parsed=StrategyProposal(people=[PersonAngles(
        contact_id=people[0]["contact_id"], angles=angles, recommended_order=order,
        why_this_order="the fresher signal leads",
    )], account_angle=account_angle))


async def _sequence_of(session, w, contact):
    return (await session.execute(select(OutreachSequence).where(
        OutreachSequence.campaign_id == w.campaign.id, OutreachSequence.contact_id == contact.id,
    ))).scalar_one()


class TestRankedAngles:
    async def test_every_angle_is_kept_ranked_and_the_top_one_is_pitched(self, session, live):
        """The thread mirrors the selected angle, so everything downstream reads it as before."""
        w = await campaign_world(session)
        approved = ProofPoint(service_id=w.service.id, kind="case_study", title="Approved win", body="b",
                              is_approved=True)
        unapproved = ProofPoint(service_id=w.service.id, kind="case_study", title="Not approved", body="b",
                                is_approved=False)
        session.add_all([approved, unapproved])
        await session.flush()

        async def synthesise(*, account, payload, people):
            return _answer(people, [
                _angle("second best", proof=[unapproved.id], confidence=0.6),
                _angle("best", proof=[approved.id, unapproved.id], confidence=0.9),
                _angle("stale", signal=uuid.uuid4()),
            ], [1, 0, 2], account_angle="Scaling fast.")

        out = await campaign_strategy.build(session, w.campaign, w.account, synthesise=synthesise)
        assert out.built
        thread = await thread_of(session, w, w.cto)
        angles = (await session.execute(
            select(StrategyAngle_).where(StrategyAngle_.thread_id == thread.id).order_by(StrategyAngle_.rank)
        )).scalars().all()
        # The angle citing a signal that is not live is dropped; the rest keep the model's order.
        assert [a.angle for a in angles] == ["best", "second best"]
        assert [a.is_selected for a in angles] == [True, False]
        assert angles[0].selected_by == "auto"
        assert angles[0].why_this_order == "the fresher signal leads"
        # Unapproved proof never reaches storage (invariant 8).
        assert angles[0].proof_point_ids == [str(approved.id)]
        assert angles[1].proof_point_ids == []
        assert (thread.problem_hypothesis, thread.positioning, thread.trigger_summary) == (
            "h-best", "p-best", "w-best",
        )
        assert thread.channel_sequence == [], "channels are the cadence's, not strategy's"
        assert (await session.get(Strategy, thread.strategy_id)).account_angle == "Scaling fast."

    async def test_a_rep_can_pitch_another_angle_and_saved_drafts_reopen(self, session, live):
        w = await campaign_world(session)

        async def synthesise(*, account, payload, people):
            return _answer(people, [_angle("first"), _angle("second")], [0, 1])

        await campaign_strategy.build(session, w.campaign, w.account, synthesise=synthesise)
        thread = await thread_of(session, w, w.cto)
        sequence = await _sequence_of(session, w, w.cto)
        sequence.status = "pending_approval"  # drafts saved for approval
        second = (await session.execute(select(StrategyAngle_).where(
            StrategyAngle_.thread_id == thread.id, StrategyAngle_.rank == 2,
        ))).scalar_one()

        r = await campaign_strategy.select_angle(session, w.campaign, w.cto.id, second.id)
        assert r["changed"] is True
        await session.refresh(thread)
        assert (thread.problem_hypothesis, thread.trigger_summary) == ("h-second", "w-second")
        assert second.is_selected and second.selected_by == "rep"
        assert sequence.status == "draft", "drafts argued the old angle and need saving again"

        with pytest.raises(campaign_strategy.AngleRefused):
            await campaign_strategy.select_angle(session, w.campaign, w.cto.id, uuid.uuid4())

    async def test_drafting_is_given_the_pitched_angle_and_its_proof(self, session, live):
        w = await campaign_world(session)
        approved = ProofPoint(service_id=w.service.id, kind="case_study", title="Approved win", body="body",
                              is_approved=True)
        session.add(approved)
        await session.flush()
        seen = {}

        async def synthesise(*, account, payload, people):
            seen.update(payload)
            return _answer(people, [_angle("the way in", proof=[approved.id])], [0], account_angle="One read.")

        await campaign_strategy.build(session, w.campaign, w.account, synthesise=synthesise)
        # The whole picture reached the model: the campaign's ICP, its service, its proof.
        assert seen["icp"]["personas"] and seen["service"]["code"] == w.service.code
        assert [p["title"] for p in seen["proof_points"]] == ["Approved win"]

        thread = await thread_of(session, w, w.cto)
        payload = await campaign_drafts._thread_payload(session, thread)
        assert payload["angle"] == "the way in"
        assert [p["title"] for p in payload["proof_to_use"]] == ["Approved win"]
        assert payload["account_angle"] == "One read."
        assert "channel_sequence" not in payload


class TestSignalRanking:
    def test_fresh_beats_stale_and_the_icp_and_the_person_count(self):
        from app.services.strategy_context import ranked

        today = date.today()

        def sig(days, kind="product_launch"):
            s = fake_signal()
            s.observed_at, s.signal_type = today - timedelta(days=days), kind
            return s

        fresh, stale = sig(2), sig(180)
        order = [s for _, _, _, s in ranked([stale, fresh], matters=set(), about_person=False, today=today)]
        assert order == [fresh, stale]

        listed, unlisted = sig(30, "m_and_a_integration"), sig(30, "product_launch")
        order = [s for _, _, _, s in ranked(
            [unlisted, listed], matters={"m_and_a_integration"}, about_person=False, today=today,
        )]
        assert order[0] is listed, "a type the ICP lists outranks an equal one it does not"

        [(_, alone, _, _)] = ranked([sig(10)], matters=set(), about_person=False, today=today)
        [(_, mine, _, _)] = ranked([sig(10)], matters=set(), about_person=True, today=today)
        assert mine > alone


class TestAngleOrder:
    def test_a_malformed_order_keeps_every_angle_once(self):
        angles = [StrategyAngle(angle=n, problem_hypothesis="h", why_now="w", positioning="p", cta="c")
                  for n in "abc"]
        person = PersonAngles(contact_id=uuid.uuid4(), angles=angles, recommended_order=[2, 2, 9],
                              why_this_order="o")
        assert [x.angle for x in person.ordered()] == ["c", "a", "b"]


class TestTitlesAreClassifiedOnWrite:
    async def test_a_new_contact_gets_a_role_and_a_set_one_is_kept(self, session):
        account = Account(name=f"Acme {tag()}", domain=f"acme-{tag()}.example")
        session.add(account)
        await session.flush()
        founder = Contact(account_id=account.id, full_name="F", title="Founder and CTO")
        chosen = Contact(account_id=account.id, full_name="C", title="CTO", buying_role="champion")
        session.add_all([founder, chosen])
        await session.flush()
        assert (founder.seniority, founder.buying_role) == ("c_level", "economic_buyer")
        assert chosen.buying_role == "champion", "a role somebody set is not overwritten"


class TestTheRealCallPath:
    async def test_the_default_synthesiser_calls_the_stage_with_what_it_takes(self, session, live, monkeypatch):
        """Every other test injects `synthesise`, so none exercised the default
        one — which passed `people` on to a stage that does not take it. The
        live rerun found that; this holds it."""
        from app.services import stages

        w = await campaign_world(session)
        seen = {}

        async def stage(_session, **kwargs):
            seen.update(kwargs)
            return _answer(kwargs["payload"]["people"], [_angle("the way in")], [0])

        monkeypatch.setattr(stages, "synthesise_strategy", stage)
        out = await campaign_strategy.build(session, w.campaign, w.account)
        assert out.built
        assert set(seen) == {"account", "payload"}
