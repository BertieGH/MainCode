"""Dev launcher for the arq worker.

Two compatibility shims that vanilla `arq` / `python -m arq` don't handle
on Windows + Python 3.14:

  1. Set WindowsProactorEventLoopPolicy before any asyncio loop is created.
     arq's worker spawns subprocesses (we use Playwright in some tasks);
     SelectorEventLoop on Windows can't do `subprocess_exec`.

  2. Pre-create a current event loop. arq 0.26.1's Worker.__init__ calls
     `asyncio.get_event_loop()`, which raises RuntimeError on Python 3.12+
     when no loop is running and no thread-current loop has been set.
"""
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Establish a thread-current loop so arq's get_event_loop() succeeds.
asyncio.set_event_loop(asyncio.new_event_loop())

from arq.cli import cli  # noqa: E402

if __name__ == "__main__":
    # Equivalent to `arq app.tasks.worker.WorkerSettings`.
    if len(sys.argv) == 1:
        sys.argv.append("app.tasks.worker.WorkerSettings")
    cli()
