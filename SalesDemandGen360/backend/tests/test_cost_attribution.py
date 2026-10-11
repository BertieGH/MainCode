"""Who a model call was for, and the rankings that depend on it.

The ledger counted every call and said nothing about whose it was, so the
question a cost screen exists to answer — *which research cost ten times its
neighbours, and why* — had no column behind it.

Two things are easy to get wrong here and both are asserted below.

**The contact pass makes one call for every person in a family**, so most
rows about people name nobody. If the company/contact split were read off
`contact_id IS NULL` the whole contact half would file under the company. It
is read off `scope`.

**Attribution travels through a context variable**, because `_record_call`
writes in a transaction of its own and threading an owner into it would mean
a parameter on every stage, every helper between, and every test. A context
variable is also the only mechanism that survives `asyncio.gather` correctly,
and the gathered family runner is exactly what it has to survive.

And that same separate transaction is why these columns are **ids, not
foreign keys**. The first version of this change used real references and
silently destroyed the ledger: `run_research` flushes its run row on the
sequential path, a separate transaction cannot see a flush, so every
attributed row raised `ForeignKeyViolation` into the guard that keeps
bookkeeping from breaking the work it measures — and was swallowed. Measured
at zero rows before the fix. The class below is that bug.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.account import Account, Run
from app.models.config import LlmCall
from app.models.cost import ModelPrice
from app.services import llm, stages

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"),
]


def _async(value):
    async def run(*_a, **_k):
        return value

    return run


def config() -> SimpleNamespace:
    return SimpleNamespace(
        scenario="company_research", provider="gemini", model="gemini-3.5-flash-lite",
        effort="high", max_tokens=48000, thinking_mode="adaptive",
    )


@pytest.fixture
async def engine():
    eng = create_async_engine(os.environ["TEST_DATABASE_URL"])
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
        await s.rollback()


@pytest.fixture
def answers(monkeypatch):
    """A stage that costs nothing and records like one that did."""

    async def fake(**_kw):
        return SimpleNamespace(
            parsed=None, input_tokens=1000, output_tokens=100,
            cache_read_tokens=0, cache_write_tokens=0, grounded=True,
            model="gemini-3.5-flash-lite",
        )

    monkeypatch.setattr(llm, "call_structured", fake)
    monkeypatch.setattr(llm, "stage_config", lambda *_a, **_k: _async(config())())
    monkeypatch.setattr(llm, "assert_may_call", lambda *_a, **_k: _async(None)())
    monkeypatch.setattr(llm, "stored_api_key", lambda *_a, **_k: _async("k")())


async def _call(session, scenario="company_research"):
    await stages._run(
        session, scenario, prefix=None, user_content="{}", output_model=dict,
    )


async def _latest(engine, n: int = 1) -> list[LlmCall]:
    """Read from a fresh session: the ledger commits in its own transaction."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as fresh:
        return list(
            (
                await fresh.execute(
                    select(LlmCall).order_by(LlmCall.created_at.desc()).limit(n)
                )
            ).scalars().all()
        )


class TestWhatACallCarries:
    async def test_an_unattributed_call_still_records(self, session, engine, answers):
        """A trial from a settings screen belongs to no run and is spend."""
        await _call(session)
        row = (await _latest(engine))[0]
        assert row.run_id is None and row.scope is None
        assert row.input_tokens == 1000, "an unowned call is still counted"

    async def test_a_call_inside_a_block_carries_the_block(self, session, engine, answers):
        run_id, account_id = uuid.uuid4(), uuid.uuid4()
        with stages.attributed(run_id=run_id, account_id=account_id, scope="company"):
            await _call(session)
        row = (await _latest(engine))[0]
        assert (row.run_id, row.account_id, row.scope) == (run_id, account_id, "company")

    async def test_a_nested_block_adds_without_restating(self, session, engine, answers):
        """A contact pass inside a run should not have to repeat the run."""
        run_id = uuid.uuid4()
        with stages.attributed(run_id=run_id, scope="company"):
            with stages.attributed(scope="contact"):
                await _call(session)
        row = (await _latest(engine))[0]
        assert row.run_id == run_id, "the inner block lost the run it is inside"
        assert row.scope == "contact"

    async def test_the_block_ends_where_it_ends(self, session, engine, answers):
        """Without the reset, every later call in the process would be filed
        under whichever run happened to go first."""
        with stages.attributed(run_id=uuid.uuid4(), scope="company"):
            pass
        await _call(session)
        assert (await _latest(engine))[0].run_id is None

    async def test_a_failed_call_is_attributed_too(self, session, engine, monkeypatch):
        """The dearest runs are often the ones that burned an allowance and
        returned nothing — an unattributed failure drops out of the ranking
        it belongs at the top of."""
        marker = f"refused {os.urandom(4).hex()}"

        async def blows_up(**_kw):
            raise llm.LlmUnavailableError(marker)

        monkeypatch.setattr(llm, "call_structured", blows_up)
        monkeypatch.setattr(llm, "stage_config", lambda *_a, **_k: _async(config())())
        monkeypatch.setattr(llm, "assert_may_call", lambda *_a, **_k: _async(None)())
        monkeypatch.setattr(llm, "stored_api_key", lambda *_a, **_k: _async("k")())

        run_id = uuid.uuid4()
        with stages.attributed(run_id=run_id, scope="company"):
            with pytest.raises(llm.LlmUnavailableError):
                await _call(session)
        await session.rollback()

        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as fresh:
            found = (
                await fresh.execute(select(LlmCall).where(LlmCall.error.contains(marker)))
            ).scalars().all()
        assert len(found) == 1 and found[0].run_id == run_id


class TestConcurrency:
    async def test_gathered_families_do_not_write_over_each_other(
        self, session, engine, answers
    ):
        """The reason this is a context variable and not a module global.

        `run_research(concurrent_families=True)` gathers the family runner,
        and a global would leave five families writing one attribution —
        whichever set it last. `asyncio` copies the context into each task,
        so each family carries its own.
        """
        ids = [uuid.uuid4() for _ in range(5)]
        maker = async_sessionmaker(engine, expire_on_commit=False)

        async def family(run_id):
            # A session each, as the concurrent runner gives a family.
            async with maker() as own:
                with stages.attributed(run_id=run_id, scope="company"):
                    # Yields to the loop mid-block, which is where a shared
                    # value would be clobbered by a sibling.
                    await asyncio.sleep(0)
                    await _call(own)

        await asyncio.gather(*(family(i) for i in ids))

        async with maker() as fresh:
            written = {
                row.run_id
                for row in (
                    await fresh.execute(
                        select(LlmCall).where(LlmCall.run_id.in_(ids))
                    )
                ).scalars().all()
            }
        assert written == set(ids), "families wrote over each other's attribution"

    async def test_a_child_cannot_change_its_parent(self, session, engine, answers):
        """A contact pass gathered inside a run must not leave `contact`
        set on the company work that follows it."""
        run_id = uuid.uuid4()
        with stages.attributed(run_id=run_id, scope="company"):
            async def child():
                with stages.attributed(scope="contact"):
                    await _call(session)

            await asyncio.gather(child())
            await _call(session)

        rows = await _latest(engine, 2)
        assert {r.scope for r in rows} == {"company", "contact"}


class TestTheLedgerSurvivesTheWriterBeingOutside:
    async def test_a_call_records_against_a_run_that_is_only_flushed(
        self, session, engine, answers
    ):
        """The regression that cost this change a rewrite.

        `_record_call` commits in its own transaction so a failed call's row
        outlives the rollback that follows it. `run_research` only *flushes*
        its run row unless families run concurrently. A foreign key between
        the two means the ledger writer cannot see the row it points at:
        every attributed call raised, the guard swallowed it, and spend
        recording stopped entirely — with nothing on any screen to say so.

        Fails with a `ForeignKey` on `llm_call.run_id`. Verified by putting
        one back.
        """
        async with async_sessionmaker(engine, expire_on_commit=False)() as s:
            account = Account(
                name=f"Flushed {uuid.uuid4().hex[:6]}",
                domain=f"{uuid.uuid4().hex[:8]}.example",
            )
            s.add(account)
            await s.flush()
            run = Run(account_id=account.id, stage="resolution", status="running")
            s.add(run)
            await s.flush()  # exactly what run_research's sequential path does
            with stages.attributed(
                run_id=run.id, account_id=account.id, scope="company"
            ):
                await _call(s)
            await s.commit()
            run_id = run.id

        async with async_sessionmaker(engine, expire_on_commit=False)() as fresh:
            found = (
                await fresh.execute(select(LlmCall).where(LlmCall.run_id == run_id))
            ).scalars().all()
        assert len(found) == 1, "the ledger lost a call to a row it could not see"


@pytest.fixture
async def api(engine):
    from app.api.deps import get_session
    from app.main import create_app

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


async def _priced_run(maker, *, name: str, company: int, contact: int, out: int = 100):
    """One account, one run, and the calls that belong to it."""
    async with maker() as s:
        account = Account(name=name, domain=f"{uuid.uuid4().hex[:8]}.example")
        s.add(account)
        await s.flush()
        run = Run(account_id=account.id, stage="signals", status="succeeded")
        s.add(run)
        await s.flush()
        for scope, n in (("company", company), ("contact", contact)):
            for _ in range(n):
                s.add(LlmCall(
                    scenario="company_research", provider="gemini",
                    model="gemini-3.5-flash-lite", effort="high",
                    input_tokens=1000, output_tokens=out, duration_ms=900,
                    grounded=True, run_id=run.id, account_id=account.id, scope=scope,
                ))
        await s.commit()
        return run.id, account.id


class TestTheRankings:
    async def test_it_ranks_research_by_what_it_cost(self, api):
        async with api.maker() as s:
            s.add(ModelPrice(
                version=9_000 + int(uuid.uuid4().int % 1000), is_active=False,
                prices={"gemini-3.5-flash-lite": {
                    "input_per_m": 0.1, "output_per_m": 0.4, "grounded_per_call": 0.005,
                }},
                note="test",
            ))
            await s.commit()

        dear, _ = await _priced_run(api.maker, name=f"Dear {uuid.uuid4().hex[:6]}",
                                    company=40, contact=10)
        cheap, _ = await _priced_run(api.maker, name=f"Cheap {uuid.uuid4().hex[:6]}",
                                     company=1, contact=0)

        body = (await api.get("/api/monitoring?days=1")).json()
        # Both lists together, because the split between them depends on
        # how many runs are in the window: under five, everything is in
        # the dearest list and the cheapest one is empty — which is
        # honest, you are looking at all of them, in order.
        ranked = [r["run_id"] for r in body["dearest_runs"]] + [
            r["run_id"] for r in reversed(body["cheapest_runs"])
        ]
        assert str(dear) in ranked and str(cheap) in ranked
        assert ranked.index(str(dear)) < ranked.index(str(cheap)), (
            "forty calls sorted below one"
        )

    async def test_a_run_never_appears_in_both_lists(self, api):
        """With four runs in the window, the dearest showing again at the
        bottom reads as two findings rather than one."""
        await _priced_run(api.maker, name=f"Only {uuid.uuid4().hex[:6]}",
                          company=3, contact=1)
        body = (await api.get("/api/monitoring?days=1")).json()
        top = {r["run_id"] for r in body["dearest_runs"]}
        bottom = {r["run_id"] for r in body["cheapest_runs"]}
        assert not (top & bottom)

    async def test_it_splits_a_run_between_the_company_and_its_people(self, api):
        run_id, _ = await _priced_run(api.maker, name=f"Split {uuid.uuid4().hex[:6]}",
                                      company=7, contact=3)
        body = (await api.get("/api/monitoring?days=1")).json()
        row = next(
            r for r in body["dearest_runs"] + body["cheapest_runs"]
            if r["run_id"] == str(run_id)
        )
        # Read off `scope`, not off whether a row names a contact: one
        # contact search covers every person in a family, so three of these
        # rows name nobody and would otherwise count as company work.
        assert (row["company_calls"], row["contact_calls"]) == (7, 3)
        assert row["calls"] == 10

    async def test_it_says_how_much_of_the_bill_it_is_not_describing(self, api):
        """Every ranking excludes unattributed calls. History is all
        unattributed, so a screen that did not say so would present a
        ranking of a fraction as a ranking of the bill."""
        async with api.maker() as s:
            s.add(LlmCall(
                scenario="sales_prep", provider="gemini", model="gemini-3.1-pro-preview",
                effort="high", input_tokens=1600, output_tokens=900, duration_ms=16000,
            ))
            await s.commit()
        body = (await api.get("/api/monitoring?days=1")).json()
        assert body["unattributed_calls"] >= 1

    async def test_an_unpriced_model_makes_a_run_unpriced_not_cheap(self, api):
        """A run whose model has no price must not sort as free. Cheap is a
        finding here — it means the run found nothing — so a missing price
        reporting as cheap would manufacture that finding."""
        async with api.maker() as s:
            account = Account(name=f"Unpriced {uuid.uuid4().hex[:6]}",
                              domain=f"{uuid.uuid4().hex[:8]}.example")
            s.add(account)
            await s.flush()
            run = Run(account_id=account.id, stage="signals", status="succeeded")
            s.add(run)
            await s.flush()
            s.add(LlmCall(
                scenario="company_research", provider="gemini",
                model="model-nobody-priced", effort="high",
                input_tokens=9_000_000, output_tokens=500_000, duration_ms=900,
                run_id=run.id, account_id=account.id, scope="company",
            ))
            await s.commit()
            run_id = run.id

        body = (await api.get("/api/monitoring?days=1")).json()
        row = next(
            (r for r in body["dearest_runs"] + body["cheapest_runs"]
             if r["run_id"] == str(run_id)),
            None,
        )
        assert row is not None, "an unpriced run must still be visible"
        assert row["cost"] is None, "unpriced is not free"
