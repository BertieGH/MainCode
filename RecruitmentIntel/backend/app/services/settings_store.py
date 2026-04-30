"""Persist the user-editable subset of `app.config.settings` to the database.

On startup we load from DB into the in-memory pydantic singleton, so every
`from app.config import settings; settings.X` caller just works. On PUT we
write the patch back to the singleton *and* the DB.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.app_setting import AppSetting

# Fields that are user-editable and worth persisting. Infra-level fields
# (DB URL, Redis URL, CORS origins) stay env-only.
PERSISTED_FIELDS = (
    "llm_provider",
    "gemini_api_key",
    "gemini_model",
    "gemini_paid_api_key",
    "gemini_tier",
    "ollama_host",
    "ollama_model",
    "fetch_interval_hours",
    "articles_per_feed_limit",
    "auto_extract_on_ingest",
    "global_scrape_keywords",
    "extraction_prompt",
    "llm_article_char_budget",
    "career_patterns",
    "fallback_google",
    "fallback_linkedin",
    "ats_detection",
    "job_target_titles",
    "job_max_listing_pages",
    "job_max_subcategory_pages",
    "job_extract_prompt",
    "job_match_prompt",
    "job_classify_prompt",
)


async def _get_or_create_row(db: AsyncSession) -> AppSetting:
    result = await db.execute(select(AppSetting).where(AppSetting.id == 1))
    row = result.scalar_one_or_none()
    if row is not None:
        return row
    # Seed a new row from the current in-memory defaults (env / pydantic defaults)
    row = AppSetting(
        id=1,
        **{field: getattr(settings, field) for field in PERSISTED_FIELDS},
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def load_into_settings(db: AsyncSession) -> None:
    """Startup hook: mirror the persisted row onto the in-memory singleton."""
    row = await _get_or_create_row(db)
    for field in PERSISTED_FIELDS:
        object.__setattr__(settings, field, getattr(row, field))


async def save_patch(db: AsyncSession, patch: dict) -> None:
    """Apply a partial update to both the DB row and the in-memory singleton."""
    row = await _get_or_create_row(db)
    for field, value in patch.items():
        if field not in PERSISTED_FIELDS or value is None:
            continue
        setattr(row, field, value)
        object.__setattr__(settings, field, value)
    await db.commit()


# Seed keywords + preset name used on first startup. Keeps new installs useful
# out of the box without forcing the user to craft a prompt from scratch.
FUNDING_KEYWORDS = ["funding", "raised", "series", "seed", "round", "investment"]
FUNDING_PRESET_NAME = "Funding Scraper"


async def seed_default_profile_if_empty(db: AsyncSession) -> None:
    """If no extraction profiles exist yet, create the Funding Scraper preset."""
    from sqlalchemy import select as sa_select
    from app.models.extraction_profile import ExtractionProfile
    from app.services.signal_extraction import DEFAULT_EXTRACTION_PROMPT

    any_profile = await db.execute(sa_select(ExtractionProfile).limit(1))
    if any_profile.scalar_one_or_none() is not None:
        return

    db.add(ExtractionProfile(
        name=FUNDING_PRESET_NAME,
        extraction_prompt=DEFAULT_EXTRACTION_PROMPT,
        scrape_keywords=list(FUNDING_KEYWORDS),
    ))
    await db.commit()
