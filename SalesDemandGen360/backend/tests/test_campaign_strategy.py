"""Qualification and strategy per campaign, against the campaign's service and ICP.

The service and ICP are chosen with the queue and copied into the campaign.
The sales rules decide who is pursued by default; a rep may pursue someone the
rules leave out, or allow a strategy without a live signal — both recorded on
the thread, and both send the sequence to be read in approval.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.account import Account, Contact
from app.models.campaign import CadenceShape, CampaignQueue, OutreachSequence
from app.models.config import IcpProfile, IcpProfileVersion, ServiceCatalog, service_icp_link
from app.models.context import AccountContext
from app.models.strategy import Strategy, StrategyThread
from app.schemas.strategy import ProposedThread, StrategyProposal
from app.services import approval, campaign_strategy, promotion
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


@pytest.fixture
def live(monkeypatch):
    """A live company signal by default; set `.signals = []` for none."""
    state = SimpleNamespace(signals=[SimpleNamespace(id=SIGNAL, strength="high", contact_id=None)])

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


def proposer(calls=None):
    async def synthesise(*, account, context, threads, contacts):
        if calls is not None:
            calls.append(threads)
        return SimpleNamespace(parsed=StrategyProposal(threads=[
            ProposedThread(
                contact_id=t["contact_id"], service_id=t["service_id"],
                problem_hypothesis=f"hurts differently for {t['contact_id']}", trigger_summary="Series B",
                trigger_signal_ids=[] if t["may_cite_no_live_signal"] else [str(SIGNAL)],
                positioning="p", channel_sequence=["email"], cta="15 minutes",
            )
            for t in threads
        ]))
    return synthesise


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

    async def test_an_empty_answer_is_retried_once(self, session, live):
        """Measured, not assumed: the same request returned one sound thread on
        411 output tokens and an empty list on 790, minutes apart. Returning
        nothing is a contract violation, not an opinion — the prompt asks for
        one thread per entry and says who was decided before the call."""
        w = await campaign_world(session)
        calls: list = []
        good = proposer()

        async def flaky(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return SimpleNamespace(parsed=StrategyProposal(threads=[]))
            return await good(**kwargs)

        out = await campaign_strategy.build(
            session, w.campaign, w.account, synthesise=flaky)
        assert len(calls) == 2, "the first empty answer was retried"
        assert out.built and out.pursued == ["Enrico Bergamo"]

    async def test_two_empty_answers_are_reported_as_the_provider_failing(self, session, live):
        """Not "no case was argued for them", which reads as a judgement and
        sends a rep looking for their own mistake."""
        w = await campaign_world(session)

        async def always_empty(**kwargs):
            return SimpleNamespace(parsed=StrategyProposal(threads=[]))

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
        assert {t["contact_id"] for t in asked} == {w.cto.id, w.user.id}, "everyone chosen is argued"
        assert all("chosen_by_rep" not in t for t in asked)
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
        live.signals = [SimpleNamespace(id=uuid.uuid4(), strength="high", contact_id=None)]
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
