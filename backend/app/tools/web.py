"""
Web Search Tool — general_chat / general-purpose Q&A.

Tujuan: memberi NOVA kemampuan menjawab pertanyaan umum (di luar
Linux/Network/MikroTik/Cisco) dengan informasi terkini dari internet,
tanpa melatih model sendiri. Pola arsitektur PERSIS sama dengan
ping_tool (app/tools/network.py) — tool ini TIDAK istimewa, hanya
kebetulan targetnya "internet" alih-alih "host jaringan".

Permission level : READ  (hanya membaca, tidak mengubah apa pun)
Risk level        : LOW

Kenapa READ/LOW dan bukan lebih tinggi:
- Tidak ada tulis/ubah state apa pun di sistem manapun.
- Tidak mengeksekusi command shell — request HTTP terstruktur lewat
  library search & ekstraksi konten (duckduckgo_search, trafilatura),
  bukan os.system()/subprocess ke arbitrary URL.

Prinsip yang tetap dipegang (sama seperti seluruh app/tools/*):
- LLM TIDAK pernah memanggil requests/HTTP langsung. LLM hanya
  mengirim ToolRequest("web.search", {"query": ...}) lewat Tool
  Manager, backend yang mengeksekusi.
- Semua kegagalan (timeout, network error, parsing gagal) ditangkap
  eksplisit dan dikembalikan sebagai success=False + error — tidak
  pernah exception mentah bocor ke API layer (Bab "Error Handling",
  PRD section 37).
- Hasil dikembalikan sebagai structured data (list of hits + snippet
  + opsional isi halaman yang sudah dibersihkan), BUKAN html/teks
  mentah — supaya LLM tidak perlu parsing sendiri (PRD section 25,
  prinsip "Tools menghasilkan structured data").
- Konten hasil scraping adalah UNTRUSTED EXTERNAL DATA (PRD section
  31, Prompt Injection Defense): dikembalikan sebagai field data
  biasa, tidak pernah disisipkan sebagai instruksi sistem oleh tool
  ini. Filtering/pertahanan lanjutan tetap tanggung jawab lapisan
  prompt-assembly, bukan tool ini.

Dependency baru (tambahkan ke requirements.txt):
    ddgs==9.14.4        # nama package resmi sekarang (rename dari
                        # duckduckgo-search oleh maintainer, v8+)
    trafilatura==1.12.2
"""

from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel, Field, HttpUrl

from app.tools.schemas import (
    LoggingPolicy,
    PermissionLevel,
    RiskLevel,
    ToolDefinition,
)

logger = logging.getLogger("nova.tools.web")


# ----------------------------------------------------------------
# web.search — cari beberapa hasil dari internet
# ----------------------------------------------------------------


class WebSearchInput(BaseModel):
    query: str = Field(..., min_length=1, max_length=400, description="Kata kunci pencarian")
    max_results: int = Field(default=5, ge=1, le=10, description="Jumlah hasil maksimum")


class WebSearchHit(BaseModel):
    title: str
    url: str
    snippet: str


class WebSearchOutput(BaseModel):
    success: bool
    query: str
    results: list[WebSearchHit] = []
    error: str | None = None


def _search_sync(query: str, max_results: int) -> list[WebSearchHit]:
    """
    Bagian blocking (library duckduckgo_search murni sync) — dijalankan
    lewat asyncio.to_thread() dari executor async, konsisten dengan
    seluruh tool lain yang tidak boleh memblok event loop FastAPI.
    """
    # Import lokal: dependency opsional. Package resmi sekarang bernama
    # 'ddgs' (rename dari 'duckduckgo_search' oleh maintainer aslinya,
    # deedy5, per rilis v8+). Package lama masih ada di PyPI tapi versi
    # yang sempat kita pin (6.3.5) memaksa profil impersonate browser
    # ('chrome_119') yang sudah di-drop oleh curl_cffi versi baru ->
    # error "Invalid impersonate: chrome_119". 'ddgs' aktif di-maintain
    # dan tidak membawa masalah pin ini.
    from ddgs import DDGS

    hits: list[WebSearchHit] = []
    with DDGS() as ddgs:
        for item in ddgs.text(query, max_results=max_results):
            hits.append(
                WebSearchHit(
                    title=item.get("title", ""),
                    url=item.get("href", ""),
                    snippet=item.get("body", ""),
                )
            )
    return hits


async def execute_web_search(input: WebSearchInput) -> WebSearchOutput:
    try:
        results = await asyncio.to_thread(_search_sync, input.query, input.max_results)
    except Exception as exc:  # noqa: BLE001 — library pihak ketiga, semua kegagalan ditangkap
        logger.warning("web.search gagal untuk query=%r: %s", input.query, exc)
        return WebSearchOutput(success=False, query=input.query, error=str(exc))

    return WebSearchOutput(success=True, query=input.query, results=results)


web_search_tool = ToolDefinition(
    name="web.search",
    description=(
        "Mencari informasi umum/terkini di internet dan mengembalikan "
        "daftar hasil terstruktur (judul, url, snippet). Dipakai untuk "
        "pertanyaan umum di luar sistem/perangkat yang dikelola NOVA."
    ),
    input_model=WebSearchInput,
    output_model=WebSearchOutput,
    permission_level=PermissionLevel.READ,
    risk_level=RiskLevel.LOW,
    supported_platforms=["general"],
    timeout_seconds=15.0,
    logging_policy=LoggingPolicy.RESULT_ONLY,
    executor=execute_web_search,
)


# ----------------------------------------------------------------
# web.read_page — ambil isi bersih dari satu URL (opsional, dipanggil
# setelah web.search kalau LLM butuh detail lebih dari snippet)
# ----------------------------------------------------------------


class WebReadPageInput(BaseModel):
    url: HttpUrl = Field(..., description="URL halaman yang akan dibaca")
    max_chars: int = Field(
        default=6000, ge=500, le=20000, description="Batas keras panjang teks yang dikembalikan"
    )


class WebReadPageOutput(BaseModel):
    success: bool
    url: str
    title: str | None = None
    text: str | None = None
    truncated: bool = False
    error: str | None = None


def _read_page_sync(url: str, max_chars: int) -> WebReadPageOutput:
    import trafilatura

    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        return WebReadPageOutput(
            success=False, url=url, error="Gagal mengambil halaman (unreachable atau diblokir)."
        )

    text = trafilatura.extract(downloaded) or ""
    metadata = trafilatura.extract_metadata(downloaded)
    title = metadata.title if metadata else None

    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars]

    if not text:
        return WebReadPageOutput(
            success=False,
            url=url,
            title=title,
            error="Halaman berhasil diambil tapi tidak ada konten teks yang bisa diekstrak.",
        )

    return WebReadPageOutput(success=True, url=url, title=title, text=text, truncated=truncated)


async def execute_web_read_page(input: WebReadPageInput) -> WebReadPageOutput:
    url_str = str(input.url)
    try:
        return await asyncio.to_thread(_read_page_sync, url_str, input.max_chars)
    except Exception as exc:  # noqa: BLE001 — semua kegagalan network/parsing ditangkap
        logger.warning("web.read_page gagal untuk url=%r: %s", url_str, exc)
        return WebReadPageOutput(success=False, url=url_str, error=str(exc))


web_read_page_tool = ToolDefinition(
    name="web.read_page",
    description=(
        "Mengambil dan membersihkan isi teks dari satu URL (biasanya "
        "hasil dari web.search) agar bisa dibaca LLM tanpa HTML mentah."
    ),
    input_model=WebReadPageInput,
    output_model=WebReadPageOutput,
    permission_level=PermissionLevel.READ,
    risk_level=RiskLevel.LOW,
    supported_platforms=["general"],
    timeout_seconds=15.0,
    logging_policy=LoggingPolicy.RESULT_ONLY,
    executor=execute_web_read_page,
)
