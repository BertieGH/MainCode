import asyncio
import sys
from contextlib import asynccontextmanager

# Playwright launches a subprocess; on Windows this requires ProactorEventLoop.
# Python 3.14 / uvicorn-with-asyncio loop sometimes installs SelectorEventLoop
# under which `loop.subprocess_exec` raises NotImplementedError and the SPA
# Playwright retry path silently fails. Set the policy before the loop spins up.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.health import router as health_router
from app.api.signals import router as signals_router
from app.api.feeds import router as feeds_router
from app.api.settings import router as settings_router
from app.api.prospect_lists import router as prospect_lists_router
from app.api.enrichment import router as enrichment_router
from app.api.job_crawl import router as job_crawl_router
from app.api.outreach import router as outreach_router
from app.api.ingestion_runs import router as ingestion_runs_router
from app.api.articles import router as articles_router
from app.api.extraction_profiles import router as extraction_profiles_router
from app.api.job_prompt_profiles import router as job_prompt_profiles_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    if "sqlite" in settings.database_url:
        from app.database import init_db
        await init_db()

    # Load persisted settings from DB into the in-memory singleton so
    # subsequent `settings.gemini_api_key` reads see saved values.
    from app.database import async_session
    from app.services.settings_store import load_into_settings, seed_default_profile_if_empty
    async with async_session() as db:
        await load_into_settings(db)
        await seed_default_profile_if_empty(db)

    # Arq pool for enqueuing background jobs from HTTP routes.
    # When Redis isn't running (e.g. `run.bat` doesn't start it), arq's default
    # 5-retry × 1 s backoff spams the log. Use conn_retries=1 so we fail fast
    # and silently fall back to in-process asyncio tasks for enrich/crawl.
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    redis_settings.conn_retries = 1
    redis_settings.conn_timeout = 2
    try:
        app.state.arq_pool = await create_pool(redis_settings)
    except Exception:
        app.state.arq_pool = None

    try:
        yield
    finally:
        if app.state.arq_pool is not None:
            await app.state.arq_pool.close()


app = FastAPI(title="Recruitment Intelligence API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api", tags=["health"])
app.include_router(signals_router, prefix="/api", tags=["signals"])
app.include_router(feeds_router, prefix="/api", tags=["feeds"])
app.include_router(settings_router, prefix="/api", tags=["settings"])
app.include_router(prospect_lists_router, prefix="/api", tags=["prospect-lists"])
app.include_router(enrichment_router, prefix="/api", tags=["enrichment"])
app.include_router(job_crawl_router, prefix="/api", tags=["job-crawl"])
app.include_router(outreach_router, prefix="/api", tags=["outreach"])
app.include_router(ingestion_runs_router, prefix="/api", tags=["ingestion-runs"])
app.include_router(articles_router, prefix="/api", tags=["articles"])
app.include_router(extraction_profiles_router, prefix="/api", tags=["extraction-profiles"])
app.include_router(job_prompt_profiles_router, prefix="/api", tags=["job-prompt-profiles"])
