"""Where research looks is configuration, and the ICP decides it.

Two designs meet here and it is worth being explicit about the seam, because
every test below is really about one side of it.

**Retrieval** is decided by sources: a handful of places worth reading, chosen
once per ICP so that two accounts on one list are comparable — the same places
were read for both, and "Apex produced nothing" is a fact about Apex rather than
about what somebody decided to look for that day.

**Interpretation** is decided by signal types, and reads everything. A document
costs the same to digest whether one conclusion is drawn from it or twenty, so a
leadership change mentioned in a job posting is a leadership change. The old
design asked one search per signal type and threw most of that away.

What the registry must not lose is the reason it used to be a closed tuple in
code: a source key nothing runs reports as a permanent coverage gap on a
prospect who may be perfectly well covered, and nothing errors.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.account import Account, Run
from app.models.config import ResearchSource, SignalType
from app.models.research import ResearchCoverage
from app.services import sources
from app.services.research import build_plan

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"
    ),
]


@pytest.fixture
async def session():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
        await s.rollback()
    await engine.dispose()


def a_type(key, **over) -> SignalType:
    fields = {
        "key": key, "label": key.replace("_", " ").title(), "scope": "company",
        "default_ttl_days": 120, "produced_by": [], "status": "active",
    }
    fields.update(over)
    return SignalType(**fields)


def a_source(key, **over) -> ResearchSource:
    fields = {
        "key": key, "label": key.replace("_", " ").title(),
        "description": f"Whatever {key} carries.", "kind": "search",
        "scopes": ["company"], "status": "active", "builtin": False,
    }
    fields.update(over)
    return ResearchSource(**fields)


# ==========================================================================
# the registry still closes the hole the tuple closed
# ==========================================================================
class TestAClaimedSourceMustExist:
    """These moved here from test_config_api.py when the registry became a
    table. The guarantee is unchanged: a typo does not error anywhere — it
    reports forever as a coverage gap, indistinguishable from a prospect nobody
    could find anything about."""

    async def test_an_unknown_source_is_rejected_and_named(self, session):
        problems = await sources.validate(session, ["fundng"], "company")
        assert problems and "fundng" in problems[0]

    async def test_a_source_from_the_other_scope_is_rejected(self, session):
        problems = await sources.validate(session, ["enrichment"], "company")
        assert any("not available to company" in p for p in problems)

    async def _support_only(self, session) -> str:
        """A corroborating source, created here because none ships.

        `reviews` used to be the one. `review_sites`, its place-shaped
        replacement, was trialled against three accounts, found nothing at any
        of them, and was never stored (`c1f7e3b89d24`). The rule it exercised
        is still enforced, so the test keeps it alive without depending on a
        row somebody may retire next.
        """
        from app.models.config import ResearchSource

        session.add(
            ResearchSource(
                key="corroborating_only", label="Corroborating only",
                description="Repeated themes; never conclusive on its own.",
                kind="search", scopes=["company"], support_only=True,
            )
        )
        await session.flush()
        return "corroborating_only"

    async def test_a_support_only_source_alone_is_rejected(self, session):
        """A source that corroborates but never concludes (docs/06 §7.1 rule 1)
        cannot be a type's only source — that type could never fire."""
        key = await self._support_only(session)
        problems = await sources.validate(session, [key], "company")
        assert any("never create one" in p for p in problems)

    async def test_a_support_only_source_alongside_a_producer_is_fine(self, session):
        key = await self._support_only(session)
        assert await sources.validate(session, [key, "trade_press"], "company") == []

    async def test_the_seeded_sources_are_all_there(self, session):
        """The catalogue the product ships with, as places rather than topics.

        Seven loci and two routes after `c1f7e3b89d24`. This list and
        `query_families.QUERY_FAMILIES` are the same registry seen from two
        sides; when they drift, a test validates `produced_by` against a
        registry production does not have.
        """
        known = await sources.by_key(session)
        for key in (
            "company_site", "trade_press", "company_data_providers",
            "conference_and_podcast_circuit", "regulators_and_registers",
            "linkedin_index", "ats_boards", "enrichment", "manual",
        ):
            assert known[key].builtin is True, f"{key} missing from the seeded registry"
        assert known["company_site"].kind == "fetch"
        assert known["ats_boards"].kind == "fetch"
        assert known["enrichment"].kind == "provider"
        assert "reviews" not in known and "news" not in known, (
            "the topic-shaped rows should be gone"
        )


# ==========================================================================
# the ICP decides what runs
# ==========================================================================
class TestTheIcpsSourcesAreThePlan:
    async def test_a_source_runs_even_though_no_type_named_it(self, session):
        """An extra: the ICP's own idea, and the reason the ICP layer is not
        just arithmetic over the types."""
        session.add(a_type("mgt_change", produced_by=["leadership"]))
        await session.flush()
        plan = await build_plan(
            session, scope="company", type_keys={"mgt_change"},
            source_keys={"leadership", "news"},
        )
        assert plan.keys == ["leadership", "news"]
        assert plan.family("news").extra is True
        assert plan.family("leadership").extra is False

    async def test_a_source_a_type_named_but_the_icp_left_out_does_not_run(
        self, session
    ):
        """The ICP is the plan of record. Otherwise a rep who removed a source
        would watch it keep being read, and the cost line would be a lie."""
        session.add(a_type("mgt_change", produced_by=["leadership", "news"]))
        await session.flush()
        plan = await build_plan(
            session, scope="company", type_keys={"mgt_change"}, source_keys={"news"}
        )
        assert plan.keys == ["news"]

    async def test_dropping_a_types_only_source_is_soft(self, session):
        """It is less likely to be found, not impossible: extraction reads
        every document against every type. Saying "never runs" here would be
        the wrong warning, and reps act on warnings."""
        session.add(a_type("mgt_change", produced_by=["leadership"]))
        await session.flush()
        plan = await build_plan(
            session, scope="company", type_keys={"mgt_change"}, source_keys={"news"}
        )
        assert plan.orphan_types == ["mgt_change"]
        assert plan.targeting_is_fatal is False

    async def test_with_nothing_running_an_untargeted_type_is_fatal(self, session):
        session.add(a_type("mgt_change"))
        await session.flush()
        plan = await build_plan(session, scope="company", type_keys={"mgt_change"})
        assert plan.keys == []
        assert plan.orphan_types == ["mgt_change"]
        assert plan.targeting_is_fatal is True

    async def test_no_icp_sources_falls_back_to_what_the_types_claim(self, session):
        """How research behaved before sources were configurable. An ICP that
        has not been through the new screen must still research."""
        session.add(a_type("mgt_change", produced_by=["trade_press"]))
        await session.flush()
        plan = await build_plan(session, scope="company", type_keys={"mgt_change"})
        assert plan.keys == ["trade_press"]

    async def test_a_contact_source_stays_out_of_the_company_plan(self, session):
        # A contact-only search, added here because the shipped catalogue has
        # none: every place-shaped locus that reaches a person also reaches the
        # company it belongs to. The scope rule is unchanged and still worth
        # a test, so the fixture supplies the shape the catalogue no longer does.
        session.add(a_source("personal_newsletter", scopes=["contact"]))
        session.add(a_type("role_change", scope="contact", produced_by=["trade_press"]))
        await session.flush()
        plan = await build_plan(
            session, scope="company", type_keys={"role_change"},
            source_keys={"personal_newsletter"},
        )
        assert plan.keys == []

    async def test_a_paused_source_is_left_out(self, session):
        session.add(a_source("local_business_journal", status="paused"))
        session.add(a_type("mgt_change", produced_by=["trade_press"]))
        await session.flush()
        plan = await build_plan(
            session, scope="company", type_keys={"mgt_change"},
            source_keys={"trade_press", "local_business_journal"},
        )
        assert plan.keys == ["trade_press"]

    async def test_a_rep_added_source_carries_its_own_brief(self, session):
        """The point of the registry: a source a rep added reads exactly like
        one that shipped, with no deploy between wanting it and having it."""
        session.add(a_source("local_chamber_of_commerce", label="Local chamber of commerce",
                             description="Member directories and their newsletters."))
        await session.flush()
        plan = await build_plan(
            session, scope="company", source_keys={"local_chamber_of_commerce"}
        )
        planned = plan.family("local_chamber_of_commerce")
        assert planned.label == "Local chamber of commerce"
        assert planned.kind == "search"

    async def test_a_provider_source_is_never_fanned_out_over(self, session):
        """Apollo's waterfall spends credits and reports through verification.
        Running it as though it were a search charges for it twice and reports
        "coverage gap" when the truth is "no credential"."""
        plan = await build_plan(
            session, scope="contact", source_keys={"enrichment", "linkedin_index"}
        )
        assert plan.keys == ["linkedin_index"]


# ==========================================================================
# what it has produced, and where it should stop being tried
# ==========================================================================
class TestASourceHasToEarnItsPlace:
    async def _coverage(self, session, *, account, family, status, count=0, detail=None,
                        ago=0):
        run = Run(account_id=account, stage="research", status="succeeded")
        session.add(run)
        await session.flush()
        row = ResearchCoverage(
            run_id=run.id, account_id=account, family=family, status=status,
            evidence_count=count, detail=detail,
        )
        session.add(row)
        await session.flush()
        if ago:
            row.created_at = datetime.now(UTC) - timedelta(days=ago)
            await session.flush()
        return row

    async def test_a_source_read_everywhere_and_giving_nothing_is_flagged(self, session):
        """A registry only ever grows. Without this, a source added in March is
        still costing a read per account in December and nobody knows."""
        await session.execute(delete(ResearchCoverage))
        account = Account(name="Northwind", domain="northwind.test")
        session.add(account)
        await session.flush()
        for _ in range(6):
            await self._coverage(session, account=account.id, family="reviews",
                                 status="empty")
        await self._coverage(session, account=account.id, family="news",
                             status="ran", count=4)

        health = await sources.health(session)
        assert health["reviews"].is_dead_weight is True
        assert health["news"].is_dead_weight is False
        assert health["news"].evidence == 4

    async def test_an_empty_read_still_counts_as_an_attempt(self, session):
        """Read from coverage rather than evidence, because the interesting
        case is the source that was read and gave nothing — which no evidence
        row can express."""
        await session.execute(delete(ResearchCoverage))
        account = Account(name="Apex", domain="apex.test")
        session.add(account)
        await session.flush()
        await self._coverage(session, account=account.id, family="hiring", status="empty")
        health = await sources.health(session)
        assert health["hiring"].attempts == 1
        assert health["hiring"].evidence == 0

    async def test_repeated_failure_at_one_account_quarantines_it_there(self, session):
        """Per account, not globally: a site that blocks our agent blocks it
        for that company only."""
        account = Account(name="Stripe", domain="stripe.test")
        session.add(account)
        await session.flush()
        for _ in range(sources.QUARANTINE_AFTER):
            await self._coverage(session, account=account.id, family="company_site",
                                 status="failed", detail="robots.txt disallows /")

        held = await sources.quarantined(session, account.id)
        assert "company_site" in held
        assert "robots.txt" in held["company_site"]

    async def test_one_success_ends_the_streak(self, session):
        """A site that came back must be read again. A quarantine that never
        lifts is the silent hole this module exists to prevent."""
        account = Account(name="Bluewave", domain="bluewave.test")
        session.add(account)
        await session.flush()
        for _ in range(sources.QUARANTINE_AFTER):
            await self._coverage(session, account=account.id, family="news",
                                 status="failed", detail="timeout", ago=3)
        await self._coverage(session, account=account.id, family="news",
                             status="ran", count=2)

        assert "news" not in await sources.quarantined(session, account.id)

    async def test_an_empty_answer_is_not_a_failure(self, session):
        """Empty is an answer — there is nothing there. Failed is "we do not
        know". Quarantining on empty would stop reading quiet companies."""
        account = Account(name="Quiet Co", domain="quiet.test")
        session.add(account)
        await session.flush()
        for _ in range(5):
            await self._coverage(session, account=account.id, family="funding",
                                 status="empty")
        assert await sources.quarantined(session, account.id) == {}


class TestEveryFetchSourceHasAReader:
    """A `fetch` source is dispatched to a reader by its registry key.

    `c1f7e3b89d24` renamed `job_board` to `ats_boards` and the dispatch table in
    `pipeline` was not part of the rename. The source went active with no
    reader, and the next run that planned it would have raised
    `no reader for fetch source 'ats_boards'` — at research time, per account,
    after the sweep had already been paid for.

    Asserted against the registry rather than a list kept here, because a list
    kept here is the thing that drifted.
    """

    async def test_the_registry_and_the_dispatch_table_agree(self, session):
        from app.services import job_boards, site_sweep

        # The same mapping `pipeline._run_family` builds. Kept in one place in
        # the test so a third fetch source added without a reader fails here
        # rather than in production.
        readers = {
            "company_site": site_sweep.sweep_account,
            "ats_boards": job_boards.sweep_account,
        }
        registry = await sources.all_sources(session)
        fetches = {s.key for s in registry if s.kind == "fetch"}
        assert fetches, "no fetch sources at all means this test proves nothing"
        assert fetches <= set(readers), (
            f"fetch sources with no reader: {sorted(fetches - set(readers))}"
        )
