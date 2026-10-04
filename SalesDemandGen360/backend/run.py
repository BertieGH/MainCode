"""Development server entry point.

    python run.py            # http://127.0.0.1:8011

**Why this exists rather than plain `uvicorn app.main:app`.**

uvicorn picks its event loop with a *factory*, not the global policy:

    def asyncio_loop_factory(use_subprocess=False):
        if sys.platform == "win32" and not use_subprocess:
            return asyncio.ProactorEventLoop
        return asyncio.SelectorEventLoop

So on Windows it hardcodes ``ProactorEventLoop`` — and psycopg's async mode
cannot run on it, raising ``InterfaceError`` on the first query. Setting the
global policy has no effect here, because uvicorn never consults it.

The fix is to hand uvicorn the factory we want. This is also the direction
Python itself is moving: ``set_event_loop_policy`` is deprecated in 3.14, and
``loop_factory`` is the supported replacement.

(``--reload`` happens to work by accident, because reload runs the server in a
subprocess and that branch returns ``SelectorEventLoop``. Relying on that would
mean the app works in development and fails in production.)
"""

from __future__ import annotations

import asyncio
import sys

import uvicorn


def main() -> None:
    config = uvicorn.Config(
        "app.main:app",
        host="127.0.0.1",
        port=8011,
        log_level="info",
        reload=False,
    )

    if sys.platform == "win32":
        # Override the hardcoded ProactorEventLoop.
        config.get_loop_factory = lambda: asyncio.SelectorEventLoop  # type: ignore[method-assign]

    uvicorn.Server(config).run()


if __name__ == "__main__":
    main()
