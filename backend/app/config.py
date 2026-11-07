"""
Central configuration for N.O.V.A backend.

Prinsip:
- Tidak ada credential atau secret yang di-hardcode di source code.
- Semua nilai sensitif/non-sensitif dibaca dari environment (.env).
"""

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
    public_registration_enabled: bool = False
    allow_direct_device_connections: bool = True
    trusted_proxy_ips: list[str] = []

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
    # Default dinaikkan dari 1024 -> 4096: reasoning model (mis. nemotron)
    # menghabiskan token budget untuk reasoning sebelum menulis jawaban
    # akhir, sehingga 1024 sering membuat content kosong dan dianggap
    # gagal. Evidence: NOVA_Phase2_OpenRouter_Integration_Log.txt Bug #2.
    openrouter_max_tokens: int = 8192

    # Kontrol reasoning effort (dokumentasi resmi OpenRouter, param
    # 'reasoning.effort') -- membatasi porsi max_tokens yang dipakai
    # model untuk "berpikir" tersembunyi sebelum menulis jawaban akhir.
    # 'low' menyisakan lebih banyak token untuk jawaban terlihat --
    # penting khusus saat tool-calling aktif, karena giliran kedua
    # (merangkum hasil web.search/web.read_page) butuh reasoning lebih
    # berat dan lebih gampang menghabiskan max_tokens sebelum sempat
    # menulis jawaban (Evidence: Phase 2 Bug #2, kambuh lagi di jalur
    # tool-calling dengan gejala jawaban terpotong jadi 1-2 kata).
    # Nilai valid: "high" | "medium" | "low" | "minimal" | "none".
    openrouter_reasoning_effort: str = "low"

    # --- Model khusus untuk jalur Tool-Calling (web.search/web.read_page) ---
    # SENGAJA TERPISAH dari GENERAL_CHAT_MODEL: model chat biasa (mis.
    # nvidia/nemotron-3.5-lightning:free) TIDAK terbukti solid untuk
    # function-calling (gejala: tool_calls kosong, model diam-diam
    # menjawab dari memori sendiri meski use_tools=True -- lihat kasus
    # tanggal pelantikan presiden yang salah, seharusnya trigger
    # web.search kalau tool-calling benar-benar aktif).
    #
    # Keputusan desain: model untuk kemampuan tool-calling ditentukan
    # BACKEND (NOVA), bukan dipilih bebas oleh user di UI -- konsisten
    # dengan Core Principle "backend yang berwenang", plus mencegah
    # user awam tanpa sadar pilih model berbayar mahal atau model yang
    # tool-calling-nya tidak reliable.
    #
    # nex-agi/nex-n2-pro:free (pilihan semula) mulai 404 "No endpoints
    # found" -- provider gratisnya sudah ditarik OpenRouter. Diganti ke
    # generasi penerusnya, nex-agi/nex-n2.5-mini:free, yang FAQ resmi
    # halaman modelnya eksplisit mengonfirmasi dukungan tools/tool_choice
    # (bukan dugaan), konteks 262K.
    #
    # CATATAN: pengumuman resmi OpenRouter menyebut model N2.5 ini
    # "free for a limited time" -- artinya berpotensi ditarik/dibayar
    # lagi seperti nex-n2-pro:free. Kalau ini 404 lagi di kemudian hari,
    # itu BUKAN bug kode -- cek dulu status model di openrouter.ai
    # sebelum menyalahkan tool_calling.py. Jaring pengaman untuk kasus
    # ini sudah ada lewat tool_calling_fallback_model di bawah.
    tool_calling_model: str = "nex-agi/nex-n2.5-mini:free"

    # Fallback KHUSUS tool-calling: openrouter/free adalah router yang
    # otomatis memfilter model yang mendukung tool-calling -- fallback
    # yang lebih aman daripada FALLBACK_MODEL biasa (yang mungkin juga
    # tidak reliable untuk tools, sama seperti masalah primary di atas).
    tool_calling_fallback_model: str = "openrouter/free"

    # --- Linux Executor (SSH) — Milestone 4 ---
    # Wajib diisi di .env, tidak ada default — sesuai prinsip fail-safe
    # (aplikasi menolak start daripada diam-diam pakai target kosong).
    linux_ssh_host: str
    linux_ssh_port: int = 22
    linux_ssh_username: str = "nova"
    linux_ssh_private_key_path: str
    linux_ssh_connect_timeout_seconds: float = 10.0

    # --- SSH Host Key Verification (AUDIT FIX-01 Phase 9) ---
    # Default False: menjaga kompatibilitas lab development (test VM dengan host key dinamis).
    # Production / Secure mode: set LINUX_SSH_HOST_KEY_CHECKING=true dan arahkan
    # LINUX_SSH_KNOWN_HOSTS_PATH ke file known_hosts untuk strict host verification.
    linux_ssh_host_key_checking: bool = False
    linux_ssh_known_hosts_path: str | None = None

    # --- Configuration Engine Kill-Switch (PRD section 39) ---
    # Default False: memblokir seluruh eksekusi perubahan konfigurasi ke perangkat jaringan.
    # Wajib bernilai True jika ingin menerapkan perubahan ke perangkat lab.
    config_apply_enabled: bool = False

    audit_log_retention_days: int = 90

    # --- MikroTik monitoring history (Phase 7) ---
    monitoring_sample_interval_seconds: int = 15
    monitoring_retention_days: int = 7
    monitoring_max_samples_per_device: int = 20000

    # --- Credential encryption at rest ---
    # JSON keyring: {"key-id":"base64-encoded-32-byte-key"}.
    # Keep keys in deployment secret storage, never in the database/repository.
    credential_encryption_keys_json: str | None = None
    credential_encryption_active_key_id: str | None = None

    # --- NOVA Remote Agent Gateway (Phase 1) ---
    # JSON object mapping pre-provisioned agent UUIDs to high-entropy tokens.
    # Keep this value in the deployment secret store; never commit real tokens.
    nova_agent_tokens_json: str = "{}"
    nova_agent_heartbeat_interval_seconds: int = 30
    # --- Image Generation (Cloudflare Workers AI) ---
    # Opsional: kalau kosong, POST /images/generate menjawab 503 [CONFIG]
    # (bukan membuat seluruh backend gagal start).
    cloudflare_account_id: str | None = None
    cloudflare_api_token: str | None = None
    image_model: str = "@cf/black-forest-labs/flux-1-schnell"

    # --- Remote Agent (Phase A) ---
    # Semua punya default aman; tidak ada env wajib baru.
    agent_auth_timeout_seconds: float = 10.0        # batas waktu frame 'auth' setelah handshake
    agent_heartbeat_interval_seconds: float = 30.0  # interval yang diminta server ke agent
    agent_heartbeat_timeout_seconds: float = 90.0   # tanpa pesan sebanyak ini -> putus (harus > interval)
    agent_max_message_bytes: int = 65536
    agent_heartbeat_min_db_interval_seconds: float = 5.0
    agent_sweep_interval_seconds: float = 30.0
    # Rate limiting (per proses/worker; lihat app/agents/ratelimit.py).
    agent_auth_fail_limit: int = 10                 # auth gagal per IP per jendela -> IP ditolak
    agent_auth_fail_window_seconds: float = 60.0
    agent_max_pending_auth_per_ip: int = 20         # koneksi belum terautentikasi serentak per IP
    agent_max_messages_per_window: int = 20         # pesan per koneksi per jendela
    agent_message_window_seconds: float = 10.0
    # None = otomatis: wajib TLS (wss) jika APP_ENV=production. Set false/true untuk override.
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

    # --- CORS (Cross-Origin Resource Sharing) ---
    cors_origins: list[str] = list(DEFAULT_DEV_CORS_ORIGINS)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            if v.startswith("[") and v.endswith("]"):
                import json
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed if str(item).strip()]
                except Exception:
                    pass
            return [item.strip() for item in v.split(",") if item.strip()]
        if isinstance(v, (list, set, tuple)):
            return [str(item).strip() for item in v if str(item).strip()]
        return v

    @field_validator("trusted_proxy_ips", mode="before")
    @classmethod
    def _parse_trusted_proxy_ips(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            if v.startswith("[") and v.endswith("]"):
                import json
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed if str(item).strip()]
                except Exception:
                    pass
            return [item.strip() for item in v.split(",") if item.strip()]
        if isinstance(v, (list, set, tuple)):
            return [str(item).strip() for item in v if str(item).strip()]
        return v

    @model_validator(mode="after")
    def _validate_production_requirements(self) -> "Settings":
        if self.app_env.lower() == "production":
            # 1. JWT secret key >= 32 characters
            if len(self.jwt_secret_key) < 32:
                raise ValueError(
                    f"Production environment requires jwt_secret_key to be at least 32 characters long "
                    f"(currently {len(self.jwt_secret_key)} characters)."
                )

            if self.public_registration_enabled:
                raise ValueError("Production must keep public_registration_enabled=False.")
            if self.allow_direct_device_connections:
                raise ValueError(
                    "Production must set allow_direct_device_connections=False; use Remote Agent relay."
                )

            # 2. Remote agent must enforce TLS
            if self.agent_require_tls is not True:
                raise ValueError(
                    "Production environment requires agent_require_tls=True."
                )

            # 3. CORS origins must be explicitly configured from environment (no defaults, no wildcards, no localhost)
            if not self.cors_origins:
                raise ValueError(
                    "Production environment requires cors_origins to be non-empty."
                )
            if self.cors_origins == DEFAULT_DEV_CORS_ORIGINS:
                raise ValueError(
                    "Production environment cannot use default localhost CORS origins. "
                    "Configure CORS_ORIGINS from environment."
                )
            for origin in self.cors_origins:
                if origin == "*":
                    raise ValueError(
                        "Production environment cannot use wildcard '*' in CORS_ORIGINS."
                    )
                lower_origin = origin.lower()
                if "localhost" in lower_origin or "127.0.0.1" in lower_origin:
                    raise ValueError(
                        f"Production environment cannot contain localhost or 127.0.0.1 in CORS_ORIGINS: {origin}"
                    )
                if not origin.startswith(("http://", "https://")):
                    raise ValueError(
                        f"CORS origin must start with http:// or https://: {origin}"
                    )

        # Validate proxy entries at startup; malformed trust boundaries fail closed.
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


# Singleton settings instance, di-import oleh module lain.
settings = Settings()