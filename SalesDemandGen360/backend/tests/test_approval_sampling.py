"""Phase 9: stratified sampling, and the four conditions `docs/08` sets.

The one that matters most is the first. Uniform sampling would be the flaw
here: a random 6 of 18 could miss all four flagged threads, and the model would
look like a faster way to rubber-stamp rather than a defensible review.
"""

from __future__ import annotations

import os
import uuid
from collections import Counter

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.campaign import OutreachCampaign
from app.models.governance import Approval, ApprovalSample, Evaluation
from app.services.approval import (
    CONFIDENCE_FLOOR,
    Candidate,
    SampleEscalatedError,
    SampleTamperedError,
    accept_sample,
    draw,
    flag_reasons,
    inherit,
    record_rejections,
    sample_size_for,
    stratify,
)

TEST_DB = os.getenv("TEST_DATABASE_URL")
requires_db = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DB)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
        await s.rollback()
    await engine.dispose()


@pytest.fixture
async def campaign(session):
    row = OutreachCampaign(label="Sept EIA push", status="pending_approval")
    session.add(row)
    await session.flush()
    return row


def clean(n: int) -> list[Candidate]:
    return [Candidate(sequence_id=uuid.uuid4()) for _ in range(n)]


def flagged(n: int) -> list[Candidate]:
    return [
        Candidate(sequence_id=uuid.uuid4(), evaluation_verdict="warn") for _ in range(n)
    ]


class TestStratifyingComesFirst:
    def test_an_evaluation_warning_flags_a_thread(self):
        assert flag_reasons(Candidate(uuid.uuid4(), evaluation_verdict="warn"))

    def test_an_unverified_contact_flags_a_thread(self):
        assert flag_reasons(Candidate(uuid.uuid4(), contact_verified=False))

    def test_low_strategy_confidence_flags_a_thread(self):
        assert flag_reasons(
            Candidate(uuid.uuid4(), strategy_confidence=CONFIDENCE_FLOOR - 0.01)
        )
        assert not flag_reasons(
            Candidate(uuid.uuid4(), strategy_confidence=CONFIDENCE_FLOOR)
        )

    def test_a_cadence_deviation_flags_a_thread(self):
        assert flag_reasons(Candidate(uuid.uuid4(), cadence_matches_template=False))

    def test_a_clean_thread_has_no_reasons(self):
        assert flag_reasons(Candidate(uuid.uuid4())) == []

    def test_every_reason_is_reported_not_just_the_first(self):
        reasons = flag_reasons(
            Candidate(
                uuid.uuid4(), evaluation_verdict="fail",
                contact_verified=False, cadence_matches_template=False,
            )
        )
        assert len(reasons) == 3

    def test_the_split_keeps_everyone(self):
        stratum = stratify(clean(14) + flagged(4))
        assert len(stratum.clean) == 14
        assert len(stratum.flagged) == 4

    def test_flag_reasons_are_carried_for_the_card(self):
        """A rep needs to know what to look at, not just that something is
        wrong."""
        one = flagged(1)[0]
        stratum = stratify([one])
        assert stratum.reasons[one.sequence_id] == ["evaluation returned warn"]


@requires_db
@pytest.mark.db
class TestFlaggedThreadsAreNeverSampled:
    async def test_a_draw_contains_only_clean_threads(self, session, campaign):
        """The phase condition, and the reason stratifying comes first."""
        stratum = stratify(clean(14) + flagged(4))
        flagged_ids = {str(c.sequence_id) for c in stratum.flagged}

        sample = await draw(session, campaign_id=campaign.id, stratum=stratum, rate=0.4)

        assert set(sample.sequence_ids).isdisjoint(flagged_ids)
        assert sample.stratum_size == 14, "the stratum is the clean set, not everyone"

    async def test_repeated_draws_never_surface_a_flagged_thread(self, session, campaign):
        """Once is luck. This is the property, so it is checked over many draws."""
        stratum = stratify(clean(10) + flagged(6))
        flagged_ids = {str(c.sequence_id) for c in stratum.flagged}

        for _ in range(40):
            sample = await draw(
                session, campaign_id=campaign.id, stratum=stratum, rate=0.5
            )
            assert set(sample.sequence_ids).isdisjoint(flagged_ids)

    async def test_an_all_flagged_batch_draws_nothing(self, session, campaign):
        stratum = stratify(flagged(5))
        sample = await draw(session, campaign_id=campaign.id, stratum=stratum, rate=0.4)
        assert sample.sample_size == 0
        assert sample.sequence_ids == []


@requires_db
@pytest.mark.db
class TestTheSampleIsServerDrawn:
    async def test_the_draw_function_accepts_no_chosen_ids(self):
        """Structural: there is no parameter through which a rep could pass a
        preferred set."""
        import inspect

        params = set(inspect.signature(draw).parameters)
        assert params == {
            "session", "campaign_id", "stratum", "rate", "doublings", "escalated",
        }

    async def test_two_draws_over_the_same_stratum_differ(self, session, campaign):
        """If they never differed, "random" would be decoration."""
        stratum = stratify(clean(20))
        draws = set()
        for _ in range(12):
            sample = await draw(
                session, campaign_id=campaign.id, stratum=stratum, rate=0.3
            )
            draws.add(tuple(sorted(sample.sequence_ids)))
        assert len(draws) > 1

    async def test_submitting_ids_that_were_not_drawn_is_refused(self, session, campaign):
        """Accepting them would let a rep choose which threads counted as read."""
        stratum = stratify(clean(10))
        sample = await draw(session, campaign_id=campaign.id, stratum=stratum, rate=0.4)

        substituted = {uuid.uuid4(): "approve" for _ in sample.sequence_ids}
        with pytest.raises(SampleTamperedError, match="exactly"):
            await accept_sample(
                session, sample=sample, reviewed=substituted, reviewer_id="bertie"
            )

    async def test_reviewing_fewer_than_drawn_is_refused(self, session, campaign):
        stratum = stratify(clean(10))
        sample = await draw(session, campaign_id=campaign.id, stratum=stratum, rate=0.5)
        partial = {uuid.UUID(s): "approve" for s in sample.sequence_ids[:-1]}

        with pytest.raises(SampleTamperedError, match="missing"):
            await accept_sample(
                session, sample=sample, reviewed=partial, reviewer_id="bertie"
            )

    async def test_a_redraw_supersedes_rather_than_mutates(self, session, campaign):
        """The record of how hard we looked has to survive a redraw."""
        stratum = stratify(clean(10))
        first = await draw(session, campaign_id=campaign.id, stratum=stratum, rate=0.3)
        second = await draw(session, campaign_id=campaign.id, stratum=stratum, rate=0.3)

        assert first.is_current is False
        assert second.is_current is True
        assert second.draw_number == first.draw_number + 1

        rows = list(
            (
                await session.execute(
                    select(ApprovalSample).where(ApprovalSample.campaign_id == campaign.id)
                )
            ).scalars()
        )
        assert len(rows) == 2, "the first draw was overwritten"

    async def test_only_one_sample_is_current_at_a_time(self, session, campaign):
        stratum = stratify(clean(6))
        await draw(session, campaign_id=campaign.id, stratum=stratum, rate=0.5)
        session.add(
            ApprovalSample(
                campaign_id=campaign.id, sequence_ids=[], stratum_size=6,
                sample_size=0, is_current=True,
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()


class TestSampleSizing:
    def test_a_small_stratum_is_never_sampled_at_zero(self):
        """A sample of nothing that reports as a sample is worse than no
        sampling at all."""
        assert sample_size_for(4, 0.1) == 1

    def test_the_rate_is_applied_and_rounded_up(self):
        assert sample_size_for(14, 0.4) == 6
        assert sample_size_for(10, 0.5) == 5

    def test_it_never_exceeds_the_stratum(self):
        assert sample_size_for(3, 1.0) == 3
        assert sample_size_for(3, 2.0) == 3

    def test_an_empty_stratum_samples_nothing(self):
        assert sample_size_for(0, 0.4) == 0

    def test_doubling_doubles_the_rate(self):
        assert sample_size_for(20, 0.25) == 5
        assert sample_size_for(20, 0.25, doublings=1) == 10
        assert sample_size_for(20, 0.25, doublings=2) == 20

    def test_doubling_saturates_at_the_whole_stratum(self):
        assert sample_size_for(20, 0.25, doublings=5) == 20


@requires_db
@pytest.mark.db
class TestOneRejectionDoublesTheSample:
    async def test_a_single_rejection_forces_a_bigger_redraw(self, session, campaign):
        stratum = stratify(clean(20))
        first = await draw(session, campaign_id=campaign.id, stratum=stratum, rate=0.25)
        assert first.sample_size == 5

        reviewed = {uuid.UUID(s): "approve" for s in first.sequence_ids}
        reviewed[uuid.UUID(first.sequence_ids[0])] = "reject"

        with pytest.raises(SampleEscalatedError, match="doubles"):
            await accept_sample(
                session, sample=first, reviewed=reviewed, reviewer_id="bertie"
            )
        assert first.rejections == 1

        second = await draw(
            session, campaign_id=campaign.id, stratum=stratum, rate=0.25, doublings=1
        )
        assert second.sample_size == 10

    async def test_two_rejections_drop_the_batch_to_individual_review(self, session, campaign):
        stratum = stratify(clean(20))
        sample = await draw(session, campaign_id=campaign.id, stratum=stratum, rate=0.25)

        with pytest.raises(SampleEscalatedError, match="individual review"):
            await record_rejections(session, sample=sample, rejected=2)

        assert sample.escalated_to_individual is True

    async def test_an_escalated_sample_cannot_be_accepted(self, session, campaign):
        stratum = stratify(clean(10))
        sample = await draw(session, campaign_id=campaign.id, stratum=stratum, rate=0.4)
        sample.escalated_to_individual = True
        await session.flush()

        with pytest.raises(SampleEscalatedError, match="no sample to accept"):
            await accept_sample(
                session, sample=sample,
                reviewed={uuid.UUID(s): "approve" for s in sample.sequence_ids},
                reviewer_id="bertie",
            )

    async def test_escalation_draws_the_whole_stratum(self, session, campaign):
        stratum = stratify(clean(9))
        sample = await draw(
            session, campaign_id=campaign.id, stratum=stratum, rate=0.3, escalated=True
        )
        assert sample.sample_size == 9, "individual review means everything is read"


@requires_db
@pytest.mark.db
class TestReviewDepthIsRecorded:
    async def test_the_sample_is_recorded_as_sampled(self, session, campaign):
        stratum = stratify(clean(10))
        sample = await draw(session, campaign_id=campaign.id, stratum=stratum, rate=0.4)

        written = await accept_sample(
            session, sample=sample,
            reviewed={uuid.UUID(s): "approve" for s in sample.sequence_ids},
            reviewer_id="bertie",
        )

        assert {a.review_depth for a in written} == {"sampled"}
        assert all(a.sample_id == sample.id for a in written)
        assert all(a.sample_size == sample.sample_size for a in written)
        assert all(a.stratum_size == sample.stratum_size for a in written)

    async def test_the_remainder_is_recorded_as_inherited(self, session, campaign):
        """This is the column the Learning layer compares against `sampled`.
        Without the distinction the sampling model can only be assumed safe."""
        stratum = stratify(clean(10))
        sample = await draw(session, campaign_id=campaign.id, stratum=stratum, rate=0.4)
        drawn = {uuid.UUID(s) for s in sample.sequence_ids}
        remainder = [c.sequence_id for c in stratum.clean if c.sequence_id not in drawn]

        inherited = inherit(sample=sample, unsampled=remainder, reviewer_id="bertie")

        assert {a.review_depth for a in inherited} == {"inherited"}
        assert len(inherited) == 10 - sample.sample_size

    async def test_the_two_depths_partition_the_stratum(self, session, campaign):
        stratum = stratify(clean(14))
        sample = await draw(session, campaign_id=campaign.id, stratum=stratum, rate=0.4)
        drawn = {uuid.UUID(s) for s in sample.sequence_ids}
        remainder = [c.sequence_id for c in stratum.clean if c.sequence_id not in drawn]

        written = await accept_sample(
            session, sample=sample,
            reviewed={d: "approve" for d in drawn},
            reviewer_id="bertie",
        )
        for row in inherit(sample=sample, unsampled=remainder, reviewer_id="bertie"):
            session.add(row)
        await session.flush()

        depths = Counter(
            a.review_depth
            for a in (
                await session.execute(
                    select(Approval).where(Approval.sample_id == sample.id)
                )
            ).scalars()
        )
        assert depths["sampled"] + depths["inherited"] == 14
        assert depths["sampled"] == len(written)

    async def test_a_sampled_approval_must_cite_its_sample(self, session):
        """Otherwise "how closely was this read" has no evidence behind it."""
        session.add(
            Approval(
                subject_type="outreach_sequence", subject_id=uuid.uuid4(),
                decision="approve", reviewer_id="bertie", review_depth="inherited",
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()


@requires_db
@pytest.mark.db
class TestTheRecordIsHonest:
    async def test_a_rejection_must_say_why(self, session):
        """The rejection-reason distribution is an M4 gate metric."""
        session.add(
            Approval(
                subject_type="outreach_sequence", subject_id=uuid.uuid4(),
                decision="reject", reviewer_id="bertie",
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_an_edit_must_carry_its_delta(self, session):
        """The delta is the most valuable learning signal in the system."""
        session.add(
            Approval(
                subject_type="outreach_sequence", subject_id=uuid.uuid4(),
                decision="edit", reviewer_id="bertie",
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_a_sample_cannot_exceed_its_stratum(self, session, campaign):
        session.add(
            ApprovalSample(
                campaign_id=campaign.id,
                sequence_ids=[str(uuid.uuid4()) for _ in range(5)],
                stratum_size=3, sample_size=5,
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_the_stated_size_must_match_the_drawn_ids(self, session, campaign):
        """A count that disagrees with the list would misreport how much was
        read, in the direction that flatters us."""
        session.add(
            ApprovalSample(
                campaign_id=campaign.id,
                sequence_ids=[str(uuid.uuid4())],
                stratum_size=10, sample_size=6,
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_a_failing_evaluation_must_record_an_issue(self, session):
        """A verdict nobody can act on is not a verdict."""
        session.add(
            Evaluation(
                subject_type="draft", subject_id=uuid.uuid4(),
                method="llm", verdict="fail",
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_a_passing_evaluation_needs_no_issues(self, session):
        session.add(
            Evaluation(
                subject_type="draft", subject_id=uuid.uuid4(),
                method="rules", verdict="pass",
            )
        )
        await session.flush()
