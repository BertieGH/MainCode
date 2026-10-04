"""Application package.

The Windows event-loop policy is set here, at import time, because it must be in
place *before* any event loop is created — and importing ``app`` is the earliest
common point for the server, the worker, Alembic, and the test suite.

**Why it is needed.** psycopg's async mode cannot run on Windows' default
``ProactorEventLoop`` and raises ``InterfaceError`` on the first connection
attempt. That surfaces as a database error rather than a platform one, which
sends you inspecting the connection string instead of the loop.

**Why the deprecated call.** ``set_event_loop_policy`` is deprecated in Python
3.14 and slated for removal in 3.16. The documented replacement is passing
``loop_factory`` to ``asyncio.run`` / ``asyncio.Runner`` — but uvicorn and
pytest-asyncio own those calls, so the global policy is the only lever available
from here today.

**When 3.16 lands**, this stops working and the replacement is per-entry-point:
run uvicorn with ``--loop asyncio`` under a runner configured with
``loop_factory=asyncio.SelectorEventLoop``, and set the equivalent
``pytest-asyncio`` loop factory in ``pyproject.toml``. The warning is suppressed
rather than silenced globally so this note is the only thing to find.

No effect on Linux or macOS, where the policy class does not exist.
"""

import asyncio
import sys
import warnings

if sys.platform == "win32":  # pragma: no cover - platform-specific
    with warnings.catch_warnings():
        # Suppressed narrowly: only this call, only this category.
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
