"""Helpers for fire-and-forget asyncio background work.

The asyncio docs warn that `asyncio.create_task(coro)` only retains a weak
reference to the returned Task — if no caller holds a strong reference, the
task can be garbage-collected mid-execution and silently disappear. We use
this from in-process fallbacks of the enrich/crawl endpoints (when no arq
worker is reachable), so a GC'd task means prospects stay stuck at "pending"
forever.

`fire_and_forget(coro)` keeps a process-wide strong reference until the task
completes, then releases it.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Coroutine

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task] = set()


def fire_and_forget(coro: Coroutine, *, name: str | None = None) -> asyncio.Task:
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)

    def _done(t: asyncio.Task) -> None:
        _background_tasks.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.exception("Background task %s failed", t.get_name(), exc_info=exc)

    task.add_done_callback(_done)
    return task
