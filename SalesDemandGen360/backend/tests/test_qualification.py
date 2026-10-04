"""Qualification: the six dimensions, and what a bad citation costs.

The shape of this step is fixed by invariant 7 — the model judges, Python
scores — and by invariant 1, which reaches it through the citations each
dimension carries. The interesting cases are all about the second: what
happens when a judgement rests on evidence we do not hold.

The answer here is deliberately *not* a refusal. An unscored account still
queues and still promotes; it simply sorts nowhere, and the reason is
invisible. A scored one carries a penalty proportional to how much of it
turned out to be unsupported, which is both honest and useful.
"""

from __future__ import annotations

import os
import uuid
from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.account import Account, Contact
from app.models.config import ScoringConfig, SignalType
from app.models.context import AccountContext, Qualification
from app.models.governance import Evaluation
from app.models.signal import Evidence, Signal, signal_evidence
from app.schemas.qualification import DimensionAssessment, DimensionAssessments
from app.services import qualification as qual
from app.services.promotion import queue_ineligibility

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"
    ),
]

DIMENSIONS = ("fit", "opportunity", "buyer", "commercial", "intent", "engagement")


@pytest.fixture
async def session():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
        await s.rollback()
    await engine.dispose()


@pytest.fixture
async def world(session):
    """An account with one evidence-backed signal, and a scoring config."""
    account = Account(
        name="Meridian Cloud", domain="meridiancloud.io", resolution_status="resolved",
        industry="SaaS", employee_count=180,
    )
    session.add_all(
        [
            account,
            ScoringConfig(
                version=1, is_active=True,
                dimension_weights={"fit": 20, "opportunity": 20, "buyer": 15,
                                   "commercial": 15, "intent": 20, "engagement": 10},
                industry_multipliers={}, size_multipliers={},
                persona_role_weights={}, band_cutoffs={"high": 75, "medium": 50},
                man_view_enabled=False,
            ),
            SignalType(key="funding", label="Funding", scope="company",
                       default_ttl_days=300, produced_by=["funding"]),
        ]
    )
    await session.flush()

    url = "https://example.com/series-b"
    excerpt = "Meridian Cloud raised a $40m Series B."
    from app.services.evidence import excerpt_hash, source_hash

    evidence = Evidence(
        account_id=account.id, source_type="news", source_url=url, excerpt=excerpt,
        source_hash=source_hash(url, None), excerpt_hash=excerpt_hash(url, excerpt),
        raw_status="unavailable",
    )
    session.add(evidence)
    await session.flush()
    signal = Signal(
        account_id=account.id, signal_type="funding", scope="company",
        summary="Series B closed", strength="high", confidence=0.9,
        observed_at=date(2026, 8, 1), expires_at=date(2027, 6, 1),
    )
    session.add(signal)
    await session.flush()
    await session.execute(
        signal_evidence.insert().values(
            signal_id=signal.id, evidence_id=evidence.id, role="primary"
        )
    )
    await session.flush()
    return account, evidence, signal


def assessments(evidence_id: str, *, unsupported: tuple[str, ...] = ()) -> DimensionAssessments:
    """Six dimensions, all cited, unless a dimension is told to cite nothing real."""
    scores = {"fit": 82, "opportunity": 74, "buyer": 68, "commercial": 77, "intent": 45}
    rows = []
    for dim in DIMENSIONS:
        if dim == "engagement":
            rows.append(DimensionAssessment(
                dimension=dim, score=0, basis="no_evidence", evidence_ids=[],
                reason="never contacted — a known zero",
            ))
            continue
        cite = str(uuid.uuid4()) if dim in unsupported else evidence_id
        rows.append(DimensionAssessment(
            dimension=dim, score=scores[dim], reason=f"{dim} judged", evidence_ids=[cite],
        ))
    return DimensionAssessments(assessments=rows)


def assessor(batch: DimensionAssessments):
    async def assess(account, context, evidence):
        return batch
    return assess


class TestTheHappyPath:
    async def test_a_context_version_then_a_score_computed_in_python(self, session, world):
        account, evidence, signal = world

        async def narrate(acc, signals, previous):
            from app.schemas.context import AccountContextPayload

            return AccountContextPayload(
                summary="Funded and hiring.",
                themes=[{"label": "Money in", "reading": "Series B closed",
                         "signal_ids": [str(signal.id)], "weight": "primary"}],
            )

        run_id = uuid.uuid4()
        outcome = await qual.run_qualification(
            session, account=account, run_id=None,
            assess=assessor(assessments(str(evidence.id))), narrate=narrate,
        )

        assert outcome.qualified is True
        assert outcome.priority_band in ("low", "medium", "high")
        assert outcome.unsupported == ()
        assert outcome.context_version == 1

        ctx = (await session.execute(select(AccountContext))).scalar_one()
        assert ctx.payload["narrative"]["summary"] == "Funded and hiring."
        assert ctx.payload["signal_count"] == 1, "the deterministic half is still there"

        stored = (await session.execute(select(Qualification))).scalar_one()
        assert stored.context_id == ctx.id
        assert stored.scoring_config_version == 1
        assert float(stored.priority_score) == outcome.priority_score
        assert stored.reasons["fit"]["evidence_ids"] == [str(evidence.id)]
        assert stored.reasons["_industry"] == "SaaS"
        assert stored.reasons["_size_band"] == "mid", "180 people is mid, not a guess"
        assert account.status == "qualified"

    async def test_a_theme_citing_a_signal_not_in_the_context_is_dropped(self, session, world):
        """The overlay may organise the facts already there; it may not add one."""
        account, evidence, signal = world

        async def narrate(acc, signals, previous):
            from app.schemas.context import AccountContextPayload

            return AccountContextPayload(
                summary="Two readings.",
                themes=[
                    {"label": "Real", "reading": "from a signal we hold",
                     "signal_ids": [str(signal.id)], "weight": "primary"},
                    {"label": "Invented", "reading": "from a signal we do not",
                     "signal_ids": [str(uuid.uuid4())], "weight": "supporting"},
                ],
            )

        outcome = await qual.run_qualification(
            session, account=account, assess=assessor(assessments(str(evidence.id))),
            narrate=narrate,
        )
        assert outcome.themes_dropped == 1
        ctx = (await session.execute(select(AccountContext))).scalar_one()
        assert [t["label"] for t in ctx.payload["narrative"]["themes"]] == ["Real"]


class TestNothingToJudge:
    async def test_an_account_with_no_live_signals_is_not_scored(self, session):
        """Zeros would rank an unresearched account against a judged one."""
        account = Account(name="Quiet Co", resolution_status="resolved")
        session.add(account)
        await session.flush()

        outcome = await qual.run_qualification(
            session, account=account, assess=assessor(assessments(str(uuid.uuid4()))),
        )
        assert outcome.qualified is False
        assert "no live signals" in (outcome.reason or "")
        assert await session.scalar(select(func.count()).select_from(Qualification)) == 0
        assert await session.scalar(select(func.count()).select_from(AccountContext)) == 0
        assert account.status != "qualified"

    async def test_expired_signals_are_not_the_same_as_no_signals(self, session, world):
        """"Nothing found" and "everything found has aged out" send a rep to
        different places: one means research, the other means this account has
        no current trigger."""
        account, evidence, signal = world
        # Aged out: the fact was true a year ago and its TTL has run out.
        signal.observed_at = date(2025, 9, 1)
        signal.expires_at = date(2026, 3, 1)
        await session.flush()

        outcome = await qual.run_qualification(
            session, account=account, assess=assessor(assessments(str(evidence.id))),
        )
        assert outcome.qualified is False
        assert "every signal has expired" in (outcome.reason or "")
        assert "Sep 2025" in (outcome.reason or ""), "the newest fact is not named"


class TestACitationThatDoesNotResolve:
    async def test_the_dimension_is_marked_unsupported_and_scores_zero(self, session, world):
        account, evidence, _ = world
        outcome = await qual.run_qualification(
            session, account=account,
            assess=assessor(assessments(str(evidence.id), unsupported=("buyer",))),
        )

        assert outcome.qualified is True, "a refusal would block nothing and hide the reason"
        assert outcome.unsupported == ("buyer",)
        assert outcome.stripped_citations == 1
        stored = (await session.execute(select(Qualification))).scalar_one()
        assert stored.reasons["buyer"]["basis"] == "unsupported"
        assert stored.reasons["buyer"]["evidence_ids"] == []
        assert float(stored.buyer_score) == 0.0

    async def test_the_penalty_is_proportional(self, session, world):
        account, evidence, _ = world
        clean = await qual.run_qualification(
            session, account=account, assess=assessor(assessments(str(evidence.id))),
        )
        weakened = await qual.run_qualification(
            session, account=account,
            assess=assessor(assessments(str(evidence.id), unsupported=("buyer", "commercial"))),
        )
        assert weakened.priority_score < clean.priority_score
        # Buyer and commercial are judged here (no ICP), so their 68 and 77 land
        # on the 75 step: each was worth 75 × 15% before it was lost.
        assert weakened.priority_score == pytest.approx(clean.priority_score - 11.25 - 11.25, abs=0.02)

    async def test_it_is_recorded_not_only_scored(self, session, world):
        """`unsupported` is not `no_evidence`: one is a fact about the account,
        the other a fact about the model."""
        account, evidence, _ = world
        await qual.run_qualification(
            session, account=account,
            assess=assessor(assessments(str(evidence.id), unsupported=("buyer",))),
        )
        logged = (await session.execute(select(Evaluation))).scalar_one()
        assert logged.subject_type == "qualification"
        assert logged.verdict == "warn"
        assert logged.scores["unsupported_dimensions"] == 1
        assert logged.issues[0]["dimension"] == "buyer"


class TestTheNarrativeIsOptional:
    async def test_a_failed_reading_still_leaves_a_scored_account(self, session, world):
        account, evidence, _ = world

        async def narrate(acc, signals, previous):
            raise RuntimeError("model unavailable")

        outcome = await qual.run_qualification(
            session, account=account, assess=assessor(assessments(str(evidence.id))),
            narrate=narrate,
        )
        assert outcome.qualified is True
        assert "model unavailable" in (outcome.narrative_failed or "")
        ctx = (await session.execute(select(AccountContext))).scalar_one()
        assert "narrative" not in ctx.payload


class TestTheQueueBandGate:
    """`low` is no restriction — the default, so nothing changes until it is
    raised. Above it, an account nobody has judged cannot pass either."""

    def test_low_lets_everything_through(self):
        account = Account(name="X", resolution_status="resolved", status="new")
        assert queue_ineligibility(account) is None
        assert queue_ineligibility(account, band=None, min_band="low") is None

    def test_a_weaker_band_is_refused_by_name(self):
        account = Account(name="X", resolution_status="resolved", status="new")
        reason = queue_ineligibility(account, band="low", min_band="medium")
        assert reason is not None and "below the queue's minimum" in reason
        assert queue_ineligibility(account, band="medium", min_band="medium") is None
        assert queue_ineligibility(account, band="high", min_band="medium") is None

    def test_an_unjudged_account_is_told_to_qualify_first(self):
        account = Account(name="X", resolution_status="resolved", status="new")
        reason = queue_ineligibility(account, band=None, min_band="medium")
        assert reason is not None and "not qualified yet" in reason

    def test_identity_still_comes_first(self):
        account = Account(name="X", resolution_status="needs_review", status="new")
        reason = queue_ineligibility(account, band="high", min_band="medium")
        assert reason is not None and "identity not confirmed" in reason


class TestFitIsComputedNotJudged:
    """With the list's ICPs known, fit is arithmetic — see tests/test_fit.py.

    The world account is SaaS, 180 people, no country: inside the ICP's size
    and industry, region uncheckable, so fit is 100 of what could be checked.
    """

    ICP = ("Default", {"industries": ["SaaS"], "employees": "50-500", "regions": ["US"]})

    async def test_the_models_fit_is_replaced_by_the_arithmetic(self, session, world):
        account, evidence, _ = world
        await qual.run_qualification(
            session, account=account, assess=assessor(assessments(str(evidence.id))),
            icps=[self.ICP],
        )
        stored = (await session.execute(select(Qualification))).scalar_one()
        assert stored.reasons["fit"]["basis"] == "firmographics"
        assert stored.reasons["fit"]["evidence_ids"] == []
        assert float(stored.fit_score) == 100.0
        assert "no country" in stored.reasons["fit"]["reason"]

    async def test_the_same_account_gets_the_same_fit_whatever_the_model_says(
        self, session, world
    ):
        """The failure that started this: 75 one run, 0 the next."""
        account, evidence, _ = world
        generous = assessments(str(evidence.id))
        stingy = assessments(str(evidence.id))
        stingy.assessments[0] = DimensionAssessment(
            dimension="fit", score=0, basis="no_evidence", evidence_ids=[],
            reason="nothing about fit in the evidence",
        )
        for batch in (generous, stingy):
            await qual.run_qualification(
                session, account=account, assess=assessor(batch), icps=[self.ICP],
            )
        fits = (await session.execute(select(Qualification.fit_score))).scalars().all()
        assert [float(f) for f in fits] == [100.0, 100.0]

    async def test_without_an_icp_the_models_fit_stands(self, session, world):
        account, evidence, _ = world
        await qual.run_qualification(
            session, account=account, assess=assessor(assessments(str(evidence.id))),
        )
        stored = (await session.execute(select(Qualification))).scalar_one()
        assert stored.reasons["fit"]["basis"] == "evidence"
        assert float(stored.fit_score) == 75.0, "judged, so the 82 lands on a step"

    async def test_a_bad_citation_on_a_replaced_fit_is_not_logged_as_a_fault(
        self, session, world
    ):
        """Nothing rests on the model's fit once it is replaced, so its bad
        citation is not a defect in this qualification."""
        account, evidence, _ = world
        outcome = await qual.run_qualification(
            session, account=account,
            assess=assessor(assessments(str(evidence.id), unsupported=("fit",))),
            icps=[self.ICP],
        )
        assert outcome.unsupported == ()
        assert outcome.stripped_citations == 0
        assert (await session.execute(select(Evaluation))).scalars().all() == []


class TestASignalIdCitedAsEvidence:
    """Seen live on BlueWave: intent cited the three signal ids of its own
    public-focus theme, none of which is an evidence id, and was scored 0 as
    unsupported for evidence it had."""

    @staticmethod
    def _citing(evidence_id: str, intent_ids: list[str]) -> DimensionAssessments:
        batch = assessments(evidence_id)
        batch.assessments[DIMENSIONS.index("intent")] = DimensionAssessment(
            dimension="intent", score=45, reason="sustained public focus", evidence_ids=intent_ids,
        )
        return batch

    async def test_it_resolves_through_the_signals_evidence(self, session, world):
        account, evidence, signal = world
        outcome = await qual.run_qualification(
            session, account=account,
            assess=assessor(self._citing(str(evidence.id), [str(signal.id)])),
        )
        assert outcome.unsupported == (), "scored 0 for evidence it had"
        assert outcome.stripped_citations == 0
        stored = (await session.execute(select(Qualification))).scalar_one()
        assert stored.reasons["intent"]["basis"] == "evidence"
        assert stored.reasons["intent"]["evidence_ids"] == [str(evidence.id)]
        assert float(stored.intent_score) == 50.0, "45 lands on the 50 step"

    async def test_the_drift_is_recorded(self, session, world):
        """Not a fault — the citation reached evidence — but a prompt citing
        signals instead of evidence is worth seeing."""
        account, evidence, signal = world
        await qual.run_qualification(
            session, account=account,
            assess=assessor(self._citing(str(evidence.id), [str(signal.id)])),
        )
        logged = (await session.execute(select(Evaluation))).scalar_one()
        assert logged.scores["citations_via_signal"] == 1
        assert any(i.get("ids") == [str(signal.id)] for i in logged.issues)

    async def test_a_signal_of_another_account_does_not_resolve(self, session, world):
        """Only the signals of this context resolve. Anything else would let one
        prospect's documents stand behind another's score."""
        account, evidence, _ = world
        other = Account(name="Other Co", domain="other.example", resolution_status="resolved")
        session.add(other)
        await session.flush()
        from app.services.evidence import excerpt_hash, source_hash

        foreign_ev = Evidence(
            account_id=other.id, source_type="news", source_url="https://other.example/a",
            excerpt="Other Co raised money.", source_hash=source_hash("https://other.example/a", None),
            excerpt_hash=excerpt_hash("https://other.example/a", "Other Co raised money."),
            raw_status="unavailable",
        )
        session.add(foreign_ev)
        await session.flush()
        foreign = Signal(
            account_id=other.id, signal_type="funding", scope="company", summary="Other raised",
            strength="high", confidence=0.9, observed_at=date(2026, 8, 1),
            expires_at=date(2027, 6, 1),
        )
        session.add(foreign)
        await session.flush()
        await session.execute(
            signal_evidence.insert().values(
                signal_id=foreign.id, evidence_id=foreign_ev.id, role="primary"
            )
        )
        await session.flush()

        outcome = await qual.run_qualification(
            session, account=account,
            assess=assessor(self._citing(str(evidence.id), [str(foreign.id)])),
        )
        assert outcome.unsupported == ("intent",)
        logged = (await session.execute(select(Evaluation))).scalar_one()
        assert any(i.get("ids") == [str(foreign.id)] for i in logged.issues), (
            "the id that did not resolve is named, so the next one can be diagnosed"
        )


class TestResolveCitations:
    def test_evidence_kept_signal_resolved_unknown_named(self):
        kept, via, unknown = qual.resolve_citations(
            ["e1", "s1", "nope"], held={"e1", "e2"}, backing={"s1": ["e2"]},
        )
        assert kept == ["e1", "e2"]
        assert via == ["s1"]
        assert unknown == ["nope"]

    def test_a_signal_whose_evidence_is_not_held_is_unknown(self):
        """The evidence behind a signal must be among what the assessment was
        shown, or the citation points at something it never read."""
        kept, via, unknown = qual.resolve_citations(["s1"], held={"e1"}, backing={"s1": ["e9"]})
        assert (kept, via, unknown) == ([], [], ["s1"])

    def test_the_same_evidence_twice_is_one_citation(self):
        kept, _, _ = qual.resolve_citations(["e1", "s1"], held={"e1"}, backing={"s1": ["e1"]})
        assert kept == ["e1"]


class TestBuyerAndEngagementAreFacts:
    ICP = (
        "Default",
        {
            "industries": ["SaaS"],
            "personas": [
                {"buying_role": "economic_buyer", "titles": ["CEO"]},
                {"buying_role": "technical_buyer", "titles": ["CTO"]},
            ],
        },
    )

    async def test_buyer_comes_from_the_contacts_not_the_model(self, session, world):
        """The model's buyer here is 68, from whatever it read. The facts: a
        reachable CEO, and nobody for the technical buyer."""
        account, evidence, _ = world
        session.add(
            Contact(
                account_id=account.id, full_name="Ana Diaz", title="CEO",
                email="ana@meridiancloud.io", email_status="verified",
            )
        )
        await session.flush()
        await qual.run_qualification(
            session, account=account, assess=assessor(assessments(str(evidence.id))),
            icps=[self.ICP],
        )
        stored = (await session.execute(select(Qualification))).scalar_one()
        assert stored.reasons["buyer"]["basis"] == "contacts"
        assert float(stored.buyer_score) == 50.0
        assert "technical buyer (CTO): nobody at the account matches" in stored.reasons["buyer"]["reason"]

    async def test_engagement_comes_from_outreach_history(self, session, world):
        account, evidence, _ = world
        await qual.run_qualification(
            session, account=account, assess=assessor(assessments(str(evidence.id))),
        )
        stored = (await session.execute(select(Qualification))).scalar_one()
        assert stored.reasons["engagement"]["basis"] == "outreach"
        assert float(stored.engagement_score) == 0.0
        assert "nothing has been sent" in stored.reasons["engagement"]["reason"]


class TestJudgedDimensionsLandOnSteps:
    async def test_every_judged_score_is_a_step(self, session, world):
        account, evidence, _ = world
        await qual.run_qualification(
            session, account=account, assess=assessor(assessments(str(evidence.id))),
        )
        stored = (await session.execute(select(Qualification))).scalar_one()
        # opportunity 74, commercial 77, intent 45 as judged
        assert float(stored.opportunity_score) == 75.0
        assert float(stored.commercial_score) == 75.0
        assert float(stored.intent_score) == 50.0


class TestTheSameInputsGiveTheSameJudgement:
    """Seen live on BlueWave: opportunity 70, 75, 80, 85 over the same evidence.
    When nothing the model would be shown has changed, it is not asked again."""

    @staticmethod
    def never():
        calls: list[int] = []

        async def assess(account, context, evidence):
            calls.append(1)
            return assessments(str(evidence[0].id)) if evidence else None

        return assess, calls

    async def test_unchanged_inputs_keep_the_judgement_unasked(self, session, world):
        account, evidence, _ = world
        first = await qual.run_qualification(
            session, account=account, assess=assessor(assessments(str(evidence.id))),
            prompt_version="v1",
        )
        again, calls = self.never()
        second = await qual.run_qualification(
            session, account=account, assess=again, prompt_version="v1",
        )
        assert calls == [], "asked again over identical inputs"
        assert second.reused_from == first.qualification_id
        assert second.priority_score == first.priority_score

    async def test_new_evidence_is_judged_afresh(self, session, world):
        account, evidence, _ = world
        await qual.run_qualification(
            session, account=account, assess=assessor(assessments(str(evidence.id))),
            prompt_version="v1",
        )
        from app.services.evidence import excerpt_hash, source_hash

        url, excerpt = "https://example.com/hiring", "Meridian Cloud opened ten QA roles."
        session.add(
            Evidence(
                account_id=account.id, source_type="news", source_url=url, excerpt=excerpt,
                source_hash=source_hash(url, None), excerpt_hash=excerpt_hash(url, excerpt),
                raw_status="unavailable",
            )
        )
        await session.flush()
        again, calls = self.never()
        second = await qual.run_qualification(
            session, account=account, assess=again, prompt_version="v1",
        )
        assert calls == [1]
        assert second.reused_from is None

    async def test_a_different_prompt_is_judged_afresh(self, session, world):
        account, evidence, _ = world
        await qual.run_qualification(
            session, account=account, assess=assessor(assessments(str(evidence.id))),
            prompt_version="v1",
        )
        again, calls = self.never()
        await qual.run_qualification(session, account=account, assess=again, prompt_version="v2")
        assert calls == [1]

    async def test_an_unsupported_judgement_is_not_kept(self, session, world):
        """Keeping it would keep the failure until the evidence happened to change."""
        account, evidence, _ = world
        await qual.run_qualification(
            session, account=account,
            assess=assessor(assessments(str(evidence.id), unsupported=("opportunity",))),
            prompt_version="v1",
        )
        again, calls = self.never()
        await qual.run_qualification(session, account=account, assess=again, prompt_version="v1")
        assert calls == [1]

    async def test_facts_are_still_recomputed_when_the_judgement_is_kept(self, session, world):
        """A contact enriched since the last run changes buyer on this one."""
        account, evidence, _ = world
        icp = TestBuyerAndEngagementAreFacts.ICP
        first = await qual.run_qualification(
            session, account=account, assess=assessor(assessments(str(evidence.id))),
            icps=[icp], prompt_version="v1",
        )
        session.add(
            Contact(
                account_id=account.id, full_name="Raj Iyer", title="CTO",
                email="raj@meridiancloud.io", email_status="verified",
            )
        )
        await session.flush()
        again, calls = self.never()
        second = await qual.run_qualification(
            session, account=account, assess=again, icps=[icp], prompt_version="v1",
        )
        assert calls == []
        assert second.reused_from == first.qualification_id
        assert second.priority_score > first.priority_score, "the new CTO did not count"

    async def test_without_a_prompt_version_nothing_is_kept(self, session, world):
        account, evidence, _ = world
        await qual.run_qualification(
            session, account=account, assess=assessor(assessments(str(evidence.id))),
        )
        again, calls = self.never()
        await qual.run_qualification(session, account=account, assess=again)
        assert calls == [1]
