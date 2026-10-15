"""Making research reachable, and what the route refuses.

The pipeline was written, tested and unreachable — no endpoint called it. This
is that endpoint, and its job is mostly restraint: research is several model
calls per account with web search attached, so the interesting behaviour is
what it declines to do rather than what it does.

Three things it must get right, each of which costs real money or real trust:

* **Unresolved accounts are skipped and counted**, not attempted. The pipeline
  refuses them anyway; counting them here is what lets the report say *why*
  nothing happened, so a rep is sent to the curation screen rather than left
  with a bare "0 researched".
* **One account's failure costs one account.** A batch that aborts halfway has
  spent the money and recorded less than it paid for.
* **The cap is real.** A forgotten limit on a 5,000-row list is discovered by
  the bill.
"""

from __future__ import annotations

import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_session
from app.main import create_app

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.getenv("TEST_DATABASE_URL"),
        reason="TEST_DATABASE_URL not set — these write real rows",
    ),
]


@pytest.fixture
async def api(monkeypatch):
    """A client with the model stubbed out.

    Nothing here reaches a vendor. `run_research` is replaced wholesale so the
    route's own decisions — who is attempted, what is counted, what is
    refused — are what the tests observe.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.models.account import Account, AccountList, AccountListMember

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async with maker() as seed:
        lst = AccountList(label="research", source="csv", created_by="tests")
        seed.add(lst)
        await seed.flush()
        made = []
        for name, status in (
            ("Confirmed One", "resolved"),
            ("Confirmed Two", "resolved"),
            ("Still Checking", "needs_review"),
            ("Never Looked", "unresolved"),
        ):
            acc = Account(name=name, resolution_status=status)
            seed.add(acc)
            await seed.flush()
            seed.add(AccountListMember(list_id=lst.id, account_id=acc.id))
            made.append(acc)
        await seed.commit()
        ids = {"list": lst.id, "accounts": [a.id for a in made]}

    app = create_app()

    async def _session():
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = _session

    # The model never runs.
    from app.services import llm, pipeline

    async def allow(*a, **k):
        return None

    monkeypatch.setattr(llm, "assert_may_call", allow)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        c.ids = ids  # type: ignore[attr-defined]
        c.pipeline = pipeline  # type: ignore[attr-defined]
        c.monkeypatch = monkeypatch  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


def stub_runs(
    api,
    *,
    per_account=None,
    explode: set[str] | None = None,
    failed_families: dict[str, str] | None = None,
    runs: list | None = None,
    skips: dict | None = None,
):
    """Replace `run_research` with something that records who was asked.

    `runs`, when given, collects `(run_id, runner)` per call — the runner is a
    marker carrying the run id it was built with, so a test can check the two
    agree.
    """
    from app.services import pipeline

    seen: list[str] = []
    explode = explode or set()
    if per_account is None:
        per_account = {} if failed_families else {"funding": 2}

    async def fake(session, *, account, crm, run_family, run_id=None,
                   triggered_by="system", skip_families=frozenset(), **kwargs):
        seen.append(account.name)
        if runs is not None:
            runs.append((run_id, run_family))
        if skips is not None:
            skips[account.name] = set(skip_families)
        if account.name in explode:
            raise RuntimeError("provider exploded")
        return pipeline.RunResult(
            run_id=run_id or uuid.uuid4(),
            evidence_by_family=dict(per_account),
            failed_families=dict(failed_families or {}),
        )

    api.monkeypatch.setattr(pipeline, "run_research", fake)
    api.monkeypatch.setattr(
        pipeline, "llm_family_runner", lambda session, **k: ("runner", k.get("run_id"))
    )
    return seen


def url(api) -> str:
    return f"/api/lists/{api.ids['list']}/run-research"


class TestOnlyConfirmedAccountsAreResearched:
    async def test_unresolved_accounts_are_skipped_and_counted(self, api):
        seen = stub_runs(api)
        body = (await api.post(url(api), params={"limit": 10})).json()

        assert body["ran"] is True
        assert body["attempted"] == 2
        assert body["skipped_unresolved"] == 2
        assert sorted(seen) == ["Confirmed One", "Confirmed Two"]

    async def test_the_count_is_what_sends_a_rep_somewhere_useful(self, api):
        """"0 researched" explains nothing. "2 unconfirmed" explains where to go."""
        stub_runs(api)
        body = (await api.post(url(api), params={"limit": 10})).json()
        assert body["skipped_unresolved"] == 2

    async def test_a_list_with_nothing_confirmed_is_blocked_not_silent(self, api):
        from sqlalchemy import update

        from app.models.account import Account

        async for session in api._transport.app.dependency_overrides[get_session]():
            await session.execute(
                update(Account)
                .where(Account.id.in_(api.ids["accounts"]))
                .values(resolution_status="needs_review")
            )
            await session.commit()
            break

        seen = stub_runs(api)
        body = (await api.post(url(api), params={"limit": 10})).json()

        assert body["attempted"] == 0
        assert seen == [], "researched a company nobody had confirmed"
        assert "confirmed identity" in body["blocked"]
        assert "Resolve them first" in body["blocked"]


class TestSpendingIsBounded:
    async def test_the_limit_caps_how_many_are_attempted(self, api):
        seen = stub_runs(api)
        body = (await api.post(url(api), params={"limit": 1})).json()
        assert body["attempted"] == 1
        assert len(seen) == 1

    async def test_the_default_limit_is_small(self, api):
        """A forgotten cap on a large list is discovered by the bill."""
        from app.api.lists import run_research_for_list

        default = run_research_for_list.__defaults__
        # `limit` is a Query object; its default is what a caller omitting it gets.
        import inspect

        param = inspect.signature(run_research_for_list).parameters["limit"]
        assert param.default.default <= 10

    async def test_a_blocked_model_reports_rather_than_erroring(self, api):
        from app.services import llm

        async def refuse(*a, **k):
            raise RuntimeError("no model provider is configured")

        api.monkeypatch.setattr(llm, "assert_may_call", refuse)
        seen = stub_runs(api)

        response = await api.post(url(api), params={"limit": 10})
        assert response.status_code == 200, "a missing model became an error page"
        body = response.json()
        assert body["ran"] is False
        assert "no model provider" in body["blocked"]
        assert seen == []


class TestOneFailureCostsOneAccount:
    async def test_a_failing_account_does_not_stop_the_batch(self, api):
        seen = stub_runs(api, explode={"Confirmed One"})
        body = (await api.post(url(api), params={"limit": 10})).json()

        assert body["attempted"] == 2
        assert body["failed"] == 1
        assert body["researched"] == 1
        assert len(seen) == 2, "the batch stopped at the first failure"

    async def test_the_failure_is_named_on_the_account(self, api):
        stub_runs(api, explode={"Confirmed One"})
        body = (await api.post(url(api), params={"limit": 10})).json()
        failed = [a for a in body["accounts"] if a["outcome"] == "failed"]
        assert failed[0]["name"] == "Confirmed One"
        assert "RuntimeError" in failed[0]["detail"]


class TestWhatTheReportCarries:
    async def test_evidence_is_totalled_and_broken_down(self, api):
        stub_runs(api, per_account={"funding": 3, "hiring": 1})
        body = (await api.post(url(api), params={"limit": 10})).json()

        assert body["evidence_stored"] == 8  # two accounts, four rows each
        first = body["accounts"][0]
        assert first["evidence_by_family"] == {"funding": 3, "hiring": 1}

    async def test_a_family_that_found_nothing_is_still_reported(self, api):
        """Present with 0 means "looked, found nothing" — a finding.

        Omitting it would be indistinguishable from never having run it, which
        is the distinction the whole coverage model exists to preserve.
        """
        stub_runs(api, per_account={"funding": 0, "hiring": 2})
        body = (await api.post(url(api), params={"limit": 10})).json()
        assert body["accounts"][0]["evidence_by_family"]["funding"] == 0

    async def test_a_missing_list_is_404(self, api):
        r = await api.post(f"/api/lists/{uuid.uuid4()}/run-research")
        assert r.status_code == 404


def _plan(api, *families: str, contact: tuple[str, ...] = (), targets: tuple[str, ...] = ("cto",)):
    """Pretend the list's ICPs plan these families, without seeding types."""
    from app.services import research
    from app.services.research import ListPlan, PlannedFamily, ResearchPlan

    def fams(keys, scope):
        return ResearchPlan(families=[PlannedFamily(f, (f,), (scope,), False) for f in keys])

    plan = ListPlan(
        company=fams(families, "company"), contact=fams(contact, "contact"), targets=targets
    )

    # `**_` absorbs `tier`, which the route now passes. The stub stands in for
    # the planner, so the tier it would have applied is asserted where tiers
    # are the subject — not by every test that needs a plan to exist.
    async def fake_plan(session, list_id, **_):
        return plan

    api.monkeypatch.setattr(research, "plan_for_list", fake_plan)


def _fresh(api, by_index: dict[int, tuple[str, ...]]):
    """Mark families as answered inside the window, per seeded account."""
    from datetime import UTC, datetime

    from app.services import research

    asked: list = []

    async def fake_fresh(session, account_id, *, days):
        asked.append(days)
        for i, families in by_index.items():
            if account_id == api.ids["accounts"][i]:
                return {f: datetime.now(UTC) for f in families}
        return {}

    api.monkeypatch.setattr(research, "fresh_families", fake_fresh)
    return asked


class TestTheReuseWindow:
    """A second list working the same company used to pay for everything
    again. Inside the window, what was already answered is reused."""

    async def test_a_fully_fresh_account_is_reused_not_run(self, api):
        _plan(api, "funding")
        _fresh(api, {0: ("funding",)})
        seen = stub_runs(api)
        body = (await api.post(url(api), params={"limit": 10})).json()

        assert seen == ["Confirmed Two"], "paid again for an answer inside the window"
        assert body["reused"] == 1
        assert body["attempted"] == 1
        assert body["window_days"] == 30
        reused = next(a for a in body["accounts"] if a["outcome"] == "reused")
        assert reused["name"] == "Confirmed One"
        assert "30-day window" in reused["detail"]

    async def test_a_partly_fresh_account_runs_only_what_is_stale(self, api):
        _plan(api, "funding", "hiring")
        _fresh(api, {0: ("funding",)})
        skips: dict = {}
        stub_runs(api, skips=skips)
        body = (await api.post(url(api), params={"limit": 10})).json()

        assert body["reused"] == 0
        assert skips == {"Confirmed One": {"funding"}, "Confirmed Two": set()}

    async def test_rerun_anyway_ignores_the_window(self, api):
        _plan(api, "funding")
        asked = _fresh(api, {0: ("funding",)})
        skips: dict = {}
        seen = stub_runs(api, skips=skips)
        body = (await api.post(url(api), params={"limit": 10, "force": "true"})).json()

        assert body["reused"] == 0
        assert sorted(seen) == ["Confirmed One", "Confirmed Two"]
        assert asked == [], "consulted the window on a forced rerun"
        assert skips["Confirmed One"] == set()

    async def test_a_reused_account_does_not_use_up_the_cap(self, api):
        """The cap bounds spending. A reused account spends nothing."""
        _plan(api, "funding")
        _fresh(api, {0: ("funding",)})
        seen = stub_runs(api)
        body = (await api.post(url(api), params={"limit": 1})).json()

        assert seen == ["Confirmed Two"]
        assert (body["reused"], body["attempted"], body["over_limit"]) == (1, 1, 0)

    async def test_accounts_past_the_cap_are_counted_not_dropped(self, api):
        """A capped run used to read as a complete one."""
        stub_runs(api)
        body = (await api.post(url(api), params={"limit": 1})).json()
        assert (body["attempted"], body["over_limit"]) == (1, 1)


class TestTheReportIsHonest:
    """A live run reported "1 researched · 0 evidence rows stored" for an
    account the model had never been able to look at: the Gemini adapter then
    attached no web tools, and every family came back empty in about three
    seconds. A report that counts that as research is the bug."""

    async def test_an_account_whose_every_source_failed_is_not_researched(self, api):
        down = "LlmUnavailableError: provider is down"
        stub_runs(api, failed_families={"funding": down, "hiring": down})
        body = (await api.post(url(api), params={"limit": 10})).json()

        assert body["researched"] == 0
        assert body["failed"] == 2
        detail = body["accounts"][0]["detail"]
        assert "2 sources failed" in detail
        assert detail.count("provider is down") == 1, "one reason, not one per family"

    async def test_some_sources_failing_is_partial_not_researched(self, api):
        """Partial means some conclusions are unknown — not the same as done."""
        stub_runs(
            api,
            per_account={"funding": 2},
            failed_families={"hiring": "RuntimeError: timeout"},
        )
        body = (await api.post(url(api), params={"limit": 10})).json()

        assert body["partial"] == 2
        assert body["researched"] == 0
        assert body["accounts"][0]["outcome"] == "partial"
        assert body["evidence_stored"] == 4

    async def test_evidence_is_stored_under_the_run_that_found_it(self, api):
        runs: list = []
        stub_runs(api, runs=runs)
        await api.post(url(api), params={"limit": 10})

        assert len(runs) == 2
        for run_id, runner in runs:
            assert run_id is not None, "the run was left to invent its own id"
            assert runner == ("runner", run_id), "evidence would carry a different run"
        assert runs[0][0] != runs[1][0]


class _Person:
    def __init__(self, name):
        self.id = uuid.uuid4()
        self.full_name = name


def _people(api, by_index: dict[int, list]):
    """Who each seeded account offers for the contact pass."""
    from app.services import research

    async def fake(session, account_id, *, targets, limit=3):
        for i, people in by_index.items():
            if account_id == api.ids["accounts"][i]:
                return people
        return []

    api.monkeypatch.setattr(research, "contacts_to_research", fake)


def _people_fresh(api, fresh: dict):
    """Per person: families answered inside the window."""
    from datetime import UTC, datetime

    from app.services import research

    async def fake(session, account_id, *, days):
        return {p.id: {f: datetime.now(UTC) for f in fams} for p, fams in fresh.items()}

    api.monkeypatch.setattr(research, "fresh_contact_families", fake)


def _stub_contacts(api, *, passages: int = 2) -> dict:
    """`run_research` that records who it was asked about, per account."""
    from app.services import pipeline

    asked: dict = {}

    async def fake(session, *, account, crm, run_family, run_id=None, triggered_by="system",
                   skip_families=frozenset(), contacts=(), contact_skip=None, **kwargs):
        asked[account.name] = {
            "people": [c.full_name for c in contacts],
            "skip": {c.full_name: set((contact_skip or {}).get(c.id, set())) for c in contacts},
        }
        return pipeline.RunResult(
            run_id=run_id or uuid.uuid4(),
            evidence_by_family={"funding": 1},
            contacts_researched=tuple(c.id for c in contacts),
            contact_evidence={c.id: passages for c in list(contacts)[:1]},
        )

    api.monkeypatch.setattr(pipeline, "run_research", fake)
    api.monkeypatch.setattr(pipeline, "llm_family_runner", lambda session, **k: None)
    api.monkeypatch.setattr(pipeline, "llm_contact_runner", lambda session, **k: None)
    return asked


class TestContactResearch:
    """The people the ICP is for, researched beside their company — and only
    once they can be written to: a verified email, found by enrichment."""

    async def test_the_chosen_people_are_researched_and_counted(self, api):
        _plan(api, "funding", contact=("leadership",))
        _people(api, {0: [_Person("Dana Reyes")]})
        asked = _stub_contacts(api, passages=2)
        body = (await api.post(url(api), params={"limit": 10})).json()

        assert asked["Confirmed One"]["people"] == ["Dana Reyes"]
        assert (body["contacts_researched"], body["contact_evidence"]) == (1, 2)
        one = next(a for a in body["accounts"] if a["name"] == "Confirmed One")
        assert "1 contact researched, 2 passages" in one["detail"]

    async def test_an_account_with_nobody_eligible_is_told_to_enrich_first(self, api):
        """The company part still runs; the people need finding first."""
        _plan(api, "funding", contact=("leadership",))
        _people(api, {})
        _stub_contacts(api)
        body = (await api.post(url(api), params={"limit": 10})).json()

        assert body["no_contacts"] == 2
        assert body["researched"] == 2, "the company was not researched"
        assert all("Enrich contacts first" in a["detail"] for a in body["accounts"])

    async def test_an_icp_with_no_contact_signals_researches_no_people(self, api):
        _plan(api, "funding")
        _people(api, {0: [_Person("Dana Reyes")]})
        asked = _stub_contacts(api)
        body = (await api.post(url(api), params={"limit": 10})).json()

        assert asked["Confirmed One"]["people"] == []
        assert body["no_contacts"] == 0, "asked to enrich for signals nobody wants"

    async def test_a_person_fresh_for_a_family_is_skipped_for_that_family(self, api):
        _plan(api, "funding", contact=("leadership", "content_activity"))
        dana = _Person("Dana Reyes")
        _people(api, {0: [dana]})
        _people_fresh(api, {dana: ("leadership",)})
        asked = _stub_contacts(api)
        await api.post(url(api), params={"limit": 10})

        assert asked["Confirmed One"]["skip"] == {"Dana Reyes": {"leadership"}}

    async def test_company_and_people_all_fresh_is_reused_without_a_run(self, api):
        _plan(api, "funding", contact=("leadership",))
        dana = _Person("Dana Reyes")
        _people(api, {0: [dana]})
        _fresh(api, {0: ("funding",)})
        _people_fresh(api, {dana: ("leadership",)})
        asked = _stub_contacts(api)
        body = (await api.post(url(api), params={"limit": 10})).json()

        assert "Confirmed One" not in asked, "paid again for answers inside the window"
        assert body["reused"] == 1

    async def test_a_stale_person_keeps_a_fresh_company_from_being_reused(self, api):
        _plan(api, "funding", contact=("leadership",))
        _people(api, {0: [_Person("Dana Reyes")]})
        _fresh(api, {0: ("funding",)})
        skips: dict = {}
        asked = _stub_contacts(api)
        body = (await api.post(url(api), params={"limit": 10})).json()

        assert body["reused"] == 0
        assert asked["Confirmed One"]["people"] == ["Dana Reyes"]


class TestSignalsReachTheReport:
    """Research now ends by reading its evidence into typed signals."""

    def _stub(self, api, **fields):
        from app.services import pipeline

        seen: dict = {}

        async def fake(session, *, account, crm, run_family, run_id=None,
                       triggered_by="system", skip_families=frozenset(), **kwargs):
            seen["types"] = tuple(kwargs.get("signal_type_keys", ()))
            seen["extractor"] = kwargs.get("run_extraction")
            return pipeline.RunResult(
                run_id=run_id or uuid.uuid4(), evidence_by_family={"funding": 2}, **fields
            )

        api.monkeypatch.setattr(pipeline, "run_research", fake)
        api.monkeypatch.setattr(pipeline, "llm_family_runner", lambda session, **k: None)
        api.monkeypatch.setattr(pipeline, "llm_signal_extractor", lambda session, **k: "extractor")
        return seen

    async def test_signals_are_counted_and_named_per_account(self, api):
        _plan(api, "funding")
        self._stub(api, signals_stored=3, signals_dropped=1)
        body = (await api.post(url(api), params={"limit": 10})).json()

        assert (body["signals_stored"], body["signals_dropped"]) == (6, 2), "two accounts"
        one = next(a for a in body["accounts"] if a["name"] == "Confirmed One")
        assert "3 signals (1 dropped — citations did not resolve)" in one["detail"]

    async def test_only_the_icps_signal_types_may_be_extracted(self, api):
        """A type whose family was not run cannot be extracted from evidence
        nobody looked for."""
        _plan(api, "funding", contact=("leadership",))
        seen = self._stub(api)
        await api.post(url(api), params={"limit": 10})
        assert seen["types"] == ("funding", "leadership")
        assert seen["extractor"] == "extractor"

    async def test_a_failed_reading_says_so_without_losing_the_research(self, api):
        """`partial`, not `researched`: something did not finish. It is also the
        cheap state to be in — a rerun reuses the families inside the window and
        pays only for the reading."""
        _plan(api, "funding")
        self._stub(api, signals_failed="LlmUnavailableError: no key")
        body = (await api.post(url(api), params={"limit": 10})).json()

        assert (body["partial"], body["researched"]) == (2, 0)
        assert body["evidence_stored"] == 4, "the evidence it paid for was lost"
        assert body["signals_stored"] == 0
        one = next(a for a in body["accounts"] if a["name"] == "Confirmed One")
        assert "signals not extracted — LlmUnavailableError: no key" in one["detail"]


class TestQualificationInTheReport:
    """Research ends by scoring what it found, across the six dimensions."""

    def _stub(self, api, **fields):
        from app.services import pipeline, qualification

        async def fake(session, *, account, crm, run_family, run_id=None,
                       triggered_by="system", skip_families=frozenset(), **kwargs):
            return pipeline.RunResult(
                run_id=run_id or uuid.uuid4(), evidence_by_family={"funding": 2}, **fields
            )

        api.monkeypatch.setattr(pipeline, "run_research", fake)
        api.monkeypatch.setattr(pipeline, "llm_family_runner", lambda session, **k: None)
        api.monkeypatch.setattr(pipeline, "llm_signal_extractor", lambda session, **k: None)
        api.monkeypatch.setattr(qualification, "llm_qualifier", lambda session, **k: None)

    async def test_scores_are_counted_by_band_and_named_per_account(self, api):
        _plan(api, "funding")
        self._stub(api, qualified=True, priority_score=61.95, priority_band="medium")
        body = (await api.post(url(api), params={"limit": 10})).json()

        assert body["qualified"] == 2
        assert body["bands"] == {"medium": 2}
        one = next(a for a in body["accounts"] if a["name"] == "Confirmed One")
        assert "priority 62 (medium)" in one["detail"]

    async def test_an_unsupported_dimension_is_named_not_hidden(self, api):
        _plan(api, "funding")
        self._stub(api, qualified=True, priority_score=51.75, priority_band="medium",
                   unsupported_dimensions=("buyer",))
        body = (await api.post(url(api), params={"limit": 10})).json()
        one = next(a for a in body["accounts"] if a["name"] == "Confirmed One")
        assert "1 dimension unsupported (buyer)" in one["detail"]

    async def test_nothing_to_judge_says_so_rather_than_scoring_zero(self, api):
        _plan(api, "funding")
        self._stub(api, qualification_note="no live signals yet")
        body = (await api.post(url(api), params={"limit": 10})).json()

        assert (body["qualified"], body["not_qualified"]) == (0, 2)
        one = next(a for a in body["accounts"] if a["name"] == "Confirmed One")
        assert "not scored — no live signals" in one["detail"]

    async def test_a_failed_assessment_keeps_the_research(self, api):
        _plan(api, "funding")
        self._stub(api, qualification_failed="LlmUnavailableError: no key")
        body = (await api.post(url(api), params={"limit": 10})).json()

        assert body["qualification_failed"] == 2
        assert body["evidence_stored"] == 4, "the evidence it paid for was lost"


class TestTheQualifyRoute:
    """For the book researched before qualification existed, and for a re-read
    after signals changed. No provider credits, no research."""

    def _stub(self, api, outcomes: dict):
        from app.services import qualification

        seen: list[str] = []

        def qualifier(session, **kwargs):
            async def run(account):
                seen.append(account.name)
                result = outcomes.get(account.name)
                if isinstance(result, Exception):
                    raise result
                return result or qualification.QualificationOutcome(
                    reason="no live signals yet"
                )

            return run

        api.monkeypatch.setattr(qualification, "llm_qualifier", qualifier)
        return seen

    def _url(self, api) -> str:
        return f"/api/lists/{api.ids['list']}/qualify"

    async def test_confirmed_accounts_are_scored_and_banded(self, api):
        from app.services.qualification import QualificationOutcome

        seen = self._stub(api, {
            "Confirmed One": QualificationOutcome(
                qualified=True, priority_score=78.0, priority_band="high", context_version=2
            ),
            "Confirmed Two": QualificationOutcome(
                qualified=True, priority_score=41.0, priority_band="low", context_version=1
            ),
        })
        body = (await api.post(self._url(api), params={"limit": 10})).json()

        assert sorted(seen) == ["Confirmed One", "Confirmed Two"]
        assert body["qualified"] == 2
        assert body["bands"] == {"high": 1, "low": 1}
        one = next(a for a in body["accounts"] if a["name"] == "Confirmed One")
        assert one["priority_band"] == "high"
        assert "context v2" in one["detail"]

    async def test_unconfirmed_identities_are_skipped_with_the_reason(self, api):
        seen = self._stub(api, {})
        body = (await api.post(self._url(api), params={"limit": 10})).json()

        assert "Still Checking" not in seen, "judged a company nobody had confirmed"
        skipped = next(a for a in body["accounts"] if a["name"] == "Still Checking")
        assert "identity is needs_review" in skipped["detail"]

    async def test_an_account_with_nothing_to_judge_is_skipped_not_zeroed(self, api):
        self._stub(api, {})
        body = (await api.post(self._url(api), params={"limit": 10})).json()
        skipped = [a for a in body["accounts"] if a["outcome"] == "skipped"]
        assert body["qualified"] == 0
        assert any("no live signals" in a["detail"] for a in skipped)

    async def test_one_failure_costs_one_account(self, api):
        from app.services.qualification import QualificationOutcome

        self._stub(api, {
            "Confirmed One": RuntimeError("provider exploded"),
            "Confirmed Two": QualificationOutcome(
                qualified=True, priority_score=60.0, priority_band="medium"
            ),
        })
        body = (await api.post(self._url(api), params={"limit": 10})).json()

        assert (body["failed"], body["qualified"]) == (1, 1)
        failed = next(a for a in body["accounts"] if a["name"] == "Confirmed One")
        assert "provider exploded" in failed["detail"]

    async def test_the_cap_bounds_what_is_spent(self, api):
        seen = self._stub(api, {})
        await api.post(self._url(api), params={"limit": 1})
        assert len(seen) == 1


class TestPriorityOnTheAccountList:
    async def _qualify(self, api, index: int, score: float, band: str) -> None:
        from app.models.context import Qualification

        async for session in api._transport.app.dependency_overrides[get_session]():
            session.add(Qualification(
                account_id=api.ids["accounts"][index], priority_score=score,
                priority_band=band, reasons={}, scoring_config_version=1,
            ))
            await session.commit()
            break

    async def test_each_account_carries_its_latest_score(self, api):
        await self._qualify(api, 0, 78.0, "high")
        rows = (await api.get(f"/api/lists/{api.ids['list']}/accounts")).json()
        by_name = {r["name"]: r for r in rows}

        assert by_name["Confirmed One"]["priority_band"] == "high"
        assert by_name["Confirmed One"]["priority_score"] == 78.0
        assert by_name["Confirmed Two"]["priority_score"] is None, "unjudged is not zero"

    async def test_best_first_does_not_open_with_the_unjudged(self, api):
        """Postgres sorts NULLs first on DESC; the coalesce is what stops the
        top of "best first" being every account nobody has scored."""
        await self._qualify(api, 0, 78.0, "high")
        await self._qualify(api, 1, 41.0, "low")
        rows = (await api.get(
            f"/api/lists/{api.ids['list']}/accounts",
            params={"sort": "priority_score", "dir": "desc"},
        )).json()
        assert [r["name"] for r in rows][:2] == ["Confirmed One", "Confirmed Two"]
        assert rows[-1]["priority_score"] is None

    async def test_the_newest_qualification_wins(self, api):
        await self._qualify(api, 0, 41.0, "low")
        await self._qualify(api, 0, 78.0, "high")
        rows = (await api.get(f"/api/lists/{api.ids['list']}/accounts")).json()
        matching = [r for r in rows if r["name"] == "Confirmed One"]
        assert len(matching) == 1, "the join duplicated the account"
        assert matching[0]["priority_band"] == "high"


class TestReuseSkipsTheSearchNotTheReading:
    """An account researched before extraction existed holds evidence nobody
    has read. Its families are fresh, so re-running costs no search — but
    reporting it "reused" and skipping it left the Signals tab empty for the
    length of the window, with no way to catch up."""

    async def _evidence(self, api, index: int) -> None:
        from app.models.signal import Evidence
        from app.services.evidence import excerpt_hash, source_hash

        url = f"https://example.com/{uuid.uuid4().hex[:8]}"
        excerpt = "They raised a Series B."
        async for session in api._transport.app.dependency_overrides[get_session]():
            session.add(Evidence(
                account_id=api.ids["accounts"][index], source_type="news", source_url=url,
                excerpt=excerpt, source_hash=source_hash(url, None),
                excerpt_hash=excerpt_hash(url, excerpt), raw_status="unavailable",
            ))
            await session.commit()
            break

    async def test_unread_evidence_is_read_without_researching_again(self, api):
        _plan(api, "funding")
        _fresh(api, {0: ("funding",)})
        await self._evidence(api, 0)
        skips: dict = {}
        seen = stub_runs(api, skips=skips)
        body = (await api.post(url(api), params={"limit": 10})).json()

        assert "Confirmed One" in seen, "left holding evidence nobody had read"
        assert body["reused"] == 0
        assert skips["Confirmed One"] == {"funding"}, "paid for a search inside the window"

    async def test_nothing_unread_is_still_reused(self, api):
        """Evidence already turned into signals is not re-read: the reuse
        window is doing its job."""
        from app.models.signal import Signal
        from datetime import date

        _plan(api, "funding")
        _fresh(api, {0: ("funding",)})
        await self._evidence(api, 0)
        async for session in api._transport.app.dependency_overrides[get_session]():
            from sqlalchemy import select

            from app.models.config import SignalType
            from app.models.signal import Evidence, signal_evidence

            session.add(SignalType(key="funding", label="Funding", scope="company",
                                   default_ttl_days=300))
            await session.flush()
            evidence = (await session.execute(select(Evidence))).scalars().first()
            signal = Signal(
                account_id=api.ids["accounts"][0], signal_type="funding", scope="company",
                summary="Series B", strength="high", confidence=0.9,
                observed_at=date(2026, 8, 1),
            )
            session.add(signal)
            await session.flush()
            await session.execute(signal_evidence.insert().values(
                signal_id=signal.id, evidence_id=evidence.id, role="primary"
            ))
            await session.commit()
            break

        seen = stub_runs(api)
        body = (await api.post(url(api), params={"limit": 10})).json()
        assert "Confirmed One" not in seen
        assert body["reused"] == 1

    async def test_an_account_with_no_evidence_at_all_is_still_reused(self, api):
        _plan(api, "funding")
        _fresh(api, {0: ("funding",)})
        seen = stub_runs(api)
        body = (await api.post(url(api), params={"limit": 10})).json()
        assert "Confirmed One" not in seen
        assert body["reused"] == 1


def stub_capture(api):
    """Replace `run_research`, keeping every keyword each account was run with."""
    from app.services import pipeline

    calls: list[dict] = []

    async def fake(session, *, account, crm, run_family, run_id=None,
                   triggered_by="system", skip_families=frozenset(), **kwargs):
        calls.append({"account": account.name, "skip": set(skip_families), **kwargs})
        return pipeline.RunResult(
            run_id=run_id or uuid.uuid4(), evidence_by_family={"funding": 1}
        )

    api.monkeypatch.setattr(pipeline, "run_research", fake)
    api.monkeypatch.setattr(
        pipeline, "llm_family_runner", lambda session, **k: ("runner", k.get("run_id"))
    )
    api.monkeypatch.setattr(
        pipeline, "llm_contact_runner", lambda session, **k: ("contact", k.get("run_id"))
    )
    return calls


class TestResearchingNamedPeople:
    """Picking somebody by name reads *them*, and their company only if it needs it."""

    async def people(self, api, *, suppressed=False):
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.models.account import Contact

        engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as s:
            picked = Contact(
                account_id=api.ids["accounts"][0], full_name="Enrico Bergamo", title="CTO",
                email="e@dd.example", email_status="verified",
                do_not_contact=suppressed,
                do_not_contact_reason="asked us to stop" if suppressed else None,
            )
            colleague = Contact(
                account_id=api.ids["accounts"][0], full_name="Ada Lovelace", title="VP Eng",
                email="a@dd.example", email_status="verified",
            )
            s.add_all([picked, colleague])
            await s.commit()
        await engine.dispose()
        return picked, colleague

    async def test_only_the_person_picked_is_read_and_their_company_is_covered(self, api):
        picked, colleague = await self.people(api)
        _plan(api, "funding", contact=("person_news",))
        calls = stub_capture(api)

        body = (await api.post(url(api), json={"contact_ids": [str(picked.id)]})).json()
        assert body["ran"] and not body["blocked"]
        assert [c["account"] for c in calls] == ["Confirmed One"], "only their company"
        [call] = calls
        assert [p.id for p in call["contacts"]] == [picked.id], "nobody else at the company"
        assert set(call["company_plan"].keys) == {"funding"}, "the company is still planned"
        assert call["contact_skip"] == {picked.id: set()}, "their own reuse window is ignored"
        assert colleague.id not in {p.id for p in call["contacts"]}

    async def test_a_company_researched_recently_is_skipped_and_the_person_is_still_read(self, api):
        picked, _ = await self.people(api)
        _plan(api, "funding", contact=("person_news",))
        _fresh(api, {0: ("funding",)})
        calls = stub_capture(api)

        body = (await api.post(url(api), json={"contact_ids": [str(picked.id)]})).json()
        assert body["ran"] and body["reused"] == 0, "there is person work, so it is not all reused"
        [call] = calls
        assert call["skip"] == {"funding"}, "nothing is bought about the company twice"
        assert [p.id for p in call["contacts"]] == [picked.id]

    async def test_somebody_marked_do_not_contact_is_not_researched(self, api):
        picked, _ = await self.people(api, suppressed=True)
        _plan(api, "funding", contact=("person_news",))
        calls = stub_capture(api)

        body = (await api.post(url(api), json={"contact_ids": [str(picked.id)]})).json()
        assert calls == []
        assert "do-not-contact" in body["blocked"]


class TestAQuotaRefusalStopsTheRun:
    """Forty more accounts must not each buy the same refusal.

    Measured on a fifty-account list: once the quota was gone the last five
    accounts lost all five sources each, and the final minute held twenty-five
    calls, every one refused. A 429 fails in milliseconds, so a limited run
    reaches the next account *sooner* than a healthy one — the call rate rises
    exactly when it should fall, and the list finishes full of accounts that
    look researched and are empty.
    """

    def _limited(self, api, *, quota, retry_after=None, after=1):
        """Rate-limit the run from the `after`-th account onward."""
        from app.services import pipeline

        seen: list[str] = []

        async def fake(session, *, account, crm, run_family, run_id=None, **kwargs):
            seen.append(account.name)
            limited = len(seen) >= after
            return pipeline.RunResult(
                run_id=run_id or uuid.uuid4(),
                evidence_by_family={} if limited else {"funding": 2},
                failed_families=(
                    {"funding": "LlmUnavailableError: HTTP 429"} if limited else {}
                ),
                rate_limited=limited,
                rate_limit_quota=quota if limited else None,
                rate_limit_retry_after=retry_after if limited else None,
            )

        api.monkeypatch.setattr(pipeline, "run_research", fake)
        api.monkeypatch.setattr(
            pipeline, "llm_family_runner", lambda session, **k: ("runner", k.get("run_id"))
        )
        return seen

    async def test_a_daily_quota_ends_the_run_at_that_account(self, api):
        seen = self._limited(api, quota="GenerateRequestsPerDayPerProjectPerModel")
        r = await api.post(f"{url(api)}?limit=50")
        assert r.status_code == 200
        body = r.json()
        assert len(seen) == 1, f"kept going after a daily quota: {seen}"
        assert body["stopped_early"]
        assert "GenerateRequestsPerDayPerProjectPerModel" in body["stopped_early"]

    async def test_a_long_delay_ends_the_run_rather_than_waiting(self, api):
        """A wait a rep cannot distinguish from a hang is not a wait."""
        from app.api.lists import RATE_LIMIT_MAX_WAIT

        seen = self._limited(
            api, quota="GenerateRequestsPerMinutePerProject",
            retry_after=RATE_LIMIT_MAX_WAIT + 1,
        )
        body = (await api.post(f"{url(api)}?limit=50")).json()
        assert len(seen) == 1
        assert body["stopped_early"]

    async def test_a_short_per_minute_ceiling_is_waited_out(self, api, monkeypatch):
        """The one case worth continuing through, and it must not really sleep."""
        import app.api.lists as lists_api

        waited: list[float] = []

        async def no_sleep(seconds):
            waited.append(seconds)

        monkeypatch.setattr(lists_api.asyncio, "sleep", no_sleep)
        seen = self._limited(
            api, quota="GenerateRequestsPerMinutePerProject", retry_after=2.0
        )
        body = (await api.post(f"{url(api)}?limit=50")).json()
        assert len(seen) > 1, "a short ceiling should not end the run"
        assert waited and all(w == 2.0 for w in waited)
        assert body["stopped_early"] is None
        assert body["rate_limit_waited"] == pytest.approx(2.0 * len(waited))

    async def test_what_was_not_reached_is_not_called_researched(self, api):
        """The accounts left are re-runnable, and the report says so."""
        seen = self._limited(api, quota="GenerateRequestsPerDayPerProjectPerModel")
        body = (await api.post(f"{url(api)}?limit=50")).json()
        assert body["attempted"] == len(seen)
        assert body["researched"] == 0
        assert "nothing was spent" in body["stopped_early"]
