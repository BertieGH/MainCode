"""Dev launcher that pins ProactorEventLoopPolicy before uvicorn starts.

Playwright launches a subprocess; on Windows that requires the Proactor
event loop. On Python 3.14 + uvicorn, the default policy at the moment
uvicorn creates its loop has been observed to be Selector, causing
`loop.subprocess_exec` to raise NotImplementedError when our SPA fallback
fires. Setting the policy here, before uvicorn imports / creates a loop,
guarantees Playwright works.
"""
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8002,
        reload=True,
        loop="asyncio",
    )
