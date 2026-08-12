"""
ASTRA — Application Settings

Pydantic BaseSettings loading from environment variables.
All configuration is centralized here.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ========================
    # Application
    # ========================
    app_name: str = "ASTRA"
    version: str = "0.1.0"
    environment: str = "development"
    debug: bool = True

    # Prefix mapping for env vars
    astra_app_name: str = "ASTRA"
    astra_version: str = "0.1.0"
    astra_env: str = "development"
    astra_debug: bool = True

    # ========================
    # Server
    # ========================
    astra_host: str = "0.0.0.0"
    astra_port: int = 8000
    astra_cors_origins: str = "http://localhost:5173"

    # ========================
    # Database
    # ========================
    database_url: str = "postgresql+asyncpg://astra:changeme@localhost:5432/astra"

    # ========================
    # AI Provider
    # ========================
    astra_ai_provider: str = "gemini"
    
    # Gemini
    astra_ai_model: str = "gemini-3.6-flash"
    gemini_api_key: str = ""
    
    # Groq
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    
    # Local Provider
    astra_local_enabled: bool = False
    astra_local_runtime: str = "openai"
    astra_local_model: str = "llama-3-8b-instruct"
    astra_local_base_url: str = "http://localhost:1234/v1"
    astra_local_context_length: int = 4096
    astra_local_max_tokens: int = 1024
    astra_local_temperature: float = 0.7
    astra_offline_mode: bool = False

    # Provider Resilience
    astra_ai_fallback_providers: str = "groq"
    astra_provider_cooldown_seconds: int = 60

    # ========================
    # Security
    # ========================
    astra_secret_key: str = "changeme_generate_a_real_secret_key"

    # ========================
    # Logging
    # ========================
    astra_log_level: str = "INFO"
    astra_log_format: str = "json"

    # ========================
    # Feature Flags
    # ========================
    astra_feature_voice: bool = False
    astra_feature_memory: bool = False
    astra_feature_knowledge: bool = False
    astra_feature_tools: bool = True
    astra_feature_agents: bool = False
    astra_feature_notch: bool = False

    # ========================
    # Voice / STT
    # ========================
    astra_stt_provider: str = "gemini"
    astra_tts_provider: str = "gtts"
    astra_local_stt_model: str = "base.en"
    astra_local_stt_device: str = "cuda"
    astra_local_stt_compute_type: str = "float16"

    # ========================
    # Tool Engine
    # ========================
    astra_tools_enabled: bool = True
    astra_tool_max_calls_per_turn: int = 5
    astra_tool_allowed_apps: str = "{}"
    astra_tool_allowed_fs_root: str = ""

    # ========================
    # Computed Properties
    # ========================

    @property
    def cors_origins(self) -> list[str]:
        """Parse CORS origins from comma-separated string."""
        return [origin.strip() for origin in self.astra_cors_origins.split(",")]

    @property
    def is_development(self) -> bool:
        return self.astra_env == "development"

    @property
    def is_production(self) -> bool:
        return self.astra_env == "production"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
