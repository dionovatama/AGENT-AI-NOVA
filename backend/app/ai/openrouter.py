"""
OpenRouter client — AI Gateway abstraction layer.

Prinsip (sesuai PRD):
- NOVA tidak boleh bergantung langsung pada satu model tertentu.
- Jika model primary gagal (timeout, unavailable, rate limit, provider
  error, malformed response), coba model fallback.
- Backend tidak boleh mengklaim fallback berhasil jika belum diverifikasi
  — yaitu, hanya dianggap sukses jika response benar-benar valid.
"""

import logging
from typing import Any

import httpx
from pydantic import BaseModel

from app.config import settings
from app.ai.model_router import TaskCategory, get_primary_model, get_fallback_model

logger = logging.getLogger("nova.ai.openrouter")


class OpenRouterError(Exception):
    """Base error untuk semua kegagalan komunikasi dengan OpenRouter."""


class ChatMessage(BaseModel):
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str | None = None

    # Field di bawah ini HANYA dipakai oleh jalur tool-calling
    # (app/ai/tool_calling.py). Default None supaya seluruh pemakaian
    # ChatMessage yang sudah ada (chat.py Milestone 2, test_ai.py) tetap
    # jalan tanpa perubahan — payload dikirim dengan exclude_none=True
    # jadi field-field ini tidak muncul sama sekali untuk chat biasa.
    tool_call_id: str | None = None  # wajib diisi kalau role == "tool"
    name: str | None = None  # nama tool, dipasangkan dengan tool_call_id
    tool_calls: list[dict[str, Any]] | None = None  # dipasang di message role="assistant"


class ToolCallRequest(BaseModel):
    """Satu tool call yang diminta model, sudah di-parse dari response mentah."""

    id: str
    name: str
    arguments: dict[str, Any]


class RawAssistantMessage(BaseModel):
    """
    Hasil satu kali panggilan OpenRouter TANPA memaksa 'content wajib ada' —
    berbeda dari _call_openrouter() yang menganggap content kosong sebagai
    kegagalan. Saat model memilih memanggil tool, content memang boleh
    kosong/None; yang penting salah satu dari content atau tool_calls terisi.
    """

    content: str | None
    tool_calls: list[ToolCallRequest] = []


class ChatCompletionResult(BaseModel):
    """Structured output — dikembalikan ke caller, bukan raw provider response."""
    content: str
    model_used: str
    category: TaskCategory
    used_fallback: bool
    # Additive, default [] -- jalur chat biasa (Milestone 2, use_tools=False)
    # selalu kosong. Diisi hanya oleh jalur tool-calling (chat.py, saat
    # use_tools=True) supaya frontend bisa menampilkan tool apa saja yang
    # BENAR-BENAR dipanggil, bukan menebak dari isi jawaban. Field baru yang
    # additive dengan default aman untuk backward compatibility -- client
    # lama yang belum tahu field ini cukup mengabaikannya.
    tools_used: list[str] = []

    # 'model_used' bentrok dengan reserved prefix Pydantic v2 (model_dump,
    # model_validate, dst). protected_namespaces=() menonaktifkan proteksi
    # itu karena field ini murni data, bukan method.
    model_config = {"protected_namespaces": ()}


async def _post_chat_completion(
    messages: list[ChatMessage],
    model: str,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Helper HTTP murni: kirim request, kembalikan JSON response mentah
    (dict) apa adanya. Semua penanganan status code (timeout, 429, 5xx,
    4xx) terjadi di sini — dipakai bersama oleh _call_openrouter()
    (jalur lama, tanpa tools) dan _call_openrouter_raw() (jalur baru,
    dengan tools), supaya semantik error tetap satu tempat kebenaran.
    """
    url = f"{settings.openrouter_base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        # Header rekomendasi OpenRouter untuk atribusi aplikasi.
        "HTTP-Referer": settings.openrouter_site_url,
        "X-Title": settings.openrouter_app_title,
    }
    payload: dict[str, Any] = {
        "model": model,
        # exclude_none: field tool-calling (tool_call_id, name, tool_calls)
        # yang None tidak boleh ikut terkirim untuk message biasa —
        # sebagian provider menolak field asing bernilai null.
        "messages": [m.model_dump(exclude_none=True) for m in messages],
        "max_tokens": settings.openrouter_max_tokens,
        # Batasi porsi max_tokens yang dipakai untuk reasoning tersembunyi
        # (dokumentasi resmi OpenRouter: reasoning.effort). Tanpa ini,
        # reasoning model (mis. nemotron) bisa menghabiskan sebagian
        # besar max_tokens untuk "berpikir" sebelum menulis jawaban --
        # makin parah saat tool-calling aktif karena konteks yang perlu
        # dirangkum lebih besar. Evidence: Phase 2 Bug #2, kambuh di
        # jalur tool-calling dengan gejala jawaban terpotong 1-2 kata.
        "reasoning": {"effort": settings.openrouter_reasoning_effort},
    }
    if tools:
        payload["tools"] = tools

    try:
        async with httpx.AsyncClient(timeout=settings.openrouter_request_timeout_seconds) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise OpenRouterError(f"Timeout saat menghubungi model '{model}'") from exc
    except httpx.RequestError as exc:
        raise OpenRouterError(f"Request error saat menghubungi model '{model}': {exc}") from exc

    if response.status_code == 429:
        raise OpenRouterError(f"Rate limit tercapai untuk model '{model}'")

    if response.status_code >= 500:
        raise OpenRouterError(
            f"Provider error (HTTP {response.status_code}) untuk model '{model}'"
        )

    if response.status_code >= 400:
        raise OpenRouterError(
            f"Request ditolak (HTTP {response.status_code}) untuk model '{model}': {response.text}"
        )

    try:
        return response.json()
    except ValueError as exc:
        raise OpenRouterError(
            f"Response bukan JSON valid dari model '{model}'"
        ) from exc


async def _call_openrouter(messages: list[ChatMessage], model: str) -> str:
    """
    Melakukan satu kali panggilan ke OpenRouter chat completions endpoint
    TANPA tools — jalur asli Milestone 2, dipertahankan apa adanya.

    Melempar OpenRouterError untuk semua kondisi gagal:
    timeout, HTTP error status, rate limit, atau response malformed.
    Tidak ada silent failure — caller (fallback logic) yang memutuskan
    langkah berikutnya.
    """
    data = await _post_chat_completion(messages, model)

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as exc:
        raise OpenRouterError(
            f"Response malformed dari model '{model}': tidak sesuai struktur yang diharapkan"
        ) from exc

    if not content or not content.strip():
        # Response 200 tapi kosong tetap dianggap gagal — bukan hasil yang valid.
        raise OpenRouterError(f"Response kosong dari model '{model}'")

    return content


async def _call_openrouter_raw(
    messages: list[ChatMessage],
    model: str,
    tools: list[dict[str, Any]] | None = None,
) -> RawAssistantMessage:
    """
    Sama seperti _call_openrouter(), tapi untuk jalur tool-calling
    (app/ai/tool_calling.py): mengembalikan message ASLI dari model,
    termasuk tool_calls kalau model memilih memanggil tool. Content
    kosong TIDAK dianggap gagal di sini — itu kondisi normal saat model
    memilih tool_calls saja tanpa jawaban teks.
    """
    data = await _post_chat_completion(messages, model, tools=tools)

    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, ValueError) as exc:
        raise OpenRouterError(
            f"Response malformed dari model '{model}': tidak sesuai struktur yang diharapkan"
        ) from exc

    content = message.get("content")
    raw_tool_calls = message.get("tool_calls") or []

    tool_calls: list[ToolCallRequest] = []
    for call in raw_tool_calls:
        try:
            import json as _json

            function = call["function"]
            arguments = _json.loads(function.get("arguments") or "{}")
            tool_calls.append(
                ToolCallRequest(id=call["id"], name=function["name"], arguments=arguments)
            )
        except (KeyError, ValueError) as exc:
            raise OpenRouterError(
                f"tool_calls malformed dari model '{model}': {exc}"
            ) from exc

    if not content and not tool_calls:
        # Bukan jawaban teks, bukan juga tool call — tidak ada hasil valid sama sekali.
        raise OpenRouterError(f"Response kosong (tanpa content maupun tool_calls) dari model '{model}'")

    return RawAssistantMessage(content=content, tool_calls=tool_calls)


async def get_completion(
    messages: list[ChatMessage],
    category: TaskCategory,
) -> ChatCompletionResult:
    """
    Entry point utama Model Router + Fallback.

    Flow (sesuai PRD):
        Primary Model -> Gagal? -> Fallback Model -> Gagal? -> Safe Error

    Tidak pernah mengklaim sukses tanpa response valid dari provider.
    """
    primary_model = get_primary_model(category)

    try:
        content = await _call_openrouter(messages, primary_model)
        return ChatCompletionResult(
            content=content,
            model_used=primary_model,
            category=category,
            used_fallback=False,
        )
    except OpenRouterError as primary_error:
        logger.warning(
            "Model primary '%s' gagal untuk kategori '%s': %s. Mencoba fallback.",
            primary_model, category.value, primary_error,
        )

    fallback_model = get_fallback_model(category)

    # Hindari fallback ke model yang sama persis dengan primary yang baru gagal.
    if fallback_model == primary_model:
        raise OpenRouterError(
            f"Model primary '{primary_model}' gagal dan fallback model sama "
            f"dengan primary — tidak ada opsi lain. Konfigurasikan fallback "
            f"model yang berbeda di environment."
        )

    try:
        content = await _call_openrouter(messages, fallback_model)
        return ChatCompletionResult(
            content=content,
            model_used=fallback_model,
            category=category,
            used_fallback=True,
        )
    except OpenRouterError as fallback_error:
        logger.error(
            "Model fallback '%s' juga gagal untuk kategori '%s': %s",
            fallback_model, category.value, fallback_error,
        )
        # Safe error — tidak pernah mengklaim sukses palsu ke caller.
        raise OpenRouterError(
            f"Primary ('{primary_model}') dan fallback ('{fallback_model}') "
            f"model sama-sama gagal untuk kategori '{category.value}'."
        ) from fallback_error