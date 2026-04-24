from fastapi import Request


async def get_arq_pool(request: Request):
    """Return the arq pool, or None if Redis wasn't available at startup.

    Endpoints that need background execution should branch on None and
    fall back to an in-process `asyncio.create_task` so local dev
    without a running worker still works.
    """
    return getattr(request.app.state, "arq_pool", None)
