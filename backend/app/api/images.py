"""
Image generation endpoint — Cloudflare Workers AI (FLUX).

Prinsip (sesuai PRD):
- Token Cloudflare hanya hidup di backend (.env). Tidak pernah dikirim
  ke frontend, tidak masuk log, tidak masuk response.
- Endpoint wajib login (JWT) — jatah gratis Cloudflare dipakai bersama,
  jadi tidak boleh terbuka untuk publik.
- Kegagalan dikembalikan sebagai error eksplisit berlabel
  ([AUTH]/[QUOTA]/[UPSTREAM]/[TIMEOUT]/[CONFIG]), tidak pernah
  mengklaim sukses tanpa gambar valid dari provider.
"""

import logging
import time
from collections import defaultdict, deque

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.config import settings
from app.database.models import User
from app.security.dependencies import get_current_user

logger = logging.getLogger("nova.api.images")

router = APIRouter(prefix="/images", tags=["images"])

MAX_PROMPT_CHARS = 2000
REQUEST_TIMEOUT_SECONDS = 60.0

# Rate limit sederhana in-memory per user: melindungi jatah gratis
# (10.000 neurons/hari) dari satu user yang menekan tombol berulang.
# Catatan: reset saat backend restart dan tidak dibagi antar-proses —
# cukup untuk lab, bukan pengganti rate limiter production.
RATE_LIMIT_MAX_REQUESTS = 10
RATE_LIMIT_WINDOW_SECONDS = 60.0
_recent_requests: dict[str, deque[float]] = defaultdict(deque)


class ImageGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)


class ImageGenerateResponse(BaseModel):
    image_data_url: str
    model: str

    # 'model' aman, tapi konsisten dengan pola di ChatCompletionResult.
    model_config = {"protected_namespaces": ()}


def _check_rate_limit(user_id: str) -> None:
    now = time.monotonic()
    window = _recent_requests[user_id]
    while window and now - window[0] > RATE_LIMIT_WINDOW_SECONDS:
        window.popleft()
    if len(window) >= RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="[RATE_LIMIT] Terlalu banyak permintaan gambar. Coba lagi sebentar lagi.",
        )
    window.append(now)


def _sniff_mime(b64: str) -> str:
    # Base64 dari header file: PNG -> "iVBOR", JPEG -> "/9j/", WEBP -> "UklGR".
    if b64.startswith("iVBOR"):
        return "image/png"
    if b64.startswith("UklGR"):
        return "image/webp"
    return "image/jpeg"


def _extract_cf_error(body: object) -> str:
    """Ambil pesan error Cloudflare tanpa pernah menyertakan header/token."""
    if isinstance(body, dict):
        errors = body.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict):
                code = first.get("code")
                msg = first.get("message", "")
                return f"{msg} (code {code})" if code is not None else str(msg)
    return "tidak ada detail error dari provider"


def _classify_http_error(status_code: int, detail: str) -> tuple[int, str]:
    low = detail.lower()
    if status_code in (401, 403):
        return 502, f"[AUTH] Cloudflare menolak kredensial/izin token: {detail}"
    if status_code == 429 or "allocation" in low or "neuron" in low or "quota" in low:
        return 429, f"[QUOTA] Jatah Workers AI habis atau terkena rate limit: {detail}"
    if status_code == 404:
        return 502, f"[CONFIG] Endpoint/model tidak ditemukan. Periksa CLOUDFLARE_ACCOUNT_ID dan IMAGE_MODEL: {detail}"
    return 502, f"[UPSTREAM] Cloudflare error (HTTP {status_code}): {detail}"


@router.post("/generate", response_model=ImageGenerateResponse)
async def generate_image(
    payload: ImageGenerateRequest,
    current_user: User = Depends(get_current_user),
) -> ImageGenerateResponse:
    account_id = settings.cloudflare_account_id
    api_token = settings.cloudflare_api_token
    if not account_id or not api_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="[CONFIG] Image generation belum dikonfigurasi. Isi CLOUDFLARE_ACCOUNT_ID dan CLOUDFLARE_API_TOKEN di backend/.env lalu restart backend.",
        )

    prompt = payload.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="Prompt tidak boleh kosong.")

    _check_rate_limit(str(current_user.id))

    model = settings.image_model
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
    started = time.perf_counter()

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {api_token}"},
                json={"prompt": prompt},
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"[TIMEOUT] Cloudflare tidak merespons dalam {int(REQUEST_TIMEOUT_SECONDS)} detik.",
        ) from exc
    except httpx.RequestError as exc:
        # Pesan exception httpx tidak memuat header Authorization.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"[UPSTREAM] Gagal menghubungi Cloudflare: {type(exc).__name__}",
        ) from exc

    duration_ms = round((time.perf_counter() - started) * 1000)

    try:
        body = response.json()
    except ValueError:
        body = None

    if response.status_code >= 400 or not (isinstance(body, dict) and body.get("success")):
        detail = _extract_cf_error(body)
        http_status, message = _classify_http_error(response.status_code, detail)
        logger.warning(
            "IMAGE_GEN gagal user=%s model=%s http=%s duration_ms=%s detail=%s",
            current_user.id, model, response.status_code, duration_ms, detail,
        )
        raise HTTPException(status_code=http_status, detail=message)

    image_b64 = (body.get("result") or {}).get("image") if isinstance(body.get("result"), dict) else None
    if not isinstance(image_b64, str) or not image_b64:
        logger.warning(
            "IMAGE_GEN respons tanpa gambar user=%s model=%s duration_ms=%s",
            current_user.id, model, duration_ms,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="[UPSTREAM] Cloudflare membalas sukses tetapi tidak menyertakan gambar.",
        )

    # Prompt sengaja tidak dicatat penuh (bisa berisi data sensitif user).
    logger.info(
        "IMAGE_GEN sukses user=%s model=%s duration_ms=%s prompt_chars=%s",
        current_user.id, model, duration_ms, len(prompt),
    )

    return ImageGenerateResponse(
        image_data_url=f"data:{_sniff_mime(image_b64)};base64,{image_b64}",
        model=model,
    )