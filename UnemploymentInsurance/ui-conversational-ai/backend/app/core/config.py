from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    gcp_project_id: str = ""
    gcp_region: str = "us-central1"
    vertex_ai_location: str = "us-central1"

    planner_model: str = "gemini-2.5-pro"
    flash_model: str = "gemini-2.5-flash"

    vertex_search_data_store_policy: str = ""
    vertex_search_data_store_qbank: str = ""
    vertex_search_data_store_allowlist: str = ""

    dlp_inspect_template: str = ""
    dlp_deidentify_template: str = ""

    doc_ai_processor_paystub: str = ""
    doc_ai_processor_separation: str = ""

    firestore_database: str = "(default)"
    database_url: str = "postgresql+asyncpg://user:pass@localhost:5432/ui_conv_ai"

    api_host: str = "0.0.0.0"
    api_port: int = 8003
    log_level: str = "INFO"

    conf_autonomous_min: float = Field(0.90, ge=0.0, le=1.0)
    conf_adjudicator_min: float = Field(0.65, ge=0.0, le=1.0)

    max_turns_per_conversation: int = 20
    max_planner_steps_per_turn: int = 4
    turn_deadline_seconds: int = 15

    autonomous_band_enabled: bool = False
    shadow_decisions_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
