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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


# Singleton settings instance, di-import oleh module lain.
settings = Settings()