"""Health endpoints.

Two of them, deliberately, because they answer different questions:

- ``/health``  — is the process up? Used by a load balancer. Must never touch
  the database, or a database blip takes the whole service out of rotation.
- ``/health/ready`` — can it actually serve? Checks the database round-trip.
  Used by a deploy gate and by the developer wondering why nothing works.
"""

from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_session

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: Literal["ok"]
    app: str
    environment: str


class Readiness(BaseModel):
    status: Literal["ready", "degraded"]
    database: Literal["up", "down"]
    latency_ms: float | None = None
    detail: str | None = None


@router.get("/health", response_model=Health)
async def health(settings: Settings = Depends(get_settings)) -> Health:
    return Health(status="ok", app=settings.app_name, environment=settings.environment)


@router.get("/health/ready", response_model=Readiness)
async def readiness(
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> Readiness:
    started = time.perf_counter()
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 — any failure means not ready
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        # The exception type is more useful than its message, which can carry
        # the connection string and therefore the password.
        return Readiness(
            status="degraded", database="down", detail=type(exc).__name__
        )
    elapsed = (time.perf_counter() - started) * 1000
    return Readiness(status="ready", database="up", latency_ms=round(elapsed, 2))
