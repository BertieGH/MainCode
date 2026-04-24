from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AppSetting(Base):
    """Singleton row (id=1) persisting user-editable app settings across restarts."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    llm_provider: Mapped[str] = mapped_column(String(20), default="gemini")
    gemini_api_key: Mapped[str] = mapped_column(String(512), default="")
    gemini_model: Mapped[str] = mapped_column(String(100), default="gemini-2.5-flash")
    gemini_paid_api_key: Mapped[str] = mapped_column(String(512), default="")
    gemini_tier: Mapped[str] = mapped_column(String(10), default="free")
    ollama_host: Mapped[str] = mapped_column(String(512), default="http://localhost:11434")
    ollama_model: Mapped[str] = mapped_column(String(100), default="llama3")
    fetch_interval_hours: Mapped[int] = mapped_column(Integer, default=2)
    articles_per_feed_limit: Mapped[int] = mapped_column(Integer, default=20)
    auto_extract_on_ingest: Mapped[bool] = mapped_column(Boolean, default=False)
    global_scrape_keywords: Mapped[list] = mapped_column(JSON, default=list)
    extraction_prompt: Mapped[str] = mapped_column(Text, default="")
    llm_article_char_budget: Mapped[int] = mapped_column(Integer, default=3500)
    career_patterns: Mapped[list] = mapped_column(JSON, default=list)
    fallback_google: Mapped[bool] = mapped_column(Boolean, default=True)
    fallback_linkedin: Mapped[bool] = mapped_column(Boolean, default=True)
    ats_detection: Mapped[list] = mapped_column(JSON, default=list)
    job_target_titles: Mapped[list] = mapped_column(JSON, default=list)
    job_max_listing_pages: Mapped[int] = mapped_column(Integer, default=4)
    job_max_subcategory_pages: Mapped[int] = mapped_column(Integer, default=6)
