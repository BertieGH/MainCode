"""Cadence drafts on the outreach screen, and the company score read per ICP.

Drafts are written from a person's strategy onto the cadence chosen at
promotion; a rep's edit is a new version; saving sends the person for approval;
any change after that returns them to draft, so an approval never covers words
nobody approved. Qualification stays with the company and is read per ICP.
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
from app.models.config import (
    IcpProfile,
    IcpProfileVersion,
    ScoringConfig,
    ServiceCatalog,
    service_icp_link,
)
from app.models.content import Touch
from app.models.context import AccountContext, Qualification
from app.models.governance import Approval
from app.schemas.draft import DraftSet, TouchDraft
from app.schemas.qualification import DIMENSIONS
from app.schemas.strategy import ProposedThread, StrategyProposal
from app.services import approval, campaign_drafts, campaign_strategy, icp_scores, promotion
from app.services.campaign_drafts import DraftingRefusedError
from app.services.campaign_strategy import Rules

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


@pytest.fixture(autouse=True)
def rules_and_signals(monkeypatch):
    async def fixed(_session):
        return Rules(threshold=20, cap=2, offset=3, role_weights={"technical_buyer": 60, "influencer": 10})

    async def signals(_session, _account_id, **_):
        return [SimpleNamespace(id=SIGNAL, strength="high", contact_id=None)]

    monkeypatch.setattr(campaign_strategy, "sales_rules", fixed)
    monkeypatch.setattr(campaign_strategy.context_service, "live_signals", signals)


def tag() -> str:
    return uuid.uuid4().hex[:6]


async def world(session):
    service = ServiceCatalog(code=f"s{tag()}", name="EIA", description="d")
    profile = IcpProfile(name=f"icp-{tag()}")
    session.add_all([service, profile])
    await session.flush()
    session.add(IcpProfileVersion(
        icp_profile_id=profile.id, version=1, is_active=True,
        definition={"personas": [{"buying_role": "technical_buyer", "titles": ["CTO"]}]},
    ))
    await session.execute(service_icp_link.insert().values(service_id=service.id, icp_profile_id=profile.id))
    account = Account(name=f"Datadog {tag()}", domain=f"dd-{tag()}.example", resolution_status="resolved")
    session.add(account)
    await session.flush()
    session.add(AccountContext(account_id=account.id, version=1, payload={}, signal_ids=[]))
    cto = Contact(account_id=account.id, full_name="Enrico Bergamo", title="CTO", buying_role="technical_buyer",
                  email=f"e{tag()}@{account.domain}", email_status="verified")
    analyst = Contact(account_id=account.id, full_name="Ada User", title="Analyst", buying_role="influencer",
                      email=f"a{tag()}@{account.domain}", email_status="verified")
    shape = CadenceShape(
        lgm_audience_name="Gen360 · Tests", key=f"shape_{tag()}", label="Short", lgm_campaign_id="lgm-1", touch_count=3, span_days=10,
        attribute_map={str(i): f"custom_attribute_{i}" for i in range(1, 4)}, attributes_used=3,
        verified_at=datetime.now(UTC) - timedelta(days=1), verified_by="tests", lgm_status="active", active=True,
    )
    session.add_all([cto, analyst, shape])
    await session.flush()
    queue = CampaignQueue(label="EIA", status="draft", service_id=service.id, icp_profile_id=profile.id, icp_version=1)
    session.add(queue)
    await session.flush()
    for c in (cto, analyst):
        await promotion.add_contact(session, queue_id=queue.id, contact_id=c.id)
    campaign = await promotion.promote(session, queue_ids=[queue.id], label="EIA", cadence_shape_id=shape.id)

    async def propose(*, account, context, threads, contacts):
        return SimpleNamespace(parsed=StrategyProposal(threads=[
            ProposedThread(
                contact_id=t["contact_id"], service_id=t["service_id"], problem_hypothesis="IT is stretched",
                trigger_summary="Series B", trigger_signal_ids=[str(SIGNAL)], positioning="p",
                channel_sequence=["email"], cta="15 minutes",
            )
            for t in threads
        ]))

    await campaign_strategy.build(session, campaign, account, synthesise=propose)
    sequences = {
        s.contact_id: s
        for s in (await session.execute(
            select(OutreachSequence).where(OutreachSequence.campaign_id == campaign.id))).scalars()
    }
    return SimpleNamespace(service=service, profile=profile, account=account, cto=cto, analyst=analyst,
                           shape=shape, campaign=campaign, enrico=sequences[cto.id], ada=sequences[analyst.id])


def drafter(prefix="body"):
    async def draft(*, account, contact, thread, shape, signals):
        assert shape["touch_count"] == 3 and thread["problem_hypothesis"] == "IT is stretched"
        return SimpleNamespace(model="fake", parsed=DraftSet(touches=[
            TouchDraft(step_no=i, day_offset=[0, 3, 8][i - 1], channel="email", purpose=f"step {i}",
                       body=f"{prefix} {i}", signal_dependence="durable")
            for i in (1, 2, 3)
        ]))
    return draft


def drafter_with_subject():
    """An arc whose first touch carries a subject line of ours."""

    async def draft(*, account, contact, thread, shape, signals):
        return SimpleNamespace(model="fake", parsed=DraftSet(touches=[
            TouchDraft(step_no=i, day_offset=[0, 3, 8][i - 1], channel="email",
                       purpose=f"step {i}", body=f"body {i}",
                       subject="A subject" if i == 1 else None,
                       signal_dependence="durable")
            for i in (1, 2, 3)
        ]))

    return draft


def drafter_for(count: int):
    """A drafter that fills whatever cadence it is handed."""

    async def draft(*, account, contact, thread, shape, signals):
        return SimpleNamespace(model="fake", parsed=DraftSet(touches=[
            TouchDraft(step_no=i, day_offset=(i - 1) * 3, channel="email", purpose=f"step {i}",
                       body=f"body {i}", signal_dependence="durable")
            for i in range(1, count + 1)
        ]))

    return draft


class TestTheArcMustFitTheCampaignsCadence:
    """An LGM campaign is one sequence: six steps or four, never both."""

    async def test_an_arc_shorter_than_the_cadence_cannot_be_saved(self, session):
        from app.models.campaign import CadenceShape

        w = await world(session)
        await campaign_drafts.write(session, w.enrico, draft=drafter())

        # The campaign is moved to a longer cadence after the drafts were
        # written — the shape a person was drafted for is no longer the one
        # that will send, and steps 4 and 5 would go out holding old copy.
        longer = CadenceShape(
            key=f"shape_{tag()}", label="Longer", lgm_campaign_id="lgm-2", touch_count=5,
            span_days=14, attribute_map={str(i): f"custom_attribute_{i}" for i in range(1, 6)},
            attributes_used=5, verified_at=datetime.now(UTC) - timedelta(days=1),
            verified_by="tests", lgm_status="active", lgm_audience_name="Gen360 · Tests", active=True,
        )
        session.add(longer)
        await session.flush()
        w.campaign.cadence_shape_id = longer.id
        await session.flush()

        with pytest.raises(DraftingRefusedError, match="3 touches drafted"):
            await campaign_drafts.save(session, w.enrico)

        # Writing again drafts for the cadence that will actually send.
        assert await campaign_drafts.write(session, w.enrico, draft=drafter_for(5)) == 5
        await campaign_drafts.save(session, w.enrico)
        assert w.enrico.status == "pending_approval"


class TestWriting:
    async def test_no_strategy_no_drafts(self, session):
        w = await world(session)
        with pytest.raises(DraftingRefusedError, match="no strategy"):
            await campaign_drafts.write(session, w.ada, draft=drafter())

    async def test_drafts_fill_the_cadence_and_wait_to_be_saved(self, session):
        w = await world(session)
        assert await campaign_drafts.write(session, w.enrico, draft=drafter()) == 3
        rows = {r["full_name"]: r for r in await campaign_drafts.rows(session, w.campaign)}
        assert (rows["Enrico Bergamo"]["state"], rows["Enrico Bergamo"]["touch_count"]) == ("drafted", 3)
        assert rows["Enrico Bergamo"]["cadence_label"] == "Short"
        assert rows["Ada User"]["state"] == "strategy_needed"

    async def test_a_rewrite_adds_a_version_to_every_touch(self, session):
        w = await world(session)
        await campaign_drafts.write(session, w.enrico, draft=drafter())
        await campaign_drafts.write(session, w.enrico, draft=drafter("again"))
        arc = await campaign_drafts.arc_of(session, w.enrico.id)
        assert [(d.version, d.generated_as, d.body) for _, d in arc][0] == (2, "regeneration", "again 1")


class TestEditingAndApproval:
    async def test_saving_then_approving_counts(self, session):
        w = await world(session)
        await campaign_drafts.write(session, w.enrico, draft=drafter())
        await campaign_drafts.save(session, w.enrico)
        assert w.enrico.status == "pending_approval"
        assert await campaign_drafts.approved_ids(session, [w.enrico]) == set()

        session.add(Approval(subject_type="outreach_sequence", subject_id=w.enrico.id, decision="approve",
                             reviewer_id="tests", review_depth="individual"))
        w.enrico.status = "approved"
        await session.flush()
        assert await campaign_drafts.approved_ids(session, [w.enrico]) == {w.enrico.id}

    async def test_an_edit_is_a_new_version_and_reopens_approval(self, session):
        w = await world(session)
        await campaign_drafts.write(session, w.enrico, draft=drafter())
        await campaign_drafts.save(session, w.enrico)
        session.add(Approval(subject_type="outreach_sequence", subject_id=w.enrico.id, decision="approve",
                             reviewer_id="tests", review_depth="individual"))
        w.enrico.status = "approved"
        await session.flush()

        await campaign_drafts.edit_touch(session, w.enrico, 2, subject=None, body="My own words")
        versions = await campaign_drafts.versions(session, w.enrico.id, 2)
        assert [(v.version, v.generated_as, v.is_current) for v in versions] == [
            (2, "rep_edit", True), (1, "arc", False)]
        assert w.enrico.status == "draft"
        assert await campaign_drafts.approved_ids(session, [w.enrico]) == set(), "the old approval no longer counts"
        assert campaign_drafts.edited(await campaign_drafts.arc_of(session, w.enrico.id))
        reasons = approval.flag_reasons(approval.Candidate(sequence_id=w.enrico.id, edited_by_rep=True))
        assert any("edited by you" in r for r in reasons)

    async def test_nothing_changes_once_enrolled(self, session):
        w = await world(session)
        await campaign_drafts.write(session, w.enrico, draft=drafter())
        w.enrico.status = "executing"
        with pytest.raises(DraftingRefusedError, match="frozen"):
            await campaign_drafts.edit_touch(session, w.enrico, 1, subject=None, body="late")

    async def test_saving_needs_drafts(self, session):
        w = await world(session)
        with pytest.raises(DraftingRefusedError, match="not been drafted"):
            await campaign_drafts.save(session, w.enrico)


class TestTheCompanyScoreReadPerIcp:
    async def test_one_assessment_scores_each_icp_without_a_model_call(self, session):
        if (await session.execute(select(ScoringConfig).where(ScoringConfig.is_active.is_(True)))).scalar_one_or_none() is None:
            session.add(ScoringConfig(
                version=9000 + int(tag(), 16) % 1000, is_active=True,
                dimension_weights={"fit": 20, "opportunity": 20, "buyer": 15,
                                   "commercial": 15, "intent": 20, "engagement": 10},
                industry_multipliers={}, size_multipliers={}, persona_role_weights={},
                band_cutoffs={"high": 75, "medium": 50}, man_view_enabled=False,
            ))
            await session.flush()
        w = await world(session)
        other = IcpProfile(name=f"cfo-{tag()}")
        session.add(other)
        await session.flush()
        session.add(IcpProfileVersion(icp_profile_id=other.id, version=1, is_active=True,
                                      definition={"personas": [{"buying_role": "economic_buyer", "titles": ["CFO"]}]}))
        reasons = {d: {"score": 60, "reason": "judged", "evidence_ids": [], "basis": "evidence"} for d in DIMENSIONS}
        session.add(Qualification(account_id=w.account.id, priority_score=60, priority_band="medium",
                                  reasons=reasons, scoring_config_version=1))
        await session.flush()

        cto_icp = await icp_scores.score_for(session, w.account.id, w.profile.id)
        cfo_icp = await icp_scores.score_for(session, w.account.id, other.id)
        buyer = {s.icp_name: next(d["score"] for d in s.dimensions if d["dimension"] == "buyer")
                 for s in (cto_icp, cfo_icp)}
        assert buyer[w.profile.name] > buyer[other.name] == 0, "the CTO is there; no CFO is"
        assert cto_icp.priority_score > cfo_icp.priority_score
        assert await promotion.latest_band(session, w.account.id, w.profile.id) == cto_icp.priority_band


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
    async def test_approving_unsaved_drafts_is_refused_and_an_edit_is_saved(self, api):
        async with api.maker() as s:
            w = await world(s)
            await campaign_drafts.write(s, w.enrico, draft=drafter())
            await s.commit()
            ids = {"seq": w.enrico.id, "campaign": w.campaign.id}

        r = await api.post(f"/api/sequences/{ids['seq']}/decision", json={"decision": "approve"})
        assert r.status_code == 409 and "save" in r.text

        r = await api.put(f"/api/sequences/{ids['seq']}/touches/1", json={"subject": None, "body": "Edited"})
        assert r.status_code == 200, r.text
        arc = r.json()
        assert arc["edited"] and arc["touches"][0]["generated_as"] == "rep_edit" and arc["state"] == "drafted"

        r = await api.post(f"/api/sequences/{ids['seq']}/save")
        assert r.status_code == 200 and r.json()["state"] == "saved"
        r = await api.post(f"/api/sequences/{ids['seq']}/decision", json={"decision": "approve"})
        assert r.status_code == 200
        approval_view = (await api.get(f"/api/campaigns/{ids['campaign']}/approval")).json()
        assert [c["contact_name"] for c in approval_view["flagged"]] == ["Enrico Bergamo"]
        [waiting] = approval_view["waiting"]
        assert (waiting["name"], waiting["state"], waiting["withdrawn"]) == (
            "Ada User", "strategy needed", False,
        )
        assert waiting["sequence_id"] and waiting["contact_id"], "the list can act on them"

        rows = (await api.get(f"/api/campaigns/{ids['campaign']}/drafts")).json()
        assert {r["full_name"]: r["state"] for r in rows} == {"Enrico Bergamo": "approved", "Ada User": "strategy_needed"}


class TestMovingACampaignToAnotherCadence:
    """An LGM campaign can be deleted and rebuilt. The work behind it survives.

    That is the case this exists for: the registration dies with the campaign,
    while the strategy and approved drafts are still perfectly good. Before
    this the only way forward was to build the campaign again and lose them.
    """

    async def _other_shape(self, session, **over):
        base = dict(
            key=f"other_{tag()}", label="Other", lgm_campaign_id=f"lgm-{tag()}", touch_count=3,
            attribute_map={str(i): f"custom_attribute_{i}" for i in range(1, 4)},
            attributes_used=3, lgm_audience_name="Gen360 · Other", lgm_status="active",
            verified_at=datetime.now(UTC), verified_by="tests", active=True,
        )
        shape = CadenceShape(**{**base, **over})
        session.add(shape)
        await session.flush()
        return shape

    async def test_the_campaign_and_its_sequences_move_together(self, session):
        w = await world(session)
        await campaign_drafts.write(session, w.enrico, draft=drafter())
        replacement = await self._other_shape(session)

        result = await promotion.change_cadence(
            session, campaign_id=w.campaign.id, shape_id=replacement.id
        )
        assert result["changed"] and result["sequences"] == 2
        await session.refresh(w.campaign)
        assert w.campaign.cadence_shape_id == replacement.id
        assert w.enrico.cadence_shape_id == replacement.id

    async def test_touches_are_re_pointed_at_the_new_shapes_attributes(self, session):
        """The silent failure this prevents: the same words, the right person,
        written into a step whose template reads a different attribute."""
        w = await world(session)
        await campaign_drafts.write(session, w.enrico, draft=drafter())
        shifted = await self._other_shape(
            session, attribute_map={str(i): f"custom_attribute_{i + 3}" for i in range(1, 4)}
        )

        result = await promotion.change_cadence(
            session, campaign_id=w.campaign.id, shape_id=shifted.id
        )
        assert result["touches_remapped"] == 3
        touches = list((await session.execute(
            select(Touch).where(Touch.sequence_id == w.enrico.id).order_by(Touch.step_no)
        )).scalars())
        assert [t.lgm_attribute for t in touches] == [
            "custom_attribute_4", "custom_attribute_5", "custom_attribute_6",
        ]

    async def test_a_different_step_count_is_refused(self, session):
        w = await world(session)
        await campaign_drafts.write(session, w.enrico, draft=drafter())
        longer = await self._other_shape(
            session, touch_count=6,
            attribute_map={str(i): f"custom_attribute_{i}" for i in range(1, 7)},
        )
        with pytest.raises(promotion.CadenceSwapRefused, match="draft them again"):
            await promotion.change_cadence(session, campaign_id=w.campaign.id, shape_id=longer.id)

    async def test_an_unmapped_step_is_refused(self, session):
        w = await world(session)
        await campaign_drafts.write(session, w.enrico, draft=drafter())
        gappy = await self._other_shape(
            session, attribute_map={"1": "custom_attribute_1", "2": "custom_attribute_2"}
        )
        with pytest.raises(promotion.CadenceSwapRefused, match="maps no attribute for step 3"):
            await promotion.change_cadence(session, campaign_id=w.campaign.id, shape_id=gappy.id)

    async def test_anything_already_in_lgm_refuses_the_move(self, session):
        """Its copy is frozen over there; our row would describe a different
        sequence from the one actually running."""
        w = await world(session)
        await campaign_drafts.write(session, w.enrico, draft=drafter())
        w.enrico.status = "executing"
        await session.flush()
        replacement = await self._other_shape(session)

        with pytest.raises(promotion.CadenceSwapRefused, match="frozen"):
            await promotion.change_cadence(
                session, campaign_id=w.campaign.id, shape_id=replacement.id
            )


class TestATouchFollowsItsShapesMapping:
    """A touch's slot is a copy, not a decision — so it follows the shape.

    Seen on screen: an **email** step's body labelled `linkedin 2 body`,
    because the arc was drafted before a template moved in LGM and the
    registration was corrected afterwards. The words would have sent, to the
    right person, in the wrong message.
    """

    async def test_a_moved_slot_is_re_pointed_on_unsent_touches(self, session):
        w = await world(session)
        await campaign_drafts.write(session, w.enrico, draft=drafter())

        w.shape.attribute_map = {"1": "custom_attribute_7", "2": "custom_attribute_8", "3": "custom_attribute_9"}
        await session.flush()
        out = await campaign_drafts.repoint_to_shape(session, w.shape)

        touches = list((await session.execute(
            select(Touch).where(Touch.sequence_id == w.enrico.id).order_by(Touch.step_no)
        )).scalars())
        assert [t.lgm_attribute for t in touches] == [
            "custom_attribute_7", "custom_attribute_8", "custom_attribute_9",
        ]
        assert len(out["moved"]) == 3 and out["frozen"] == 0

    async def test_anything_already_in_lgm_keeps_its_slot(self, session):
        """LGM holds that copy in the old attribute. Changing our row would
        describe a sequence that is not the one running."""
        w = await world(session)
        await campaign_drafts.write(session, w.enrico, draft=drafter())
        w.enrico.status = "executing"
        w.shape.attribute_map = {"1": "custom_attribute_7", "2": "custom_attribute_8", "3": "custom_attribute_9"}
        await session.flush()

        out = await campaign_drafts.repoint_to_shape(session, w.shape)
        touches = list((await session.execute(
            select(Touch).where(Touch.sequence_id == w.enrico.id).order_by(Touch.step_no)
        )).scalars())
        assert [t.lgm_attribute for t in touches] == [
            "custom_attribute_1", "custom_attribute_2", "custom_attribute_3",
        ]
        assert out["moved"] == [] and out["frozen"] == 1

    async def test_a_subject_the_step_can_no_longer_carry_goes_back_to_lgms(self, session):
        w = await world(session)
        w.shape.subject_attribute_map = {"1": "custom_attribute_9"}
        await session.flush()
        await campaign_drafts.write(session, w.enrico, draft=drafter_with_subject())

        w.shape.subject_attribute_map = {}
        await session.flush()
        out = await campaign_drafts.repoint_to_shape(session, w.shape)

        first = (await session.execute(
            select(Touch).where(Touch.sequence_id == w.enrico.id, Touch.step_no == 1)
        )).scalar_one()
        assert first.subject_source == "lgm_template"
        assert any("subject back to LGM" in m for m in out["moved"])

    async def test_a_rewrite_re_points_the_slot_too(self, session):
        """Redrafting updated the words and left the slot, so a corrected
        shape kept sending step 1's body to step 2's attribute however many
        times it was rewritten."""
        w = await world(session)
        await campaign_drafts.write(session, w.enrico, draft=drafter())

        w.shape.attribute_map = {"1": "custom_attribute_7", "2": "custom_attribute_8", "3": "custom_attribute_9"}
        await session.flush()
        await campaign_drafts.write(session, w.enrico, draft=drafter("rewritten"))

        touches = list((await session.execute(
            select(Touch).where(Touch.sequence_id == w.enrico.id).order_by(Touch.step_no)
        )).scalars())
        assert [t.lgm_attribute for t in touches] == [
            "custom_attribute_7", "custom_attribute_8", "custom_attribute_9",
        ]


class TestTheArcSaysWhereItsWordsLand:
    """The binding is the whole integration and it was invisible.

    Gen360 writes each touch into a `customAttributeN` and LGM's step template
    decides which one it reads. A rep reviewing a draft could not tell where
    any of it went — nor that a subject they had written would never appear,
    because the step has nowhere to put it.
    """

    async def _mapped_world(self, s):
        w = await world(s)
        w.shape.attribute_map = {"1": "custom_attribute_3", "2": "custom_attribute_1", "3": "custom_attribute_9"}
        w.shape.subject_attribute_map = {"1": "custom_attribute_2"}
        w.shape.step_channels = {"1": "email", "2": "linkedin", "3": "linkedin"}
        await s.flush()
        return w

    async def test_each_touch_names_its_slot_and_what_we_call_it(self, api):
        async with api.maker() as s:
            w = await self._mapped_world(s)
            await campaign_drafts.write(s, w.enrico, draft=drafter())
            await s.commit()
            seq = w.enrico.id

        arc = (await api.get(f"/api/sequences/{seq}/arc")).json()
        by_step = {t["step_no"]: t for t in arc["touches"]}

        assert by_step[1]["lgm_attribute"] == "custom_attribute_3"
        assert by_step[1]["lgm_attribute_label"] == "email 1 body"
        assert by_step[2]["lgm_attribute_label"] == "linkedin 2 body"
        assert arc["attributes_used"] == 4 and arc["attribute_budget"] == 20

    async def test_only_a_step_with_a_subject_slot_may_carry_one(self, api):
        async with api.maker() as s:
            w = await self._mapped_world(s)
            await campaign_drafts.write(s, w.enrico, draft=drafter())
            await s.commit()
            seq = w.enrico.id

        arc = (await api.get(f"/api/sequences/{seq}/arc")).json()
        by_step = {t["step_no"]: t for t in arc["touches"]}

        assert by_step[1]["subject_allowed"] is True
        assert by_step[1]["subject_attribute"] == "custom_attribute_2"
        assert by_step[1]["subject_attribute_label"] == "email 1 subject"
        assert by_step[2]["subject_allowed"] is False
        assert by_step[2]["subject_attribute"] is None

    async def test_the_channel_lgm_sends_on_travels_beside_the_drafted_one(self, api):
        """They disagree in real data — a touch drafted as a LinkedIn message
        that LGM sends as an email — and the screen shows LGM's."""
        async with api.maker() as s:
            w = await self._mapped_world(s)
            await campaign_drafts.write(s, w.enrico, draft=drafter())
            await s.commit()
            seq = w.enrico.id

        arc = (await api.get(f"/api/sequences/{seq}/arc")).json()
        by_step = {t["step_no"]: t for t in arc["touches"]}
        assert by_step[1]["lgm_channel"] == "email"
        assert by_step[2]["lgm_channel"] == "linkedin"


class TestTheArcSurvivesTheRoundTrip:
    """The bug this exists for: the write succeeded and the *response* failed.

    `touch.day_offset` became nullable when timing went back to LGM, but the
    route's `TouchOut` still declared it `int`. Drafting wrote a perfectly good
    arc, committed it, and then 500'd serialising the reply — so the screen
    said "Could not draft Enrico Bergamo's cadence" about copy that was
    already saved. Service-level tests all passed, because none of them went
    through the route.
    """

    async def test_an_arc_with_no_days_reads_back_through_the_route(self, api):
        async with api.maker() as s:
            w = await world(s)

            async def undated(*, account, contact, thread, shape, signals):
                return SimpleNamespace(model="fake", parsed=DraftSet(touches=[
                    TouchDraft(step_no=i, channel="email", purpose=f"step {i}",
                               body=f"body {i}", signal_dependence="durable")
                    for i in (1, 2, 3)
                ]))

            await campaign_drafts.write(s, w.enrico, draft=undated)
            await s.commit()
            seq = w.enrico.id

        r = await api.get(f"/api/sequences/{seq}/arc")
        assert r.status_code == 200, r.text
        arc = r.json()
        assert [t["day_offset"] for t in arc["touches"]] == [None, None, None]
        assert [t["body"] for t in arc["touches"]] == ["body 1", "body 2", "body 3"]


class TestWithdrawingSomebody:
    """A promoted queue is locked, so this is the only way out before sending."""

    async def test_withdrawing_keeps_the_drafts_and_frees_the_person(self, session):
        w = await world(session)
        await campaign_drafts.write(session, w.enrico, draft=drafter())
        await campaign_drafts.save(session, w.enrico)

        await promotion.withdraw(session, w.enrico, reason="covered by another campaign")
        assert w.enrico.status == "cancelled"
        assert w.enrico.withdraw_reason == "covered by another campaign"
        assert len(await campaign_drafts.arc_of(session, w.enrico.id)) == 3, "the drafts stay"

        rows = {r["full_name"]: r for r in await campaign_drafts.rows(session, w.campaign)}
        assert rows["Enrico Bergamo"]["state"] == "withdrawn"
        assert rows["Enrico Bergamo"]["withdraw_reason"] == "covered by another campaign"

    async def test_nothing_counts_them_any_more(self, session):
        from app.services import preflight

        w = await world(session)
        before = await preflight.run(session, w.campaign.id)
        await promotion.withdraw(session, w.enrico, reason="wrong person")
        after = await preflight.run(session, w.campaign.id)

        threads_before = next(c for c in before.checks if c.key == "has_threads")
        threads_after = next(c for c in after.checks if c.key == "has_threads")
        assert "2 sequence(s)" in threads_before.detail
        assert "1 sequence(s)" in threads_after.detail

    async def test_a_withdrawal_needs_a_reason_and_cannot_touch_an_enrolled_person(self, session):
        w = await world(session)
        with pytest.raises(promotion.NotWithdrawableError, match="needs a reason"):
            await promotion.withdraw(session, w.enrico, reason="   ")

        w.enrico.status = "executing"
        await session.flush()
        with pytest.raises(promotion.NotWithdrawableError, match="stop it instead"):
            await promotion.withdraw(session, w.enrico, reason="too late")

    async def test_putting_somebody_back_needs_them_drafted_and_approved_again(self, session):
        w = await world(session)
        await campaign_drafts.write(session, w.enrico, draft=drafter())
        await campaign_drafts.save(session, w.enrico)
        await promotion.withdraw(session, w.enrico, reason="mistake")

        with pytest.raises(campaign_drafts.DraftingRefusedError, match="was withdrawn"):
            await campaign_drafts.save(session, w.enrico)

        await promotion.reinstate(session, w.enrico)
        assert w.enrico.status == "draft" and w.enrico.withdraw_reason is None
        await campaign_drafts.save(session, w.enrico)
        assert w.enrico.status == "pending_approval"
