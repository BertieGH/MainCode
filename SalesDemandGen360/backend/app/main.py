"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    campaign_drafts,
    campaign_strategy,
    campaigns,
    config,
    contact_finding,
    health,
    intelligence,
    lists,
    monitoring,
    outreach_events,
    pasted,
    prep,
    prompts,
)
from app.config import get_settings
from app.database import engine
from app.services.llm import LlmUnavailableError, NoAdapterError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("starting %s (%s)", settings.app_name, settings.environment)
    yield
    # Dispose explicitly so a reload does not leak pooled connections.
    await engine.dispose()
    logger.info("shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Prospect Engine — marketing intelligence for CGVAK outbound.",
        lifespan=lifespan,
    )

    # The Angular dev server runs on 4200. Locked to explicit origins rather
    # than "*" even in local dev, so the production config is a change of list
    # rather than a change of posture.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:4200", "http://127.0.0.1:4200"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # A stage that cannot run is not a bug in the request, and it has
    # something useful to say: no key, a provider unreachable, or an output
    # budget too small for what was asked. Without these, every one of those
    # reached the screen as "Internal Server Error" — which is how an hour
    # went into diagnosing a `max_tokens` that the exception named in its
    # first sentence.
    @app.exception_handler(LlmUnavailableError)
    async def _llm_unavailable(_request: Request, exc: LlmUnavailableError):
        return JSONResponse(
            status_code=503,
            content={
                "error": "llm_unavailable",
                "message": str(exc),
                "detail": str(exc),
            },
        )

    @app.exception_handler(NoAdapterError)
    async def _no_adapter(_request: Request, exc: NoAdapterError):
        return JSONResponse(
            status_code=409,
            content={"error": "no_adapter", "message": str(exc), "detail": str(exc)},
        )

    app.include_router(health.router, prefix="/api")
    app.include_router(config.router, prefix="/api")
    app.include_router(lists.router, prefix="/api")
    app.include_router(intelligence.router, prefix="/api")
    app.include_router(pasted.router, prefix="/api")
    app.include_router(contact_finding.router, prefix="/api")
    app.include_router(campaigns.router, prefix="/api")
    app.include_router(campaign_strategy.router, prefix="/api")
    app.include_router(outreach_events.router, prefix="/api")
    app.include_router(campaign_drafts.router, prefix="/api")
    app.include_router(monitoring.router, prefix="/api")
    app.include_router(prep.router, prefix="/api")
    app.include_router(prompts.router, prefix="/api")
    return app


app = create_app()
