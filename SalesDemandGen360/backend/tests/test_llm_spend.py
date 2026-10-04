"""What every model call cost, in tokens.

Written because "how much it costed?" had no answer. The `run` table carried
token columns that nothing ever filled, and the two dearest stages — strategy
and drafting — made no run row at all. A stage could be configured into
thinking for thirty thousand tokens a call and nothing would show it.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.config import LlmCall
from app.services import llm, stages

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"),
]


@pytest.fixture
async def session():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
        await s.rollback()
    await engine.dispose()


def config() -> SimpleNamespace:
    return SimpleNamespace(
        scenario="strategy_synthesis", provider="gemini", model="gemini-3.8-flash",
        effort="high", max_tokens=48000, thinking_mode="adaptive",
    )


async def rows(session) -> list[LlmCall]:
    return list((await session.execute(select(LlmCall))).scalars().all())


class TestTheLedger:
    async def test_a_call_writes_what_it_used(self, session, monkeypatch):
        async def fake(**kw):
            return SimpleNamespace(
                parsed=None, input_tokens=2219, output_tokens=411,
                cache_read_tokens=100, cache_write_tokens=0, model="gemini-3.8-flash",
            )

        monkeypatch.setattr(llm, "call_structured", fake)
        monkeypatch.setattr(llm, "stage_config", lambda *_a, **_k: _async(config()))
        monkeypatch.setattr(llm, "assert_may_call", lambda *_a, **_k: _async(None))
        monkeypatch.setattr(llm, "stored_api_key", lambda *_a, **_k: _async("k"))

        before = len(await rows(session))
        await stages._run(
            session, "strategy_synthesis", prefix=None, user_content="{}", output_model=dict,
        )
        after = await rows(session)
        assert len(after) == before + 1
        call = after[-1]
        assert (call.input_tokens, call.output_tokens) == (2219, 411)
        assert call.scenario == "strategy_synthesis" and call.ok

    async def test_a_failed_call_survives_the_rollback_that_follows_it(
        self, session, monkeypatch
    ):
        """The bug this test was written badly enough to miss the first time.

        A failed call raises, the route never commits, and a row flushed onto
        the caller's session dies with the transaction — so the calls worth
        counting most were the ones not counted. The original test asserted
        inside the same session, before any rollback, and passed.

        The ledger now writes in its own transaction. This rolls the caller's
        session back, as a failing route does, and then looks in a *new* one.
        """
        async def blows_up(**kw):
            raise llm.LlmUnavailableError("Gemini hit maxOutputTokens before finishing")

        monkeypatch.setattr(llm, "call_structured", blows_up)
        monkeypatch.setattr(llm, "stage_config", lambda *_a, **_k: _async(config()))
        monkeypatch.setattr(llm, "assert_may_call", lambda *_a, **_k: _async(None))
        monkeypatch.setattr(llm, "stored_api_key", lambda *_a, **_k: _async("k"))

        marker = f"maxOutputTokens {os.urandom(4).hex()}"

        async def blows_up_marked(**kw):
            raise llm.LlmUnavailableError(marker)

        monkeypatch.setattr(llm, "call_structured", blows_up_marked)
        with pytest.raises(llm.LlmUnavailableError):
            await stages._run(
                session, "strategy_synthesis", prefix=None, user_content="{}", output_model=dict,
            )
        await session.rollback()

        engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as fresh:
            found = (
                await fresh.execute(select(LlmCall).where(LlmCall.error.contains(marker)))
            ).scalars().all()
        await engine.dispose()
        assert len(found) == 1, "a failure the ledger forgets is the one worth remembering"
        assert not found[0].ok

    async def test_a_failed_call_is_counted_too(self, session, monkeypatch):
        """The one nobody would otherwise count, and where a runaway budget
        shows up first: it burned the allowance and returned nothing."""
        async def blows_up(**kw):
            raise llm.LlmUnavailableError("Gemini hit maxOutputTokens before finishing")

        monkeypatch.setattr(llm, "call_structured", blows_up)
        monkeypatch.setattr(llm, "stage_config", lambda *_a, **_k: _async(config()))
        monkeypatch.setattr(llm, "assert_may_call", lambda *_a, **_k: _async(None))
        monkeypatch.setattr(llm, "stored_api_key", lambda *_a, **_k: _async("k"))

        with pytest.raises(llm.LlmUnavailableError):
            await stages._run(
                session, "strategy_synthesis", prefix=None, user_content="{}", output_model=dict,
            )
        call = (await rows(session))[-1]
        assert not call.ok and "maxOutputTokens" in call.error

    async def test_bookkeeping_cannot_fail_the_work(self, session):
        """A lost ledger row must never cost a strategy.

        A config with none of the fields the row reads is enough to break the
        write. It must be logged and swallowed — and the logging must survive
        the same breakage, which is what failed the first time this was run.
        """
        await stages._record_call(session, SimpleNamespace(), 0.0, result=None)


def _async(value):
    async def run():
        return value
    return run()


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


class TestTheSpendView:
    async def test_it_groups_by_stage_and_shows_the_worst_call(self, api):
        async with api.maker() as s:
            for out in (400, 800, 30208):
                s.add(LlmCall(
                    scenario="strategy_synthesis", provider="gemini", model="gemini-3.8-flash",
                    effort="high", input_tokens=2000, output_tokens=out, duration_ms=1200,
                ))
            await s.commit()

        body = (await api.get("/api/config/llm/spend?days=1")).json()
        stage = next(r for r in body["by_stage"] if r["scenario"] == "strategy_synthesis")
        assert stage["calls"] >= 3
        assert stage["worst_output"] >= 30208, "the runaway call is what the screen is for"
        assert body["output_tokens"] >= 31408
        assert "not currency" in body["note"]
