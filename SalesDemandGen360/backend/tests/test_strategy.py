"""Phase 6: persona × service weighting, the thread cap, and differentiation."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.account import Account, Contact
from app.models.config import ServiceCatalog
from app.models.strategy import Strategy, StrategyThread
from app.services.strategy import (
    DifferentiationError,
    PersonaInput,
    ServiceInput,
    assert_differentiated,
    build_matrix,
    check_triggers,
    select_threads,
)

TEST_DB = os.getenv("TEST_DATABASE_URL")
requires_db = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")

ROLE_WEIGHTS = {"economic_buyer": 60, "champion": 45, "technical_buyer": 40, "user": 15}

CTO = uuid.UUID(int=1)
CFO = uuid.UUID(int=2)
DEV = uuid.UUID(int=3)
QA_SVC = uuid.UUID(int=10)
DATA_SVC = uuid.UUID(int=11)


def personas(**over) -> list[PersonaInput]:
    base = [
        PersonaInput(CTO, "Dana Reyes", buying_role="technical_buyer"),
        PersonaInput(CFO, "Sam Okafor", buying_role="economic_buyer"),
        PersonaInput(DEV, "Lee Park", buying_role="user"),
    ]
    return over.get("personas", base)


def services() -> list[ServiceInput]:
    return [
        ServiceInput(QA_SVC, "qa", target_personas=("technical_buyer", "user")),
        ServiceInput(DATA_SVC, "data", target_personas=()),
    ]


def matrix(people=None, **kw) -> list:
    return build_matrix(
        people or personas(), services(), persona_role_weights=ROLE_WEIGHTS, **kw
    )


class TestTheMatrixKeepsWhatDidNotHappen:
    def test_every_persona_service_pair_is_present(self):
        """"Why didn't we contact the CEO?" has no answer if only the
        activated combinations were stored."""
        cells = matrix()
        assert len(cells) == 3 * 2
        assert {(c.contact_id, c.service_id) for c in cells} == {
            (p, s) for p in (CTO, CFO, DEV) for s in (QA_SVC, DATA_SVC)
        }

    def test_a_zero_weighted_cell_still_records_why(self):
        unreachable = [PersonaInput(CTO, "Dana", buying_role="technical_buyer", contactable=False)]
        cell = matrix(unreachable)[0]
        assert cell.weight == 0
        assert "no verified contact route" in cell.rationale

    def test_a_service_that_does_not_target_the_role_is_discounted_not_dropped(self):
        cells = {(c.contact_id, c.service_id): c for c in matrix()}
        targeted = cells[(CTO, QA_SVC)]
        untargeted_role = cells[(CFO, QA_SVC)]

        assert untargeted_role.weight < targeted.weight
        assert untargeted_role.weight > 0, "it stays in the matrix as a considered option"
        assert "does not target" in untargeted_role.rationale

    def test_an_unmapped_role_gets_the_default_rather_than_vanishing(self):
        odd = [PersonaInput(CTO, "Dana", buying_role="procurement")]
        assert matrix(odd)[0].weight > 0


class TestContactSignalsMovePersonaRanking:
    def test_a_signal_promotes_a_persona_above_a_higher_ranked_role(self):
        """`docs/02`: evidence about someone beats a guess from their title.
        Without this the ranking is title-ordering with extra steps."""
        plain = select_threads(
            matrix(),
            persona_weight_threshold=10,
            max_concurrent_threads=2,
            thread_start_offset_days=3,
        )
        assert plain[0].contact_id == CFO, "economic_buyer leads on title alone"

        with_signal = select_threads(
            matrix(
                [
                    PersonaInput(
                        CTO, "Dana", buying_role="technical_buyer",
                        signals=((uuid.uuid4(), "high"),),
                    ),
                    PersonaInput(CFO, "Sam", buying_role="economic_buyer"),
                    PersonaInput(DEV, "Lee", buying_role="user"),
                ]
            ),
            persona_weight_threshold=10,
            max_concurrent_threads=2,
            thread_start_offset_days=3,
        )
        assert with_signal[0].contact_id == CTO, "evidence about the person did not move ranking"

    def test_signal_strength_is_reflected_in_the_weight(self):
        def top_weight(strength):
            cells = matrix(
                [PersonaInput(CTO, "Dana", buying_role="technical_buyer",
                              signals=((uuid.uuid4(), strength),))]
            )
            return max(c.weight for c in cells)

        assert top_weight("high") > top_weight("medium") > top_weight("low")

    def test_extra_signals_add_less_each_time(self):
        """Five signals about one person is not five times the reason to
        contact them, and undamped volume would crowd out a better persona."""
        def weight(n):
            cells = matrix(
                [PersonaInput(CTO, "Dana", buying_role="technical_buyer",
                              signals=tuple((uuid.uuid4(), "high") for _ in range(n)))]
            )
            return max(c.weight for c in cells)

        first = weight(1) - weight(0)
        second = weight(2) - weight(1)
        third = weight(3) - weight(2)
        assert first > second > third

    def test_the_cited_signals_are_recorded_on_the_cell(self):
        sid = uuid.uuid4()
        cells = matrix(
            [PersonaInput(CTO, "Dana", buying_role="technical_buyer", signals=((sid, "high"),))]
        )
        assert str(sid) in cells[0].evidence_ids


class TestTheThreadCapHolds:
    def _threads(self, cap=2, threshold=10):
        return select_threads(
            matrix(),
            persona_weight_threshold=threshold,
            max_concurrent_threads=cap,
            thread_start_offset_days=3,
        )

    def test_only_the_cap_is_activated(self):
        threads = self._threads(cap=2)
        active = [t for t in threads if t.thread_status.startswith("active")]
        assert len(active) == 2

    def test_a_cap_of_one_leaves_a_single_primary(self):
        threads = self._threads(cap=1)
        assert [t.thread_status for t in threads] == [
            "active_primary", "queued", "queued",
        ]

    def test_exactly_one_primary_and_it_ranks_first(self):
        threads = self._threads()
        primaries = [t for t in threads if t.thread_status == "active_primary"]
        assert len(primaries) == 1
        assert primaries[0].rank == 1

    def test_above_the_threshold_but_beyond_the_cap_is_queued_not_rejected(self):
        """"Not yet" and "no" are different facts about a persona."""
        threads = self._threads(cap=1, threshold=10)
        assert all(t.thread_status != "not_activated" for t in threads)
        assert sum(t.thread_status == "queued" for t in threads) == 2

    def test_below_the_threshold_is_not_activated_even_with_room(self):
        threads = self._threads(cap=3, threshold=1000)
        assert all(t.thread_status == "not_activated" for t in threads)

    def test_one_thread_per_contact_not_one_per_service(self):
        """A person contacted twice about the same account is the failure this
        layer prevents; it does not stop being one because the second message
        is about a different service."""
        threads = self._threads()
        assert len({t.contact_id for t in threads}) == len(threads)

    def test_active_threads_are_staggered(self):
        threads = [t for t in self._threads() if t.thread_status.startswith("active")]
        assert [t.start_offset_days for t in threads] == [0, 3]

    def test_offsets_count_activated_threads_not_rank(self):
        """A not_activated persona between two active ones must not push the
        second one's start date out."""
        people = [
            PersonaInput(CFO, "Sam", buying_role="economic_buyer"),
            PersonaInput(DEV, "Lee", buying_role="user"),          # below threshold
            PersonaInput(CTO, "Dana", buying_role="technical_buyer"),
        ]
        threads = select_threads(
            build_matrix(people, services(), persona_role_weights=ROLE_WEIGHTS),
            persona_weight_threshold=30,
            max_concurrent_threads=2,
            thread_start_offset_days=3,
        )
        active = [t for t in threads if t.thread_status.startswith("active")]
        assert [t.start_offset_days for t in active] == [0, 3]

    def test_ranking_is_stable_across_runs(self):
        """Two equally weighted services must not produce a different primary
        each time the strategy is rebuilt."""
        first = self._threads()
        second = self._threads()
        assert [(t.contact_id, t.service_id, t.rank) for t in first] == [
            (t.contact_id, t.service_id, t.rank) for t in second
        ]


class TestTwoPersonasMustArgueDifferently:
    def test_identical_hypotheses_are_refused(self):
        """Two people at one company receiving the same argument is how an
        account learns it is being automated at."""
        with pytest.raises(DifferentiationError, match="same problem hypothesis"):
            assert_differentiated(
                {CTO: "Scaling pains after the raise.", CFO: "Scaling pains after the raise."}
            )

    def test_whitespace_and_case_do_not_disguise_a_duplicate(self):
        with pytest.raises(DifferentiationError):
            assert_differentiated(
                {CTO: "Scaling pains.", CFO: "  scaling   PAINS.  "}
            )

    def test_genuinely_different_hypotheses_pass(self):
        assert_differentiated(
            {
                CTO: "Hiring six engineers without a QA function to absorb them.",
                CFO: "Burn rate rising faster than headcount productivity.",
            }
        )


class TestTriggersMustStillBeLive:
    def test_a_stale_trigger_is_reported(self):
        """"I saw you raised a round" about a round from two years ago reads as
        automation that did not check."""
        live, stale = str(uuid.uuid4()), str(uuid.uuid4())
        assert check_triggers([live, stale], {live}) == [stale]

    def test_all_live_triggers_pass(self):
        a, b = str(uuid.uuid4()), str(uuid.uuid4())
        assert check_triggers([a, b], {a, b}) == []


@requires_db
@pytest.mark.db
class TestTheDatabaseEnforcesTheShape:
    @pytest.fixture
    async def session(self):
        engine = create_async_engine(TEST_DB)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as s:
            yield s
            await s.rollback()
        await engine.dispose()

    @pytest.fixture
    async def world(self, session):
        account = Account(name="Meridian Cloud", domain="MERIDIANCLOUD.IO")
        service = ServiceCatalog(code="qa", name="QA engineering", description="d")
        session.add_all([account, service])
        await session.flush()
        contact = Contact(account_id=account.id, full_name="Dana Reyes")
        strategy = Strategy(account_id=account.id, version=1)
        session.add_all([contact, strategy])
        await session.flush()
        return {"account": account, "service": service, "contact": contact, "strategy": strategy}

    def _thread(self, world, **over):
        base = dict(
            strategy_id=world["strategy"].id,
            contact_id=world["contact"].id,
            service_id=world["service"].id,
            weight=60,
            rank=1,
            thread_status="active_primary",
            problem_hypothesis="Scaling pains",
            trigger_summary="Series B",
            trigger_signal_ids=[str(uuid.uuid4())],
            positioning="QA as the absorber",
            channel_sequence=["linkedin", "email"],
            cta="15 minutes next week",
        )
        return StrategyThread(**{**base, **over})

    async def test_a_thread_without_a_trigger_is_rejected(self, session, world):
        session.add(self._thread(world, trigger_signal_ids=[]))
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_a_primary_thread_must_rank_first(self, session, world):
        session.add(self._thread(world, rank=2))
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_one_contact_cannot_hold_two_threads_in_a_strategy(self, session, world):
        session.add(self._thread(world))
        await session.flush()
        session.add(self._thread(world, rank=2, thread_status="active_secondary"))
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_a_valid_thread_persists_with_its_fields_intact(self, session, world):
        row = self._thread(world)
        session.add(row)
        await session.flush()

        found = await session.get(StrategyThread, row.id)
        assert found is not None
        assert found.thread_status == "active_primary"
        assert found.channel_sequence == ["linkedin", "email"]
        assert len(found.trigger_signal_ids) == 1
        assert found.start_offset_days == 0, "the primary starts immediately"
