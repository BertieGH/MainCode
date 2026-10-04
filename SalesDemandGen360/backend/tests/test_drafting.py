"""Phase 8: whole-arc generation, durability banding, and the attribute budget."""

from __future__ import annotations

import os
import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.account import Account, Contact
from app.models.campaign import CadenceShape, OutreachSequence
from app.models.config import ProofPoint, ServiceCatalog
from app.models.content import Draft, Touch
from app.models.strategy import Strategy, StrategyThread
from app.schemas.draft import DraftSet, FreshnessVerdict, TouchDraft
from app.services.drafting import (
    ATTRIBUTE_BUDGET,
    ArcRejectedError,
    attributes_needed,
    band_for_step,
    mark_content_written,
    regenerate_draft,
    store_arc,
    validate_arc,
)

TEST_DB = os.getenv("TEST_DATABASE_URL")
requires_db = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")

CHANNELS = ["linkedin_connect", "email", "linkedin_engage", "email", "inmail", "email"]
DAYS = [1, 3, 6, 8, 12, 15]


def arc(count: int = 6, overrides: dict[int, dict] | None = None) -> DraftSet:
    """A sound 6/15 arc: implied early and middle, durable late.

    Nothing is `dated` by default — a dated touch has to name a signal that
    outlives the day it sends, so the tests that care about dating seed one.
    """
    touches = []
    for i in range(count):
        step = i + 1
        band = band_for_step(step, count)
        dependence = {"early": "implied", "middle": "implied", "late": "durable"}[band]
        # Merged rather than splatted, so an override *replaces* a default
        # instead of colliding with it.
        fields = {
            "step_no": step,
            "day_offset": DAYS[i] if i < len(DAYS) else 15 + i,
            "channel": CHANNELS[i % len(CHANNELS)],
            "purpose": f"step {step}",
            "body": f"Body for step {step}",
            "signal_dependence": dependence,
            "cited_signal_ids": [],
        }
        fields.update((overrides or {}).get(step, {}))
        touches.append(TouchDraft(**fields))
    return DraftSet(touches=touches)


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DB)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
        await s.rollback()
    await engine.dispose()


async def seed_signal(
    session, *, days: int | None = 30, superseded: bool = False, observed_days_ago: int = 0
) -> str:
    """A company signal expiring `days` from today. None never expires.

    `observed_days_ago` backdates the observation, which is the only way to
    build one that has *already* expired: the table refuses an expiry earlier
    than the day the thing was seen.
    """
    from datetime import date, timedelta

    from app.models.account import Account
    from app.models.config import SignalType
    from app.models.signal import Signal

    account = Account(name=f"Datadog {uuid.uuid4().hex[:6]}", resolution_status="resolved")
    kind = f"funding_{uuid.uuid4().hex[:6]}"
    session.add_all([
        account,
        SignalType(key=kind, label="Funding", scope="company", default_ttl_days=300),
    ])
    await session.flush()
    other = None
    if superseded:
        other = Signal(
            account_id=account.id, signal_type=kind, scope="company", summary="newer",
            strength="high", confidence=0.9, observed_at=date.today(),
        )
        session.add(other)
        await session.flush()
    signal = Signal(
        account_id=account.id, signal_type=kind, scope="company", summary="Series B",
        strength="high", confidence=0.9,
        observed_at=date.today() - timedelta(days=observed_days_ago),
        expires_at=(date.today() + timedelta(days=days)) if days is not None else None,
        superseded_by=other.id if other else None,
    )
    session.add(signal)
    await session.flush()
    return str(signal.id)


@pytest.fixture
async def sequence(session):
    account = Account(name="Meridian Cloud", domain="MERIDIANCLOUD.IO")
    service = ServiceCatalog(code=f"qa{uuid.uuid4().hex[:5]}", name="QA", description="d")
    session.add_all([account, service])
    await session.flush()
    contact = Contact(account_id=account.id, full_name="Dana Reyes")
    strategy = Strategy(account_id=account.id, version=1)
    session.add_all([contact, strategy])
    await session.flush()
    thread = StrategyThread(
        strategy_id=strategy.id, contact_id=contact.id, service_id=service.id,
        weight=60, rank=1, thread_status="active_primary",
        problem_hypothesis="h", trigger_summary="t",
        trigger_signal_ids=[str(uuid.uuid4())], positioning="p",
        channel_sequence=["email"], cta="c",
    )
    session.add(thread)
    await session.flush()
    row = OutreachSequence(thread_id=thread.id, status="draft")
    session.add(row)
    await session.flush()
    return row


def shape(**over) -> CadenceShape:
    base = dict(
        key="standard_6_15", label="Standard", lgm_campaign_id="lgm-1",
        touch_count=6, span_days=15,
        attribute_map={str(i): f"custom_attribute_{i}" for i in range(1, 7)},
        attributes_used=6, verified_by="bertie",
    )
    return CadenceShape(**{**base, **over})


# --------------------------------------------------------------------------


class TestTheArcIsGeneratedWhole:
    def test_a_partial_arc_is_refused(self):
        """One call writes every touch, so a gap means the model skipped one
        rather than that we asked for fewer."""
        with pytest.raises(ValidationError, match="no gaps or repeats"):
            DraftSet(
                touches=[
                    TouchDraft(step_no=1, day_offset=1, channel="email", purpose="p",
                               body="b", signal_dependence="durable"),
                    TouchDraft(step_no=3, day_offset=6, channel="email", purpose="p",
                               body="b", signal_dependence="durable"),
                ]
            )

    def test_a_repeated_step_is_refused(self):
        with pytest.raises(ValidationError, match="no gaps or repeats"):
            DraftSet(
                touches=[
                    TouchDraft(step_no=1, day_offset=1, channel="email", purpose="p",
                               body="b", signal_dependence="durable"),
                    TouchDraft(step_no=1, day_offset=3, channel="email", purpose="p",
                               body="b", signal_dependence="durable"),
                ]
            )

    def test_day_offsets_may_not_go_backwards(self):
        with pytest.raises(ValidationError, match="must not go backwards"):
            DraftSet(
                touches=[
                    TouchDraft(step_no=1, day_offset=8, channel="email", purpose="p",
                               body="b", signal_dependence="durable"),
                    TouchDraft(step_no=2, day_offset=3, channel="email", purpose="p",
                               body="b", signal_dependence="durable"),
                ]
            )

    def test_a_sound_arc_is_accepted(self):
        assert len(arc().touches) == 6


class TestDurabilityBanding:
    def test_the_bands_split_the_arc_into_thirds(self):
        assert [band_for_step(i, 6) for i in range(1, 7)] == [
            "early", "early", "middle", "middle", "late", "late",
        ]

    def test_banding_scales_with_the_cadence_length(self):
        """Hardcoding "5–6 is late" would leave touch 8 of an enterprise
        sequence unguarded."""
        assert band_for_step(8, 8) == "late"
        assert band_for_step(5, 8) == "middle"
        assert band_for_step(4, 4) == "late"

    @requires_db
    @pytest.mark.db
    async def test_a_late_touch_may_state_a_signal_that_outlives_the_send_date(self, session):
        """The question is not how late the touch is, but whether the claim is
        still true when it goes out. Copy is frozen at enrolment, so the send
        date is known exactly."""
        live = await seed_signal(session, days=60)
        late = arc(6, {6: {"signal_dependence": "dated", "cited_signal_ids": [live]}})
        assert await validate_arc(session, late) == []

    @requires_db
    @pytest.mark.db
    async def test_a_signal_that_expires_first_is_refused_with_both_dates(self, session):
        """Day 15 copy citing a signal that dies on day 5 is the failure a rep
        cannot catch at approval — on day 0 it reads perfectly."""
        dies = await seed_signal(session, days=5)
        late = arc(6, {6: {"signal_dependence": "dated", "cited_signal_ids": [dies]}})
        problems = await validate_arc(session, late)

        assert [p.reason for p in problems] == ["signal_expires_before_it_sends"]
        assert problems[0].step_no == 6
        assert "day 15" in problems[0].detail

    @requires_db
    @pytest.mark.db
    async def test_a_signal_that_never_expires_dates_any_touch(self, session):
        forever = await seed_signal(session, days=None)
        assert await validate_arc(
            session, arc(6, {5: {"signal_dependence": "dated", "cited_signal_ids": [forever]}})
        ) == []

    @requires_db
    @pytest.mark.db
    async def test_a_superseded_signal_cannot_carry_a_current_claim(self, session):
        """Its expiry may be months away; it is no longer the current reading.

        Refused as `signal_expired` rather than as expiring mid-flight: it was
        already untrue when the copy was written, which is a different fix.
        """
        stale = await seed_signal(session, days=90, superseded=True)
        problems = await validate_arc(
            session, arc(6, {1: {"signal_dependence": "dated", "cited_signal_ids": [stale]}})
        )
        assert [p.reason for p in problems] == ["signal_expired"]

    @requires_db
    @pytest.mark.db
    async def test_a_signal_nobody_has_is_refused(self, session):
        problems = await validate_arc(
            session,
            arc(6, {1: {"signal_dependence": "dated", "cited_signal_ids": [str(uuid.uuid4())]}}),
        )
        assert [p.reason for p in problems] == ["unknown_signal"]

    @requires_db
    @pytest.mark.db
    async def test_implied_and_durable_are_unconstrained(self, session):
        """An implication does not announce news, so it does not go stale."""
        assert await validate_arc(session, arc(6, {6: {"signal_dependence": "implied"}})) == []
        assert await validate_arc(session, arc()) == []

    def test_dated_copy_must_name_the_signal_it_depends_on(self):
        """Otherwise the pre-send freshness check has nothing to re-validate
        and the guard degrades into a label."""
        with pytest.raises(ValidationError, match="must cite the signal"):
            TouchDraft(step_no=1, day_offset=1, channel="email", purpose="p",
                       body="b", signal_dependence="dated")


class TestTheAttributeBudget:
    def test_bodies_and_custom_subjects_both_consume_budget(self):
        assert attributes_needed(arc(6)) == 6
        with_subjects = arc(6, {1: {"subject": "Hello"}, 2: {"subject": "Again"}})
        assert attributes_needed(with_subjects) == 8

    @requires_db
    @pytest.mark.db
    async def test_exceeding_the_cap_is_rejected(self, session):
        """A 21st attribute is refused by LGM, so the arc is refused here.

        Eleven steps with a custom subject each needs 22. The cap is twenty —
        measured against a live account, not read from the documentation,
        which said ten.
        """
        greedy = arc(11, {i: {"subject": f"S{i}"} for i in range(1, 12)})
        assert attributes_needed(greedy) == 22

        problems = await validate_arc(session, greedy)
        budget = [p for p in problems if p.reason == "attribute_budget"]
        assert budget
        assert str(ATTRIBUTE_BUDGET) in budget[0].detail

    @requires_db
    @pytest.mark.db
    async def test_a_six_step_arc_may_now_give_every_step_a_subject(self, session):
        """What the corrected cap buys. At ten this was over budget by two."""
        rich = arc(6, {i: {"subject": f"S{i}"} for i in range(1, 7)})
        assert attributes_needed(rich) == 12
        assert [p.reason for p in await validate_arc(session, rich)] == []

    @requires_db
    @pytest.mark.db
    async def test_exactly_the_cap_is_allowed(self, session):
        at_limit = arc(11, {i: {"subject": f"S{i}"} for i in range(1, 10)})
        assert attributes_needed(at_limit) == ATTRIBUTE_BUDGET
        assert [p.reason for p in await validate_arc(session, at_limit)] == []

    @requires_db
    @pytest.mark.db
    async def test_the_arc_must_match_the_registered_shape(self, session):
        problems = await validate_arc(session, arc(4), shape=shape())
        assert "touch_count_mismatch" in [p.reason for p in problems]

    @requires_db
    @pytest.mark.db
    async def test_an_arc_running_past_the_shape_span_is_rejected(self, session):
        long = arc(6, {6: {"day_offset": 40}})
        problems = await validate_arc(session, long, shape=shape())
        assert "span_mismatch" in [p.reason for p in problems]

    @requires_db
    @pytest.mark.db
    async def test_a_shape_with_no_span_has_nothing_to_run_past(self, session):
        """Registrations since timing became LGM's carry no span at all.

        LGM publishes no step delay, so the number this used to compare
        against could only have been typed by a rep. With nothing to compare,
        the check is silent rather than inventing a default to enforce.
        """
        long = arc(6, {6: {"day_offset": 40}})
        problems = await validate_arc(session, long, shape=shape(span_days=None))
        assert "span_mismatch" not in [p.reason for p in problems]


@requires_db
@pytest.mark.db
class TestTheScheduleIsNotOurs:
    """LGM runs the sequence on a schedule it does not publish.

    The model used to propose a day per touch and the arc was then measured
    against a span somebody typed — two inventions agreeing with each other.
    Now it proposes words, in order, and says nothing about when they go out.
    """

    def _undated(self, count: int = 6) -> DraftSet:
        return DraftSet(
            touches=[
                TouchDraft(
                    step_no=i + 1, channel=CHANNELS[i % len(CHANNELS)], purpose=f"step {i + 1}",
                    body=f"Body for step {i + 1}", signal_dependence="durable",
                )
                for i in range(count)
            ]
        )

    async def test_an_arc_with_no_days_at_all_is_sound(self, session):
        assert await validate_arc(session, self._undated(), shape=shape(span_days=None)) == []

    async def test_a_claim_live_today_survives_an_expiry_nobody_can_place(self, session):
        """The rep's rule, and the only one the facts support.

        A signal valid on the day of drafting may be cited. Whether it is
        still valid when LGM sends step 4 is unknowable here — LGM chooses
        that date — and the pre-send freshness check answers it against the
        real calendar, with no guess in it.
        """
        dies_soon = await seed_signal(session, days=2)
        arc_ = self._undated()
        arc_.touches[5].signal_dependence = "dated"
        arc_.touches[5].cited_signal_ids = [dies_soon]
        assert await validate_arc(session, arc_, shape=shape(span_days=None)) == []

    async def test_a_claim_already_untrue_is_still_refused(self, session):
        """Removing the guess does not remove the gate."""
        dead = await seed_signal(session, days=-1, observed_days_ago=30)
        arc_ = self._undated()
        arc_.touches[0].signal_dependence = "dated"
        arc_.touches[0].cited_signal_ids = [dead]
        problems = await validate_arc(session, arc_, shape=shape(span_days=None))
        assert [p.reason for p in problems] == ["signal_expired"]
        assert "today" in problems[0].detail

    async def test_offsets_are_stored_empty_rather_than_guessed(self, session, sequence):
        """NULL reads as "LGM decides". A zero would read as day zero."""
        await store_arc(session, sequence=sequence, draft_set=self._undated(), shape=shape(span_days=None))
        touches = list(
            (
                await session.execute(
                    select(Touch).where(Touch.sequence_id == sequence.id).order_by(Touch.step_no)
                )
            ).scalars()
        )
        assert [t.day_offset for t in touches] == [None] * 6


@requires_db
@pytest.mark.db
class TestOnlyApprovedProofPointsReachAProspect:
    async def test_an_unapproved_proof_point_is_rejected(self, session):
        pp = ProofPoint(kind="case_study", title="Unapproved", body="b", is_approved=False)
        session.add(pp)
        await session.flush()

        cited = arc(6, {1: {"cited_proof_point_ids": [str(pp.id)]}})
        problems = await validate_arc(session, cited)
        assert "unapproved_proof_point" in [p.reason for p in problems]

    async def test_an_approved_proof_point_passes(self, session):
        pp = ProofPoint(kind="case_study", title="Approved", body="b", is_approved=True)
        session.add(pp)
        await session.flush()

        cited = arc(6, {1: {"cited_proof_point_ids": [str(pp.id)]}})
        assert await validate_arc(session, cited) == []

    async def test_a_nonexistent_proof_point_is_rejected(self, session):
        cited = arc(6, {1: {"cited_proof_point_ids": [str(uuid.uuid4())]}})
        assert "unapproved_proof_point" in [
            p.reason for p in await validate_arc(session, cited)
        ]


@requires_db
@pytest.mark.db
class TestStoringTheArc:
    async def test_one_pass_writes_every_touch_and_draft(self, session, sequence):
        stored = await store_arc(session, sequence=sequence, draft_set=arc(), shape=shape())

        assert len(stored.touch_ids) == 6
        assert len(stored.draft_ids) == 6
        touches = list(
            (
                await session.execute(
                    select(Touch).where(Touch.sequence_id == sequence.id).order_by(Touch.step_no)
                )
            ).scalars()
        )
        assert [t.step_no for t in touches] == [1, 2, 3, 4, 5, 6]
        assert [t.day_offset for t in touches] == DAYS

    async def test_each_touch_is_mapped_to_its_lgm_attribute(self, session, sequence):
        await store_arc(session, sequence=sequence, draft_set=arc(), shape=shape())
        touches = list(
            (
                await session.execute(
                    select(Touch).where(Touch.sequence_id == sequence.id).order_by(Touch.step_no)
                )
            ).scalars()
        )
        assert [t.lgm_attribute for t in touches] == [
            f"custom_attribute_{i}" for i in range(1, 7)
        ]

    async def test_a_rejected_arc_stores_nothing(self, session, sequence):
        bad = arc(6, {6: {"signal_dependence": "dated",
                            "cited_signal_ids": [str(uuid.uuid4())]}})
        with pytest.raises(ArcRejectedError, match="unknown_signal"):
            await store_arc(session, sequence=sequence, draft_set=bad)

        assert (
            await session.execute(select(Touch).where(Touch.sequence_id == sequence.id))
        ).scalars().all() == []

    async def test_subjects_default_to_lgm_native_to_save_budget(self, session, sequence):
        # The shape must have somewhere to put it: a subject is only sendable
        # where that step's subject template in LGM names an attribute.
        await store_arc(
            session, sequence=sequence,
            draft_set=arc(6, {1: {"subject": "Custom"}}),
            shape=shape(subject_attribute_map={"1": "custom_attribute_7"}),
        )
        touches = {
            t.step_no: t
            for t in (
                await session.execute(select(Touch).where(Touch.sequence_id == sequence.id))
            ).scalars()
        }
        assert touches[1].subject_source == "custom_attribute"
        assert touches[2].subject_source == "lgm_template"

    async def test_a_subject_with_nowhere_to_go_is_refused(self, session):
        """LGM drops it in silence, so the approved arc and the sent message
        would be different things. Step 2 of this shape shows LGM's own
        subject — or none at all, if it is a LinkedIn step."""
        problems = await validate_arc(
            session, arc(6, {2: {"subject": "Quick question"}}),
            shape=shape(subject_attribute_map={"1": "custom_attribute_7"}),
        )
        [problem] = [p for p in problems if p.reason == "subject_has_nowhere_to_go"]
        assert problem.step_no == 2
        assert "customAttributeN" in problem.detail, "it says how to make it possible"

    async def test_a_subject_where_the_step_reads_one_is_accepted(self, session):
        assert await validate_arc(
            session, arc(6, {1: {"subject": "Adaptive ML and the SE bottleneck"}}),
            shape=shape(subject_attribute_map={"1": "custom_attribute_7"}),
        ) == []

    async def test_drafting_an_enrolled_sequence_is_refused(self, session, sequence):
        """Content is frozen at enrolment. Re-drafting in place would diverge
        from what LGM already holds on the lead."""
        sequence.status = "executing"
        await session.flush()

        with pytest.raises(ArcRejectedError, match="frozen at enrolment"):
            await store_arc(session, sequence=sequence, draft_set=arc())


@requires_db
@pytest.mark.db
class TestDraftsAreVersionedNeverOverwritten:
    async def test_regeneration_adds_a_version_and_moves_the_flag(self, session, sequence):
        await store_arc(session, sequence=sequence, draft_set=arc(), shape=shape())
        touch = (
            await session.execute(
                select(Touch).where(Touch.sequence_id == sequence.id, Touch.step_no == 1)
            )
        ).scalar_one()

        new = await regenerate_draft(
            session, touch=touch, body="Rewritten", reason="rep_guidance"
        )

        drafts = list(
            (
                await session.execute(
                    select(Draft).where(Draft.touch_id == touch.id).order_by(Draft.version)
                )
            ).scalars()
        )
        assert [d.version for d in drafts] == [1, 2]
        assert [d.is_current for d in drafts] == [False, True]
        assert new.generated_as == "regeneration"
        assert drafts[0].body.startswith("Body for step 1"), "v1 was overwritten"

    async def test_two_current_drafts_cannot_coexist(self, session, sequence):
        await store_arc(session, sequence=sequence, draft_set=arc(), shape=shape())
        touch = (
            await session.execute(
                select(Touch).where(Touch.sequence_id == sequence.id, Touch.step_no == 1)
            )
        ).scalar_one()

        session.add(Draft(touch_id=touch.id, version=2, body="Second", is_current=True))
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_a_regeneration_must_say_why(self, session, sequence):
        """"This isn't what I approved" has to be answerable."""
        await store_arc(session, sequence=sequence, draft_set=arc(), shape=shape())
        touch = (
            await session.execute(
                select(Touch).where(Touch.sequence_id == sequence.id, Touch.step_no == 1)
            )
        ).scalar_one()
        session.add(
            Draft(touch_id=touch.id, version=9, body="x", generated_as="regeneration")
        )
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_regeneration_after_the_content_is_written_is_refused(self, session, sequence):
        await store_arc(session, sequence=sequence, draft_set=arc(), shape=shape())
        await mark_content_written(session, sequence.id)
        touch = (
            await session.execute(
                select(Touch).where(Touch.sequence_id == sequence.id, Touch.step_no == 1)
            )
        ).scalar_one()

        with pytest.raises(ArcRejectedError, match="already been written"):
            await regenerate_draft(session, touch=touch, body="too late", reason="rep_guidance")


@requires_db
@pytest.mark.db
class TestContentIsWrittenInOneBatch:
    async def test_every_touch_shares_one_written_timestamp(self, session, sequence):
        """Per-step writes let a campaign start half-written, which is
        invisible until a recipient gets the wrong message."""
        await store_arc(session, sequence=sequence, draft_set=arc(), shape=shape())
        await mark_content_written(session, sequence.id)

        touches = list(
            (
                await session.execute(select(Touch).where(Touch.sequence_id == sequence.id))
            ).scalars()
        )
        assert all(t.content_sync_status == "written" for t in touches)
        assert len({t.content_written_at for t in touches}) == 1

    async def test_an_unmapped_step_blocks_the_write(self, session, sequence):
        partial = shape(attribute_map={"1": "custom_attribute_1"})
        await store_arc(session, sequence=sequence, draft_set=arc(), shape=partial)

        with pytest.raises(ArcRejectedError, match="no LGM attribute"):
            await mark_content_written(session, sequence.id)

    async def test_a_written_touch_must_name_its_attribute(self, session, sequence):
        session.add(
            Touch(
                sequence_id=sequence.id, step_no=1, day_offset=1, channel="email",
                content_sync_status="written",
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()


class TestTheFreshnessVerdictCannotRewrite:
    def test_it_has_no_field_for_replacement_copy(self):
        """Content is frozen on the lead, so a redraft here would differ from
        what LGM actually sends."""
        fields = set(FreshnessVerdict.model_fields)
        for forbidden in ("body", "subject", "draft", "replacement"):
            assert forbidden not in fields

    def test_a_stop_must_say_why(self):
        with pytest.raises(ValidationError, match="must carry a stop_reason"):
            FreshnessVerdict(proceed=False)

    def test_a_proceed_cannot_carry_a_stop_reason(self):
        with pytest.raises(ValidationError, match="cannot carry a stop_reason"):
            FreshnessVerdict(proceed=True, stop_reason="compliance")

    def test_a_clean_verdict_proceeds(self):
        assert FreshnessVerdict(proceed=True).stop_reason is None
