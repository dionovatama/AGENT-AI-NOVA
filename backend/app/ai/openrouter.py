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

import httpx
from pydantic import BaseModel

from app.config import settings
from app.ai.model_router import TaskCategory, get_primary_model, get_fallback_model

logger = logging.getLogger("nova.ai.openrouter")


class OpenRouterError(Exception):
    """Base error untuk semua kegagalan komunikasi dengan OpenRouter."""


class ChatMessage(BaseModel):
    role: str  # "system" | "user" | "assistant"
    content: str


class ChatCompletionResult(BaseModel):
    """Structured output — dikembalikan ke caller, bukan raw provider response."""
    content: str
    model_used: str
    category: TaskCategory
    used_fallback: bool

    # 'model_used' bentrok dengan reserved prefix Pydantic v2 (model_dump,
    # model_validate, dst). protected_namespaces=() menonaktifkan proteksi
    # itu karena field ini murni data, bukan method.
    model_config = {"protected_namespaces": ()}


async def _call_openrouter(messages: list[ChatMessage], model: str) -> str:
    """
    Melakukan satu kali panggilan ke OpenRouter chat completions endpoint.

    Melempar OpenRouterError untuk semua kondisi gagal:
    timeout, HTTP error status, rate limit, atau response malformed.
    Tidak ada silent failure — caller (fallback logic) yang memutuskan
    langkah berikutnya.
    """
    url = f"{settings.openrouter_base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        # Header rekomendasi OpenRouter untuk atribusi aplikasi.
        "HTTP-Referer": settings.openrouter_site_url,
        "X-Title": settings.openrouter_app_title,
    }
    payload = {
        "model": model,
        "messages": [m.model_dump() for m in messages],
        "max_tokens": settings.openrouter_max_tokens,
    }

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
        data = response.json()
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as exc:
        raise OpenRouterError(
            f"Response malformed dari model '{model}': tidak sesuai struktur yang diharapkan"
        ) from exc

    if not content or not content.strip():
        # Response 200 tapi kosong tetap dianggap gagal — bukan hasil yang valid.
        raise OpenRouterError(f"Response kosong dari model '{model}'")

    return content


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
