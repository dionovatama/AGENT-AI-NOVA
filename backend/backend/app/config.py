"""
Central configuration for N.O.V.A backend.

Prinsip:
- Tidak ada credential atau secret yang di-hardcode di source code.
- Semua nilai sensitif/non-sensitif dibaca dari environment (.env).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Application ---
    app_name: str = "N.O.V.A"
    app_env: str = "development"

    # --- Database ---
    database_url: str

    # --- JWT ---
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30

    # --- OpenRouter (AI Gateway) ---
    openrouter_api_key: str
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # OpenRouter merekomendasikan header ini untuk atribusi di leaderboard mereka.
    # Tidak wajib secara fungsional, tapi baik untuk disertakan.
    openrouter_site_url: str = "http://localhost:3000"
    openrouter_app_title: str = "N.O.V.A"

    # --- Model Router: task category -> model ---
    # Tidak di-hardcode di kode. Semua dapat diganti dari .env tanpa
    # mengubah arsitektur (sesuai keputusan Tuan di poin G.1).
    #
    # Catatan: field TIDAK diawali "model_" karena itu reserved prefix
    # internal Pydantic v2 (model_dump, model_validate, dst).
    general_chat_model: str = "openai/gpt-4o-mini"
    technical_reasoning_model: str = "anthropic/claude-3.5-sonnet"
    troubleshooting_model: str = "anthropic/claude-3.5-sonnet"
    network_diagnostic_model: str = "openai/gpt-4o-mini"
    configuration_generation_model: str = "anthropic/claude-3.5-sonnet"
    coding_model: str = "anthropic/claude-3.5-sonnet"
    summarization_model: str = "openai/gpt-4o-mini"

    # Fallback model global — dipakai jika model primary pada kategori
    # manapun gagal (timeout, unavailable, rate limit, provider error).
    fallback_model: str = "openai/gpt-4o-mini"

    # --- Model behavior ---
    openrouter_request_timeout_seconds: float = 30.0
    openrouter_max_tokens: int = 1024

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


# Singleton settings instance, di-import oleh module lain.
settings = Settings()
