"""A stage that cannot run says so, rather than answering 500.

Written after a strategy build failed with "Gemini hit maxOutputTokens before
finishing — raise max_tokens for this stage" and the screen showed "Internal
Server Error". The exception named the fix in its first sentence; the rep
could not see it. Every LLM-backed route had the same gap, because each one
caught its own domain errors and nothing caught this.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.services.llm import LlmUnavailableError, NoAdapterError


@pytest.fixture
def app() -> FastAPI:
    from app.main import create_app

    application = create_app()

    @application.get("/api/_test/out-of-budget")
    async def _out_of_budget():
        raise LlmUnavailableError(
            "Gemini hit maxOutputTokens before finishing — raise max_tokens for this stage"
        )

    @application.get("/api/_test/no-adapter")
    async def _no_adapter():
        raise NoAdapterError("acme", "strategy_synthesis")

    return application


async def client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class TestTheReasonReachesTheScreen:
    async def test_an_unrunnable_stage_answers_503_with_what_to_change(self, app):
        async with await client(app) as c:
            r = await c.get("/api/_test/out-of-budget")
        assert r.status_code == 503
        body = r.json()
        assert body["error"] == "llm_unavailable"
        assert "max_tokens" in body["message"], "the fix is named, not just the failure"

    async def test_a_provider_we_cannot_call_answers_409(self, app):
        async with await client(app) as c:
            r = await c.get("/api/_test/no-adapter")
        assert r.status_code == 409
        assert r.json()["error"] == "no_adapter"

    async def test_neither_is_a_500(self, app):
        """A 500 tells a rep nothing and sends them to a developer."""
        async with await client(app) as c:
            for path in ("/api/_test/out-of-budget", "/api/_test/no-adapter"):
                assert (await c.get(path)).status_code != 500
