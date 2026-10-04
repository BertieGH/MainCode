"""Phase 4: CRM first, gaps reported, and a plan that comes from the registry."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.account import Account
from app.models.config import SignalType
from app.models.research import ResearchCoverage
from app.services.crm import CrmAccount, CrmUnavailableError, StubCrmAdapter
from app.services.pipeline import resolve, run_research
from app.services.research import build_plan

pytestmark = pytest.mark.db

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
async def account(session):
    # `resolved` because these tests are about research, not identity. The
    # gate that refuses an unconfirmed account has its own tests below —
    # leaving this unresolved would make every test here fail for a reason
    # unrelated to what it is checking.
    row = Account(
        name="Meridian Cloud",
        domain="MERIDIANCLOUD.IO",
        resolution_status="resolved",
    )
    session.add(row)
    session.add_all(
        [
            SignalType(
                key="funding", label="Funding", scope="company",
                default_ttl_days=300, produced_by=["funding", "news"],
            ),
            SignalType(
                key="engineering_scaling", label="Hiring surge", scope="company",
                default_ttl_days=60, produced_by=["hiring"],
            ),
        ]
    )
    await session.flush()
    return row


class Recorder:
    """A family runner that records the order it was asked, and when."""

    def __init__(self, counts: dict[str, int] | None = None, explode: set[str] | None = None):
        self.counts = counts or {}
        self.explode = explode or set()
        self.calls: list[str] = []

    async def __call__(self, account: Account, family: str) -> int:
        self.calls.append(family)
        if family in self.explode:
            raise RuntimeError(f"{family} provider is down")
        return self.counts.get(family, 0)


@requires_db
class TestIdentityIsCheckedBeforeTheCrm:
    """Research on an unconfirmed company is the expensive silent failure.

    It *succeeds*: the evidence parses, the signals cite it, the score computes
    and the draft reads well — about a different business. Nothing downstream
    can tell, which is why the refusal lives at the top of the pipeline rather
    than with whoever calls it.

    Not theoretical: a live tier-0 run returned three invented companies at
    1.00 confidence because the fallback model was shown their domains and
    agreed with them. Without this gate they would have been researched in
    full.
    """

    @pytest.mark.parametrize(
        "status", ["unresolved", "needs_review", "rejected"]
    )
    async def test_an_unconfirmed_identity_stops_research(
        self, session, account, status
    ):
        account.resolution_status = status
        await session.flush()
        called: list[str] = []

        async def runner(acc, family):
            called.append(family)
            return 1

        result = await run_research(
            session, account=account, crm=StubCrmAdapter(), run_family=runner
        )
        assert result.halted is not None
        assert status in result.halted
        assert called == [], "spent research on an unverified company"

    async def test_it_is_refused_before_the_crm_is_even_asked(self, session, account):
        """Identity is cheaper to check than the CRM, and gates more."""
        account.resolution_status = "needs_review"
        await session.flush()
        asked: list[str] = []

        class SpyCrm:
            async def find_account(self, *, domain=None, name=None):
                asked.append(domain or name or "?")
                return None

        result = await run_research(
            session, account=account, crm=SpyCrm(),
            run_family=lambda a, f: None,
        )
        assert result.halted is not None
        assert asked == [], "asked the CRM about a company nobody had confirmed"

    async def test_a_confirmed_identity_proceeds(self, session, account):
        account.resolution_status = "resolved"
        await session.flush()

        async def runner(acc, family):
            return 1

        result = await run_research(
            session, account=account, crm=StubCrmAdapter(), run_family=runner
        )
        assert result.halted is None


class TestTheCrmIsCheckedFirst:
    async def test_an_unreachable_crm_stops_research_before_it_starts(self, session, account):
        """Not a soft failure. Researching without the CRM means prospecting
        blind into a book we cannot see — which is the exact outcome the
        CRM-first rule exists to prevent."""
        crm = StubCrmAdapter(available=False)
        runner = Recorder({"funding": 3})

        result = await run_research(
            session, account=account, crm=crm, run_family=runner
        )

        assert result.researched is False
        assert runner.calls == [], "a family ran despite the CRM being unreachable"
        assert "CRM" in result.halted

    async def test_absence_from_the_crm_is_not_unavailability(self, session, account):
        """`None` means genuinely not there, and research proceeds. Conflating
        the two would either halt on every new prospect or prospect every
        existing customer."""
        resolution = await resolve(session, account=account, crm=StubCrmAdapter())
        assert resolution.known_to_crm is False
        assert resolution.may_research is True

    async def test_a_known_account_carries_its_owner_through(self, session, account):
        crm = StubCrmAdapter(
            accounts={
                "MERIDIANCLOUD.IO": CrmAccount(
                    crm_id="crm-1", name="Meridian Cloud", owner="priya",
                    notes=("Renewal in March.",),
                )
            }
        )
        resolution = await resolve(session, account=account, crm=crm)

        assert resolution.known_to_crm is True
        assert resolution.owner == "priya"
        assert resolution.notes == ("Renewal in March.",)

    async def test_the_stub_raises_rather_than_returning_none_when_down(self):
        with pytest.raises(CrmUnavailableError):
            await StubCrmAdapter(available=False).find_account(domain="x.io", name="X")


@requires_db
class TestThePlanComesFromTheRegistry:
    async def test_families_are_the_union_of_what_active_types_declare(self, session, account):
        plan = await build_plan(session)
        assert plan.keys == ["funding", "hiring", "news"], "sorted, and deduplicated"

    async def test_a_family_knows_which_conclusions_depend_on_it(self, session, account):
        """A gap has to say what it cost. "hiring found nothing" is only
        actionable once it reads as "so engineering_scaling is unreachable"."""
        plan = await build_plan(session)
        assert plan.family("hiring").feeds == ("engineering_scaling",)
        assert plan.family("news").feeds == ("funding",)

    async def test_a_paused_type_drops_out_of_the_plan(self, session, account):
        """Otherwise pausing spends provider budget gathering evidence that no
        active signal will ever cite."""
        st = (
            await session.execute(
                select(SignalType).where(SignalType.key == "engineering_scaling")
            )
        ).scalar_one()
        st.status = "paused"
        from datetime import UTC, datetime

        st.paused_at = datetime.now(UTC)
        await session.flush()

        plan = await build_plan(session)
        assert "hiring" not in plan.keys

    async def test_a_type_with_no_family_is_flagged_not_silently_ignored(self, session, account):
        session.add(
            SignalType(key="orphan", label="Orphan", scope="company", default_ttl_days=30)
        )
        await session.flush()

        plan = await build_plan(session)
        assert "orphan" in plan.orphan_types

    async def test_the_plan_order_is_stable(self, session, account):
        """The prompt is built from this. Set-ordered families would change the
        bytes between runs and silently cost the cache every time."""
        first = await build_plan(session)
        second = await build_plan(session)
        assert first.keys == second.keys


@requires_db
class TestCoverageAndGaps:
    async def test_a_family_that_finds_nothing_is_recorded_not_omitted(self, session, account):
        runner = Recorder({"funding": 4})  # hiring and news return 0

        result = await run_research(
            session, account=account, crm=StubCrmAdapter(), run_family=runner
        )

        rows = {
            r.family: r
            for r in (
                await session.execute(
                    select(ResearchCoverage).where(ResearchCoverage.run_id == result.run_id)
                )
            ).scalars()
        }
        assert set(rows) == {"funding", "hiring", "news"}, "every planned family is recorded"
        assert rows["funding"].status == "ran"
        assert rows["hiring"].status == "empty"
        assert rows["news"].status == "empty"

    async def test_gaps_name_the_conclusions_they_cost(self, session, account):
        runner = Recorder({"funding": 2, "news": 1})
        result = await run_research(
            session, account=account, crm=StubCrmAdapter(), run_family=runner
        )

        gaps = {g.family: g for g in result.gaps}
        assert set(gaps) == {"hiring"}
        assert gaps["hiring"].unreachable == ("engineering_scaling",)

    async def test_a_failed_family_is_not_the_same_as_an_empty_one(self, session, account):
        """Empty is intelligence — there is no funding news about this company.
        Failed is ignorance. A rep shown both as blank walks away from a live
        prospect believing it was quiet."""
        runner = Recorder({"funding": 1, "news": 1}, explode={"hiring"})
        result = await run_research(
            session, account=account, crm=StubCrmAdapter(), run_family=runner
        )

        gap = next(g for g in result.gaps if g.family == "hiring")
        assert gap.is_failure is True
        assert "provider is down" in gap.detail

    async def test_one_failing_family_does_not_lose_the_others(self, session, account):
        runner = Recorder({"funding": 5, "news": 2}, explode={"hiring"})
        result = await run_research(
            session, account=account, crm=StubCrmAdapter(), run_family=runner
        )

        assert result.evidence_by_family == {"funding": 5, "news": 2}
        assert result.researched is True

    async def test_every_planned_family_is_actually_attempted(self, session, account):
        runner = Recorder()
        await run_research(
            session, account=account, crm=StubCrmAdapter(), run_family=runner
        )
        assert sorted(runner.calls) == ["funding", "hiring", "news"]


@requires_db
class TestCoverageKeepsWhatWasSearched:
    """An `empty` family used to say "nothing found" and nothing more — not
    what had been looked for, which is what makes an empty result trustworthy.
    And a family that ran could not be opened: evidence knew its run, never
    its family."""

    async def _coverage(self, session, run_id):
        return {
            r.family: r
            for r in (
                await session.execute(
                    select(ResearchCoverage).where(ResearchCoverage.run_id == run_id)
                )
            ).scalars()
        }

    async def test_what_an_empty_family_searched_for_is_kept(self, session, account):
        from app.services.pipeline import FamilyOutcome

        async def runner(acc, family):
            if family == "hiring":
                return FamilyOutcome(stored=0, not_found=("QA engineer openings", "careers page"))
            return FamilyOutcome(stored=1)

        result = await run_research(
            session, account=account, crm=StubCrmAdapter(), run_family=runner
        )
        rows = await self._coverage(session, result.run_id)
        assert rows["hiring"].status == "empty"
        assert rows["hiring"].not_found == ["QA engineer openings", "careers page"]
        assert rows["funding"].not_found == []

    async def test_a_runner_returning_a_bare_count_still_works(self, session, account):
        result = await run_research(
            session, account=account, crm=StubCrmAdapter(),
            run_family=Recorder({"funding": 2}),
        )
        rows = await self._coverage(session, result.run_id)
        assert rows["funding"].evidence_count == 2
        assert rows["funding"].not_found == []

    async def test_stored_evidence_records_the_family_that_found_it(
        self, session, account, monkeypatch
    ):
        """What makes a coverage row openable. Only the first family stores
        the shared passage — the rest see a duplicate, so it is filed under
        the one search that actually found it first."""
        import uuid as _uuid

        from app.models.signal import Evidence
        from app.schemas.evidence import EvidenceBatch, FoundEvidence
        from app.services import llm, pipeline

        batch = EvidenceBatch(
            evidence=[
                FoundEvidence(
                    source_type="news",
                    source_url="https://example.com/a",
                    excerpt="Meridian opened six QA roles.",
                )
            ],
            not_found=["salary bands"],
        )

        async def fake_research(session, *, account, family, client=None):
            return llm.CallResult(parsed=batch)

        monkeypatch.setattr("app.services.stages.research_family", fake_research)
        run_id = _uuid.uuid4()
        result = await run_research(
            session, account=account, crm=StubCrmAdapter(),
            run_family=pipeline.llm_family_runner(session, run_id=run_id),
            run_id=run_id,
        )

        rows = list(
            (await session.execute(select(Evidence).where(Evidence.run_id == run_id))).scalars()
        )
        assert len(rows) == 1
        assert rows[0].family == "funding", "filed under the first family, which found it"
        coverage = await self._coverage(session, result.run_id)
        assert coverage["funding"].evidence_count == 1
        assert coverage["hiring"].status == "empty", "a duplicate is not new ground"
        assert coverage["hiring"].not_found == ["salary bands"]


@requires_db
class TestTheReuseWindow:
    """Families answered inside the window are left out of a run — not run,
    not recorded, and not reported as a gap, because the answer exists."""

    async def test_skipped_families_are_not_run_and_are_named(self, session, account):
        runner = Recorder({"hiring": 1})
        result = await run_research(
            session, account=account, crm=StubCrmAdapter(), run_family=runner,
            skip_families=frozenset({"funding", "news"}),
        )
        assert runner.calls == ["hiring"]
        assert result.reused == ("funding", "news")
        assert result.gaps == [], "a reused family reported as 'not reached'"
        assert result.status == "complete"

    async def test_a_quarantined_source_is_recorded_rather_than_dropped(
        self, session, account
    ):
        """Skipped, with the reason, and visible as a gap.

        A source that stops being read without saying so is worse than one that
        fails: the account looks covered. That is the difference between a
        quiet prospect and one whose site has been blocking us for a month.
        """
        runner = Recorder({"hiring": 1})
        result = await run_research(
            session, account=account, crm=StubCrmAdapter(), run_family=runner,
            quarantined={"funding": "failed 3 times running — robots.txt disallows /"},
        )
        assert "funding" not in runner.calls, "a quarantined source was still read"
        gap = next(g for g in result.gaps if g.family == "funding")
        assert gap.status == "skipped"
        assert "robots.txt" in (gap.detail or "")

    async def test_a_failure_beside_reused_families_is_partial(self, session, account):
        """Some of the answer is current; that is not a failed account."""
        result = await run_research(
            session, account=account, crm=StubCrmAdapter(),
            run_family=Recorder(explode={"hiring"}),
            skip_families=frozenset({"funding", "news"}),
        )
        assert result.status == "partial"
        assert await _research_status(session, account) == "partial"

    async def test_the_window_counts_answers_not_failures(self, session, account):
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import update

        from app.services.research import fresh_families

        await run_research(
            session, account=account, crm=StubCrmAdapter(),
            run_family=Recorder({"funding": 1}, explode={"news"}),
        )
        fresh = await fresh_families(session, account.id, days=30)
        assert set(fresh) == {"funding", "hiring"}, "a failed family is not an answer"

        await session.execute(
            update(ResearchCoverage)
            .where(ResearchCoverage.account_id == account.id, ResearchCoverage.family == "hiring")
            .values(created_at=datetime.now(UTC) - timedelta(days=45))
        )
        fresh = await fresh_families(session, account.id, days=30)
        assert set(fresh) == {"funding"}, "an answer older than the window was reused"


async def _research_status(session, account) -> str:
    # Read back rather than off the instance: the column has a server default,
    # and touching an unloaded attribute on an async session raises.
    return (
        await session.execute(select(Account.research_status).where(Account.id == account.id))
    ).scalar_one()


@requires_db
class TestTheAccountRecordsWhereItsResearchStands:
    """The list showed `not_started` beside a report saying the account had
    just been researched. The pipeline wrote a run and its coverage, and never
    the account."""

    async def test_every_family_answering_is_complete(self, session, account):
        await run_research(
            session, account=account, crm=StubCrmAdapter(),
            run_family=Recorder({"funding": 1}),
        )
        assert await _research_status(session, account) == "complete"

    async def test_some_families_failing_is_partial(self, session, account):
        result = await run_research(
            session, account=account, crm=StubCrmAdapter(),
            run_family=Recorder({"funding": 1}, explode={"hiring"}),
        )
        assert result.status == "partial"
        assert await _research_status(session, account) == "partial"

    async def test_every_family_failing_is_failed_not_researched(self, session, account):
        """Nothing was looked at, however cleanly the run finished."""
        from app.models.account import Run

        result = await run_research(
            session, account=account, crm=StubCrmAdapter(),
            run_family=Recorder(explode={"funding", "hiring", "news"}),
        )
        assert result.researched is False
        assert result.status == "failed"
        assert await _research_status(session, account) == "failed"
        run = await session.get(Run, result.run_id)
        assert run.status == "failed"
        assert "provider is down" in run.error

    async def test_an_unconfirmed_identity_leaves_it_untouched(self, session, account):
        """Not attempted by design — that is not a research failure."""
        account.resolution_status = "needs_review"
        await session.flush()
        await run_research(
            session, account=account, crm=StubCrmAdapter(), run_family=Recorder()
        )
        assert await _research_status(session, account) == "not_started"
