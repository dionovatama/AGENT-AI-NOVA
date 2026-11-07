"""Central configuration for N.O.V.A backend."""

from typing import Any
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DEV_CORS_ORIGINS: list[str] = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]


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

    # --- Public exposure guardrails ---
    # Registration is opt-in in development and forbidden in production.
    public_registration_enabled: bool = False
    # Direct device sockets from the backend are lab-only. Production device
    # access must use an authenticated Remote Agent relay and target allow-list.
    allow_direct_device_connections: bool = True
    # Only these reverse-proxy peers may supply X-Forwarded-For. Keep empty
    # unless the backend is actually behind a trusted proxy.
    trusted_proxy_ips: list[str] = []

    # --- OpenRouter (AI Gateway) ---
    openrouter_api_key: str
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: str = "http://localhost:3000"
    openrouter_app_title: str = "N.O.V.A"

    # --- Model Router: task category -> model ---
    general_chat_model: str = "openai/gpt-4o-mini"
    technical_reasoning_model: str = "anthropic/claude-3.5-sonnet"
    troubleshooting_model: str = "anthropic/claude-3.5-sonnet"
    network_diagnostic_model: str = "openai/gpt-4o-mini"
    configuration_generation_model: str = "anthropic/claude-3.5-sonnet"
    coding_model: str = "anthropic/claude-3.5-sonnet"
    summarization_model: str = "openai/gpt-4o-mini"
    fallback_model: str = "openai/gpt-4o-mini"

    # --- Model behavior ---
    openrouter_request_timeout_seconds: float = 30.0
    openrouter_max_tokens: int = 8192
    openrouter_reasoning_effort: str = "low"
    tool_calling_model: str = "nex-agi/nex-n2.5-mini:free"
    tool_calling_fallback_model: str = "openrouter/free"

    # --- Linux Executor (SSH) ---
    linux_ssh_host: str
    linux_ssh_port: int = 22
    linux_ssh_username: str = "nova"
    linux_ssh_private_key_path: str
    linux_ssh_connect_timeout_seconds: float = 10.0
    linux_ssh_host_key_checking: bool = False
    linux_ssh_known_hosts_path: str | None = None

    # --- Configuration Engine Kill-Switch ---
    config_apply_enabled: bool = False
    audit_log_retention_days: int = 90

    # --- MikroTik monitoring history ---
    monitoring_sample_interval_seconds: int = 15
    monitoring_retention_days: int = 7
    monitoring_max_samples_per_device: int = 20000

    # --- Credential encryption at rest ---
    credential_encryption_keys_json: str | None = None
    credential_encryption_active_key_id: str | None = None

    # --- NOVA Remote Agent Gateway ---
    nova_agent_tokens_json: str = "{}"
    nova_agent_heartbeat_interval_seconds: int = 30

    # --- Image Generation ---
    cloudflare_account_id: str | None = None
    cloudflare_api_token: str | None = None
    image_model: str = "@cf/black-forest-labs/flux-1-schnell"

    # --- Remote Agent ---
    agent_auth_timeout_seconds: float = 10.0
    agent_heartbeat_interval_seconds: float = 30.0
    agent_heartbeat_timeout_seconds: float = 90.0
    agent_max_message_bytes: int = 65536
    agent_heartbeat_min_db_interval_seconds: float = 5.0
    agent_sweep_interval_seconds: float = 30.0
    agent_auth_fail_limit: int = 10
    agent_auth_fail_window_seconds: float = 60.0
    agent_max_pending_auth_per_ip: int = 20
    agent_max_messages_per_window: int = 20
    agent_message_window_seconds: float = 10.0
    agent_require_tls: bool | None = None

    # --- HTTP Rate Limiting ---
    rate_limit_auth_login_limit: int = 5
    rate_limit_auth_login_window_seconds: float = 60.0
    rate_limit_auth_register_limit: int = 3
    rate_limit_auth_register_window_seconds: float = 60.0
    rate_limit_chat_limit: int = 5
    rate_limit_chat_window_seconds: float = 60.0
    rate_limit_tools_execute_limit: int = 30
    rate_limit_tools_execute_window_seconds: float = 60.0
    rate_limit_monitoring_limit: int = 60
    rate_limit_monitoring_window_seconds: float = 60.0
    rate_limit_images_limit: int = 2
    rate_limit_images_window_seconds: float = 60.0

    # --- CORS ---
    cors_origins: list[str] = list(DEFAULT_DEV_CORS_ORIGINS)

    @field_validator("cors_origins", "trusted_proxy_ips", mode="before")
    @classmethod
    def _parse_string_lists(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return []
            if value.startswith("[") and value.endswith("]"):
                import json
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed if str(item).strip()]
                except Exception:
                    pass
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, (list, set, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        return value

    @model_validator(mode="after")
    def _validate_production_requirements(self) -> "Settings":
        if self.app_env.lower() == "production":
            if len(self.jwt_secret_key) < 32:
                raise ValueError("Production requires jwt_secret_key to be at least 32 characters.")
            if self.agent_require_tls is not True:
                raise ValueError("Production requires agent_require_tls=True.")
            if self.public_registration_enabled:
                raise ValueError("Production must keep public_registration_enabled=False.")
            if self.allow_direct_device_connections:
                raise ValueError(
                    "Production must set allow_direct_device_connections=False; use Remote Agent relay."
                )
            if not self.cors_origins or self.cors_origins == DEFAULT_DEV_CORS_ORIGINS:
                raise ValueError("Production requires explicit non-localhost CORS_ORIGINS.")
            for origin in self.cors_origins:
                lower_origin = origin.lower()
                if origin == "*" or "localhost" in lower_origin or "127.0.0.1" in lower_origin:
                    raise ValueError(f"Invalid production CORS origin: {origin}")
                if not origin.startswith(("http://", "https://")):
                    raise ValueError(f"CORS origin must start with http:// or https://: {origin}")

        # Validate proxy entries at startup; malformed trust boundaries must not
        # silently broaden the set of peers allowed to supply forwarding headers.
        import ipaddress
        for proxy in self.trusted_proxy_ips:
            try:
                ipaddress.ip_network(proxy, strict=False)
            except ValueError as exc:
                raise ValueError(f"Invalid TRUSTED_PROXY_IPS entry: {proxy}") from exc

        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


settings = Settings()
