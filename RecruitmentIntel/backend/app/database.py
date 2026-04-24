from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        yield session


async def init_db():
    """Create all tables (used for SQLite local dev)."""
    # Import all models so Base.metadata knows about them
    import app.models.signal  # noqa: F401
    import app.models.prospect_list  # noqa: F401
    import app.models.prospect  # noqa: F401
    import app.models.job  # noqa: F401
    import app.models.feed_source  # noqa: F401
    import app.models.app_setting  # noqa: F401
    import app.models.ingestion_run  # noqa: F401
    import app.models.article  # noqa: F401
    import app.models.extraction_profile  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_sqlite_add_missing_columns)


def _sqlite_add_missing_columns(sync_conn) -> None:
    """Best-effort ALTER TABLE for new columns on SQLite dev DBs.

    `create_all` creates new tables but does not add columns to existing ones.
    For solo dev on SQLite we add any columns the ORM expects but the DB lacks,
    so a schema change doesn't force the developer to delete the DB (and lose
    their saved API key). PostgreSQL uses alembic migrations instead.
    """
    from sqlalchemy import inspect as sa_inspect, text

    inspector = sa_inspect(sync_conn)

    try:
        settings_cols = {col["name"] for col in inspector.get_columns("app_settings")}
    except Exception:
        settings_cols = None

    if settings_cols is not None:
        if "articles_per_feed_limit" not in settings_cols:
            sync_conn.execute(text(
                "ALTER TABLE app_settings ADD COLUMN articles_per_feed_limit INTEGER DEFAULT 20"
            ))
        if "auto_extract_on_ingest" not in settings_cols:
            sync_conn.execute(text(
                "ALTER TABLE app_settings ADD COLUMN auto_extract_on_ingest INTEGER DEFAULT 0"
            ))
        if "global_scrape_keywords" not in settings_cols:
            sync_conn.execute(text(
                "ALTER TABLE app_settings ADD COLUMN global_scrape_keywords JSON"
            ))
        if "extraction_prompt" not in settings_cols:
            sync_conn.execute(text(
                "ALTER TABLE app_settings ADD COLUMN extraction_prompt TEXT DEFAULT ''"
            ))
        if "llm_article_char_budget" not in settings_cols:
            sync_conn.execute(text(
                "ALTER TABLE app_settings ADD COLUMN llm_article_char_budget INTEGER DEFAULT 3500"
            ))
        if "job_target_titles" not in settings_cols:
            sync_conn.execute(text(
                "ALTER TABLE app_settings ADD COLUMN job_target_titles JSON"
            ))
        if "job_max_listing_pages" not in settings_cols:
            sync_conn.execute(text(
                "ALTER TABLE app_settings ADD COLUMN job_max_listing_pages INTEGER DEFAULT 4"
            ))
        if "job_max_subcategory_pages" not in settings_cols:
            sync_conn.execute(text(
                "ALTER TABLE app_settings ADD COLUMN job_max_subcategory_pages INTEGER DEFAULT 6"
            ))
        if "gemini_paid_api_key" not in settings_cols:
            sync_conn.execute(text(
                "ALTER TABLE app_settings ADD COLUMN gemini_paid_api_key VARCHAR(512) DEFAULT ''"
            ))
        if "gemini_tier" not in settings_cols:
            sync_conn.execute(text(
                "ALTER TABLE app_settings ADD COLUMN gemini_tier VARCHAR(10) DEFAULT 'free'"
            ))

    try:
        jobs_cols = {col["name"] for col in inspector.get_columns("jobs")}
    except Exception:
        jobs_cols = None

    if jobs_cols is not None and "match_target" not in jobs_cols:
        sync_conn.execute(text(
            "ALTER TABLE jobs ADD COLUMN match_target VARCHAR(255)"
        ))

    try:
        articles_cols = {col["name"] for col in inspector.get_columns("articles")}
    except Exception:
        articles_cols = None

    if articles_cols is not None and "keyword_hits" not in articles_cols:
        sync_conn.execute(text(
            "ALTER TABLE articles ADD COLUMN keyword_hits JSON"
        ))

    try:
        prospects_cols = {col["name"] for col in inspector.get_columns("prospects")}
    except Exception:
        prospects_cols = None

    if prospects_cols is not None:
        for col_ddl in [
            ("enrichment_strategy", "ALTER TABLE prospects ADD COLUMN enrichment_strategy VARCHAR(50)"),
            ("enrichment_error", "ALTER TABLE prospects ADD COLUMN enrichment_error TEXT"),
            ("job_crawl_strategy", "ALTER TABLE prospects ADD COLUMN job_crawl_strategy VARCHAR(50)"),
            ("job_crawl_raw_count", "ALTER TABLE prospects ADD COLUMN job_crawl_raw_count INTEGER DEFAULT 0"),
            ("job_crawl_error", "ALTER TABLE prospects ADD COLUMN job_crawl_error TEXT"),
        ]:
            col_name, ddl = col_ddl
            if col_name not in prospects_cols:
                sync_conn.execute(text(ddl))
