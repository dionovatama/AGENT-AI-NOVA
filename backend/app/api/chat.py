"""
Chat endpoint — Milestone 2.

Ini BUKAN endpoint tool-calling. Endpoint ini hanya membuktikan bahwa
AI Gateway (OpenRouter) + Model Router + Fallback berfungsi end-to-end.

Tool Manager, Tool Calling, dan eksekusi terhadap sistem nyata BELUM ada
di sini — itu scope Milestone 3 (Tool Manager) dan seterusnya, sesuai
roadmap dan Core Principle: LLM adalah untrusted decision maker.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.database.models import User
from app.security.dependencies import get_current_user
from app.ai.model_router import TaskCategory
from app.ai.openrouter import ChatMessage, ChatCompletionResult, OpenRouterError, get_completion
from app.ai.tool_calling import ChatWithToolsResult, get_completion_with_tools

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    category: TaskCategory = TaskCategory.GENERAL_CHAT
    # Default False: perilaku endpoint ini TIDAK berubah dari Milestone 2
    # kecuali user secara eksplisit minta tool-calling diaktifkan. Saat
    # True, hanya tool READ yang ada di allowlist kategori (lihat
    # app/ai/tool_calling.py) yang bisa dipanggil model — mis. web.search
    # untuk category=general_chat.
    use_tools: bool = False


@router.post("/completions", response_model=ChatCompletionResult)
async def chat_completions(
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Kirim satu pesan ke NOVA AI Gateway.

    Membutuhkan Bearer token (dari /auth/login). Endpoint ini murni
    reasoning — tidak ada tool execution, tidak ada akses sistem —
    KECUALI payload.use_tools=True (lihat docstring ChatRequest.use_tools).
    """
    if payload.use_tools:
        try:
            tools_result = await get_completion_with_tools(payload.message, payload.category)
        except OpenRouterError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"AI Gateway gagal memproses request: {exc}",
            )
        # Dipetakan ke ChatCompletionResult (kontrak response lama) --
        # sekarang termasuk tools_used (field additive) supaya frontend
        # bisa menampilkan tool apa saja yang BENAR-BENAR dipanggil,
        # bukan menebak dari isi jawaban model.
        return ChatCompletionResult(
            content=tools_result.content,
            model_used=tools_result.model_used,
            category=tools_result.category,
            used_fallback=tools_result.used_fallback,
            tools_used=tools_result.tools_used,
        )

    messages = [ChatMessage(role="user", content=payload.message)]

    try:
        result = await get_completion(messages, payload.category)
    except OpenRouterError as exc:
        # Safe error — jangan pernah mengklaim sukses jika gagal.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI Gateway gagal memproses request: {exc}",
        )

    return result