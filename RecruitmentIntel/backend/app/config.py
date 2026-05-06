from pydantic_settings import BaseSettings
from typing import Literal


class Settings(BaseSettings):
    # Database — defaults to SQLite for local dev, set to PostgreSQL for Docker
    database_url: str = "sqlite+aiosqlite:///./recruitmentintel.db"
    database_url_sync: str = "sqlite:///./recruitmentintel.db"

    # Redis (optional for local dev)
    redis_url: str = "redis://localhost:6379/0"

    # LLM Provider
    llm_provider: Literal["gemini", "ollama"] = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    # Paid-tier API key — used when gemini_tier == "paid". Falls back to
    # gemini_api_key if blank, so existing single-key setups keep working.
    gemini_paid_api_key: str = ""
    # "free" = bail the batch on first 429 (free tier RPD is small);
    # "paid" = treat 429 as a transient burst and retry with backoff.
    gemini_tier: Literal["free", "paid"] = "free"
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3"

    # Ingestion
    fetch_interval_hours: int = 2
    articles_per_feed_limit: int = 20
    auto_extract_on_ingest: bool = False
    global_scrape_keywords: list[str] = []
    extraction_prompt: str = ""  # Loaded from DB or falls back to DEFAULT_EXTRACTION_PROMPT
    # Chars of article body sent to the LLM per extraction call. Higher = better
    # recall on long pieces, more tokens per call. Clamped to [500, 30000].
    llm_article_char_budget: int = 3500

    # Job Crawl
    career_patterns: list[str] = ["/careers", "/jobs", "/join-us", "/open-positions"]
    fallback_google: bool = True
    fallback_linkedin: bool = True
    ats_detection: list[str] = ["Greenhouse", "Lever", "Workable", "Ashby"]
    # Only save jobs whose title semantically matches one of these (LLM-judged).
    # Empty list = save every job we find (today's behaviour).
    job_target_titles: list[str] = []
    # Per-prospect cap on validated listings pages we actually scrape.
    job_max_listing_pages: int = 4
    # Per hub-page cap on sub-category links we follow when expanding.
    job_max_subcategory_pages: int = 6
    # Editable LLM prompts for the three job-crawl LLM call sites.
    # Empty string → falls back to DEFAULT_JOB_*_PROMPT in services/job_scraper.py.
    job_extract_prompt: str = ""
    job_match_prompt: str = ""
    job_classify_prompt: str = ""

    # CORS
    cors_origins: list[str] = ["http://localhost:4200", "http://localhost:4201", "http://localhost:4300"]

    model_config = {"env_prefix": "RI_", "env_file": ".env"}


settings = Settings()
