from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class FeedCreate(BaseModel):
    name: str
    url: str
    feed_type: str = "Google News"
    keywords: list[str] = []


class FeedUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    feed_type: str | None = None
    keywords: list[str] | None = None
    is_active: bool | None = None


class FeedOut(BaseModel):
    id: UUID
    name: str
    url: str
    feed_type: str
    keywords: list[str]
    is_active: bool
    last_fetched: datetime | None
    consecutive_failures: int
    created_at: datetime

    model_config = {"from_attributes": True}


class SettingsOut(BaseModel):
    llm_provider: str
    gemini_api_key: str
    gemini_model: str
    gemini_paid_api_key: str
    gemini_tier: str
    ollama_host: str
    ollama_model: str
    fetch_interval_hours: int
    articles_per_feed_limit: int
    auto_extract_on_ingest: bool
    global_scrape_keywords: list[str]
    extraction_prompt: str
    llm_article_char_budget: int
    career_patterns: list[str]
    fallback_google: bool
    fallback_linkedin: bool
    ats_detection: list[str]
    job_target_titles: list[str]
    job_max_listing_pages: int
    job_max_subcategory_pages: int
    job_extract_prompt: str
    job_match_prompt: str
    job_classify_prompt: str


class BackfillRunOut(BaseModel):
    id: UUID
    kind: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    total: int
    processed: int
    updated: int
    still_unknown: int
    via_location: int
    via_llm: int
    message: str | None
    trigger: str

    model_config = {"from_attributes": True}


class SettingsUpdate(BaseModel):
    llm_provider: str | None = None
    gemini_api_key: str | None = None
    gemini_model: str | None = None
    gemini_paid_api_key: str | None = None
    gemini_tier: str | None = None
    ollama_host: str | None = None
    ollama_model: str | None = None
    fetch_interval_hours: int | None = None
    articles_per_feed_limit: int | None = None
    auto_extract_on_ingest: bool | None = None
    global_scrape_keywords: list[str] | None = None
    extraction_prompt: str | None = None
    llm_article_char_budget: int | None = None
    career_patterns: list[str] | None = None
    fallback_google: bool | None = None
    fallback_linkedin: bool | None = None
    ats_detection: list[str] | None = None
    job_target_titles: list[str] | None = None
    job_max_listing_pages: int | None = None
    job_max_subcategory_pages: int | None = None
    job_extract_prompt: str | None = None
    job_match_prompt: str | None = None
    job_classify_prompt: str | None = None
