"""Deterministic scoring, and the re-scoring guarantee.

The phase condition is that re-scoring the whole book after a weight change
makes **zero LLM calls**. That is asserted here by making any LLM call fail
loudly rather than by trusting the code to be well behaved.
"""

from __future__ import annotations

import os
import sys
import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.account import Account
from app.models.config import ScoringConfig
from app.models.context import Qualification
from app.schemas.qualification import DimensionAssessment, DimensionAssessments
from app.services.scoring import (
    normalise_industry,
    band_for,
    effective_weights,
    rescore_book,
    score,
)

TEST_DB = os.getenv("TEST_DATABASE_URL")
requires_db = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")

EVEN = {
    "fit": 20, "opportunity": 20, "buyer": 15,
    "commercial": 15, "intent": 20, "engagement": 10,
}


def cfg(**over) -> ScoringConfig:
    base = dict(
        dimension_weights=dict(EVEN),
        industry_multipliers={},
        size_multipliers={},
        persona_role_weights={},
        band_cutoffs={"high": 75, "medium": 50},
        man_view_enabled=False,
        version=1,
        is_active=True,
    )
    return ScoringConfig(**{**base, **over})


def assessments(**scores) -> DimensionAssessments:
    """Six assessments, each citing one made-up-but-well-formed evidence id."""
    return DimensionAssessments(
        assessments=[
            DimensionAssessment(
                dimension=d,
                score=scores.get(d, 50),
                reason=f"{d} reason",
                evidence_ids=[str(uuid.uuid4())],
            )
            for d in ("fit", "opportunity", "buyer", "commercial", "intent", "engagement")
        ]
    )


class TestTheArithmeticIsAWeightedAverage:
    def test_all_dimensions_at_the_same_score_produce_that_score(self):
        # The weights total 100, so a flat 60 across six dimensions must roll
        # up to exactly 60. If it does not, the weights are not a distribution.
        result = score(assessments(**dict.fromkeys(EVEN, 60)), config=cfg())
        assert result.priority_score == 60.0

    def test_a_zero_everywhere_is_zero(self):
        assert score(assessments(**dict.fromkeys(EVEN, 0)), config=cfg()).priority_score == 0.0

    def test_weighting_moves_the_result_in_the_expected_direction(self):
        # fit carries 20 of 100; lifting only fit from 50 to 100 adds 10.
        flat = score(assessments(**dict.fromkeys(EVEN, 50)), config=cfg())
        lifted = score(assessments(**{**dict.fromkeys(EVEN, 50), "fit": 100}), config=cfg())
        assert lifted.priority_score - flat.priority_score == 10.0

    def test_every_dimension_reports_its_own_contribution(self):
        result = score(assessments(**dict.fromkeys(EVEN, 50)), config=cfg())
        assert sum(d.contribution for d in result.dimensions) == pytest.approx(
            result.priority_score, abs=0.02
        )

    def test_rounding_is_half_up_not_bankers(self):
        """Python rounds 62.5 down and 63.5 up. Under a threshold of 63 that
        would admit one account and reject an identical one."""
        from app.services.scoring import _round2

        assert _round2(62.505) == 62.51
        assert _round2(0.125) == 0.13


class TestMultipliersRebalanceRatherThanInflate:
    def test_multipliers_are_renormalised_back_to_100(self):
        weights = effective_weights(EVEN, {"buyer": 1.4, "intent": 1.4})
        assert sum(weights.values()) == pytest.approx(100.0)

    def test_a_uniform_multiplier_changes_nothing(self):
        """Scaling every dimension equally is not a preference, and must not
        move the score."""
        flat = score(assessments(**dict.fromkeys(EVEN, 55)), config=cfg())
        doubled = score(
            assessments(**dict.fromkeys(EVEN, 55)),
            config=cfg(industry_multipliers={"saas": dict.fromkeys(EVEN, 2.0)}),
            industry="SaaS",
        )
        assert doubled.priority_score == flat.priority_score

    def test_a_multiplier_shifts_emphasis_between_dimensions(self):
        low_buyer = {**dict.fromkeys(EVEN, 50), "buyer": 100}
        plain = score(assessments(**low_buyer), config=cfg())
        weighted = score(
            assessments(**low_buyer),
            config=cfg(industry_multipliers={"saas": {"buyer": 2.0}}),
            industry="SaaS",
        )
        assert weighted.priority_score > plain.priority_score

    def test_an_industry_with_no_row_falls_back_to_the_base_weights(self):
        result = score(
            assessments(**dict.fromkeys(EVEN, 50)),
            config=cfg(industry_multipliers={"saas": {"buyer": 2.0}}),
            industry="Agency",
        )
        assert result.priority_score == 50.0

    def test_zeroing_every_weight_is_refused(self):
        with pytest.raises(ValueError, match="every dimension would be ignored"):
            effective_weights(EVEN, dict.fromkeys(EVEN, 0.0))


class TestTheIndustryKeyIsNormalised:
    """`account.industry` is free text and the ICP is free text.

    "FinTech" from a spreadsheet and "Fintech" from an ICP must reach the same
    multiplier row, because the alternative failure is silent — the account
    scores on base weights and nobody is told why.
    """

    @pytest.mark.parametrize("written", ["SaaS", "saas", "  SaaS  ", "SAAS"])
    def test_case_and_padding_reach_the_same_row(self, written):
        result = score(
            assessments(**{**dict.fromkeys(EVEN, 50), "buyer": 100}),
            config=cfg(industry_multipliers={"saas": {"buyer": 2.0}}),
            industry=written,
        )
        plain = score(
            assessments(**{**dict.fromkeys(EVEN, 50), "buyer": 100}), config=cfg()
        )
        assert result.priority_score > plain.priority_score

    def test_internal_whitespace_is_collapsed(self):
        assert normalise_industry("Real   Estate") == "real estate"

    def test_it_does_not_guess_a_mapping(self):
        """Normalisation, not aliasing.

        "Financial Services" and "Fintech" are two different words, and deciding
        they mean one thing is a judgement to be made deliberately — with an
        alias table, once Apollo's taxonomy is in the system to reconcile
        against — not silently inside a `casefold`.
        """
        assert normalise_industry("Financial Services") != normalise_industry("Fintech")

    def test_nothing_normalises_to_the_empty_key(self):
        assert normalise_industry(None) == ""
        assert normalise_industry("   ") == ""


class TestSizeMultipliersStackWithIndustry:
    """Both axes apply, and the result is renormalised once.

    Renormalising after each set separately would quietly favour whichever was
    applied last, which is exactly the bug the single renormalise prevents.
    """

    def test_both_sets_apply(self):
        low_buyer = {**dict.fromkeys(EVEN, 50), "buyer": 100}
        both = score(
            assessments(**low_buyer),
            config=cfg(
                industry_multipliers={"saas": {"buyer": 1.5}},
                size_multipliers={"large": {"buyer": 1.5}},
            ),
            industry="SaaS",
            size_band="large",
        )
        industry_only = score(
            assessments(**low_buyer),
            config=cfg(industry_multipliers={"saas": {"buyer": 1.5}}),
            industry="SaaS",
        )
        assert both.priority_score > industry_only.priority_score

    def test_order_does_not_matter(self):
        """×1.2 then ×1.3 is ×1.3 then ×1.2 — true only with one renormalise."""
        low_buyer = {**dict.fromkeys(EVEN, 50), "buyer": 100}
        forward = effective_weights(EVEN, {"buyer": 1.2}, {"buyer": 1.3})
        backward = effective_weights(EVEN, {"buyer": 1.3}, {"buyer": 1.2})
        assert forward == pytest.approx(backward)
        assert sum(forward.values()) == pytest.approx(100.0)

    def test_an_unknown_size_carries_no_multipliers(self):
        """`unknown` is the absence of a headcount, not a size.

        Scoring it as one would be an invention nothing on screen reveals.
        """
        result = score(
            assessments(**dict.fromkeys(EVEN, 50)),
            config=cfg(size_multipliers={"unknown": {"buyer": 5.0}}),
            size_band="unknown",
        )
        assert result.priority_score == 50.0

    def test_the_applied_axes_are_recorded_on_the_result(self):
        """A re-score has to reproduce the multipliers that were applied, and
        the account's industry or headcount may have changed since."""
        result = score(
            assessments(**dict.fromkeys(EVEN, 50)),
            config=cfg(),
            industry="SaaS",
            size_band="large",
        )
        assert result.industry == "SaaS"
        assert result.size_band == "large"


class TestBanding:
    def test_the_cutoff_itself_is_inside_the_band(self):
        """A high cut-off of 75 means 75 is High. Exclusive would make the
        number shown in Settings not the number that applies."""
        cutoffs = {"high": 75, "medium": 50}
        assert band_for(75, cutoffs) == "high"
        assert band_for(74.99, cutoffs) == "medium"
        assert band_for(50, cutoffs) == "medium"
        assert band_for(49.99, cutoffs) == "low"


class TestEveryDimensionScoreCarriesEvidence:
    def test_an_evidence_based_assessment_must_cite_something(self):
        with pytest.raises(ValidationError, match="at least one"):
            DimensionAssessment(dimension="fit", score=70, reason="looks right")

    def test_absence_can_be_declared_rather_than_fabricated(self):
        """Engagement on an account we have never contacted is a known, correct
        zero — not a gap and not a guess. Requiring a citation here would push
        the model to invent one."""
        a = DimensionAssessment(
            dimension="engagement", score=0, reason="no prior contact", basis="no_evidence"
        )
        assert a.evidence_ids == []

    def test_a_declared_absence_cannot_score_above_zero(self):
        with pytest.raises(ValidationError, match="must score 0"):
            DimensionAssessment(
                dimension="engagement", score=40, reason="hunch", basis="no_evidence"
            )

    def test_a_declared_absence_cannot_carry_citations(self):
        with pytest.raises(ValidationError, match="cannot carry citations"):
            DimensionAssessment(
                dimension="engagement", score=0, reason="x",
                basis="no_evidence", evidence_ids=[str(uuid.uuid4())],
            )

    def test_a_partial_set_of_dimensions_is_refused(self):
        with pytest.raises(ValidationError):
            DimensionAssessments(assessments=list(assessments().assessments)[:5])

    def test_scoring_refuses_a_config_missing_weights(self):
        """A real row in the dev database carried only {"fit": 20} — written
        before the six-dimension validator existed. Scoring on it would rank
        the whole book on one dimension and report it as a full assessment."""
        with pytest.raises(ValueError, match="missing weights"):
            score(assessments(), config=cfg(dimension_weights={"fit": 100}))

    def test_scoring_refuses_a_missing_dimension(self):
        """A priority over five dimensions is not comparable to one over six,
        and the whole book is ranked on this number."""
        partial = {d: {"score": 50, "reason": "x"} for d in list(EVEN)[:5]}
        with pytest.raises(ValueError, match="missing"):
            score(partial, config=cfg())

    def test_citations_survive_into_the_stored_reasons(self):
        result = score(assessments(), config=cfg())
        stored = result.as_reasons()
        assert all(stored[d]["evidence_ids"] for d in EVEN)
        assert all(stored[d]["reason"] for d in EVEN)


class TestTheManViewIsDerivedNotAuthored:
    def test_it_is_absent_when_switched_off(self):
        assert score(assessments(), config=cfg()).man is None

    def test_it_reads_off_the_six_when_switched_on(self):
        result = score(
            assessments(commercial=90, buyer=50, opportunity=10),
            config=cfg(man_view_enabled=True),
        )
        assert result.man == {"money": "strong", "authority": "moderate", "need": "weak"}


@requires_db
@pytest.mark.db
class TestRescoringTheBookMakesNoLlmCalls:
    @pytest.fixture
    async def session(self):
        engine = create_async_engine(TEST_DB)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as s:
            yield s
            await s.rollback()
        await engine.dispose()

    async def _book(self, session, n=3):
        rows = []
        for i in range(n):
            account = Account(name=f"Co {i}", domain=f"CO{i}.IO")
            session.add(account)
            await session.flush()
            result = score(assessments(**dict.fromkeys(EVEN, 50 + i * 10)), config=cfg())
            row = Qualification(
                account_id=account.id,
                priority_score=result.priority_score,
                priority_band=result.priority_band,
                reasons=result.as_reasons(),
                scoring_config_version=1,
            )
            session.add(row)
            rows.append(row)
        await session.flush()
        return rows

    async def test_a_weight_change_rescores_without_asking_anything(self, session, monkeypatch):
        """The guarantee, enforced rather than trusted: anthropic is replaced
        with an object that raises on any attribute access, so a single call
        anywhere beneath `rescore_book` fails the test."""
        await self._book(session)

        class Forbidden:
            def __getattr__(self, name):
                raise AssertionError(f"re-scoring reached the LLM (anthropic.{name})")

        monkeypatch.setitem(sys.modules, "anthropic", Forbidden())

        heavier_fit = cfg(
            dimension_weights={
                "fit": 50, "opportunity": 10, "buyer": 10,
                "commercial": 10, "intent": 10, "engagement": 10,
            },
            version=2,
        )
        changed = await rescore_book(session, config=heavier_fit)

        assert changed == 3
        rows = list((await session.execute(select(Qualification))).scalars())
        assert all(r.scoring_config_version == 2 for r in rows)

    async def test_rescoring_actually_changes_the_numbers(self, session):
        """The counterpart. A re-score that silently no-ops would satisfy every
        assertion about not calling an LLM."""
        await self._book(session, n=1)
        before = (await session.execute(select(Qualification))).scalar_one()
        original = float(before.priority_score)

        await rescore_book(
            session,
            config=cfg(
                dimension_weights={
                    "fit": 50, "opportunity": 10, "buyer": 10,
                    "commercial": 10, "intent": 10, "engagement": 10,
                },
                version=2,
            ),
        )
        after = (await session.execute(select(Qualification))).scalar_one()
        assert float(after.priority_score) == original, "flat scores are weight-invariant"

        # Now a book whose dimensions differ, where re-weighting must move it.
        before.reasons = {
            **before.reasons,
            "fit": {**before.reasons["fit"], "score": 100},
        }
        await session.flush()
        await rescore_book(session, config=cfg(version=3))
        moved = (await session.execute(select(Qualification))).scalar_one()
        assert float(moved.priority_score) > original

    async def test_the_stored_assessments_are_left_intact(self, session):
        """They are the input to every future re-score. Overwriting them with
        weighted contributions would make the next weight change unrecoverable."""
        await self._book(session, n=1)
        row = (await session.execute(select(Qualification))).scalar_one()
        before = dict(row.reasons)

        await rescore_book(session, config=cfg(version=2))

        after = (await session.execute(select(Qualification))).scalar_one()
        assert after.reasons == before

    async def test_the_config_version_explains_the_number(self, session):
        await self._book(session, n=1)
        await rescore_book(session, config=cfg(version=7))
        row = (await session.execute(select(Qualification))).scalar_one()
        assert row.scoring_config_version == 7


class TestScoringIsPure:
    def test_the_same_inputs_always_give_the_same_number(self):
        a = assessments(**dict.fromkeys(EVEN, 63))
        first = score(a, config=cfg())
        second = score(a, config=cfg())
        assert first.priority_score == second.priority_score
        assert first.priority_band == second.priority_band

    def test_it_needs_nothing_but_assessments_and_config(self):
        """No session, no clock, no network. That is what makes a book-wide
        re-score a batch job."""
        result = score(
            {
                d: {"score": 50, "reason": "r", "evidence_ids": [], "basis": "no_evidence"}
                for d in EVEN
            },
            config=SimpleNamespace(
                dimension_weights=EVEN,
                industry_multipliers={},
                size_multipliers={},
                band_cutoffs={"high": 75, "medium": 50},
                man_view_enabled=False,
                version=1,
            ),
        )
        assert result.priority_score == 50.0
