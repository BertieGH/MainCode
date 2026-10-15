from __future__ import annotations

import time
import uuid
from contextvars import ContextVar
from typing import Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .logging import get_logger

_request_id_var: ContextVar[str] = ContextVar("request_id", default="")
_conversation_id_var: ContextVar[str] = ContextVar("conversation_id", default="")


def current_request_id() -> str:
    return _request_id_var.get()


def current_conversation_id() -> str:
    return _conversation_id_var.get()


def set_conversation_id(conversation_id: str) -> None:
    _conversation_id_var.set(conversation_id)


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        token = _request_id_var.set(request_id)
        structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)
        start = time.perf_counter()
        log = get_logger("http")
        try:
            response: Response = await call_next(request)
        except Exception:
            log.exception("request.error")
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            structlog.contextvars.unbind_contextvars("request_id", "path")
            _request_id_var.reset(token)
        log.info("request.complete", status=response.status_code, duration_ms=round(duration_ms, 2))
        response.headers["x-request-id"] = request_id
        return response


def audit_event(event: str, **fields: Any) -> None:
    """
    Emit an immutable audit event. Every agent decision, guard block, and adjudicator
    handoff calls this. Stored to Cloud Logging via structlog and (separately) persisted
    to the audit table by the agent runtime.
    """
    log = get_logger("audit")
    log.info(
        event,
        request_id=current_request_id(),
        conversation_id=current_conversation_id(),
        **fields,
    )
