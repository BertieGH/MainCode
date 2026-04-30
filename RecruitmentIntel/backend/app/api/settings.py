from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.schemas.feed import SettingsOut, SettingsUpdate
from app.services.settings_store import save_patch
from app.services.signal_extraction import get_primary_provider

router = APIRouter()


def _masked_key(key: str) -> str:
    if not key:
        return ""
    if len(key) > 8:
        return key[:4] + "*" * (len(key) - 8) + key[-4:]
    return "****"


@router.get("/settings", response_model=SettingsOut)
async def get_settings():
    return SettingsOut(
        llm_provider=settings.llm_provider,
        gemini_api_key=_masked_key(settings.gemini_api_key),
        gemini_model=settings.gemini_model,
        gemini_paid_api_key=_masked_key(settings.gemini_paid_api_key),
        gemini_tier=settings.gemini_tier,
        ollama_host=settings.ollama_host,
        ollama_model=settings.ollama_model,
        fetch_interval_hours=settings.fetch_interval_hours,
        articles_per_feed_limit=settings.articles_per_feed_limit,
        auto_extract_on_ingest=settings.auto_extract_on_ingest,
        global_scrape_keywords=settings.global_scrape_keywords,
        extraction_prompt=settings.extraction_prompt,
        llm_article_char_budget=settings.llm_article_char_budget,
        career_patterns=settings.career_patterns,
        fallback_google=settings.fallback_google,
        fallback_linkedin=settings.fallback_linkedin,
        ats_detection=settings.ats_detection,
        job_target_titles=settings.job_target_titles,
        job_max_listing_pages=settings.job_max_listing_pages,
        job_max_subcategory_pages=settings.job_max_subcategory_pages,
        job_extract_prompt=settings.job_extract_prompt,
        job_match_prompt=settings.job_match_prompt,
        job_classify_prompt=settings.job_classify_prompt,
    )


@router.put("/settings", response_model=SettingsOut)
async def update_settings(data: SettingsUpdate, db: AsyncSession = Depends(get_db)):
    patch = {}
    for field, value in data.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        # Don't accept the masked value the UI echoes back
        if field in ("gemini_api_key", "gemini_paid_api_key") and "*" in str(value):
            continue
        patch[field] = value

    if patch:
        await save_patch(db, patch)

    return await get_settings()


@router.post("/settings/test-connection")
async def test_connection():
    provider = get_primary_provider()
    if not provider:
        return {"status": "error", "message": "No provider configured. Set API key first."}

    try:
        success = await provider.test_connection()
    except Exception as e:
        return {
            "status": "error",
            "provider": settings.llm_provider,
            "message": f"{type(e).__name__}: {e}",
        }

    return {
        "status": "ok" if success else "error",
        "provider": settings.llm_provider,
        "message": "Connection successful" if success else "Connection failed (no OK in response)",
    }
