"""
Tool execution endpoint — dipakai untuk menguji Tool Manager secara
end-to-end lewat HTTP (Swagger /docs), sebelum tool calling lewat LLM
terhubung penuh ke sini.
"""

from fastapi import APIRouter, HTTPException

from app.security.permissions import PermissionDeniedError
from app.tools.manager import (
    ToolExecutionError,
    ToolManagerError,
    ToolNotFoundError,
    ToolTimeoutError,
    ToolValidationError,
    tool_manager,
)
from app.tools.schemas import ToolRequest, ToolResult

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("/list")
async def list_tools() -> list[str]:
    """Menampilkan semua tool yang terdaftar di allowlist."""
    return tool_manager.list_tools()


@router.post("/execute", response_model=ToolResult)
async def execute_tool(request: ToolRequest) -> ToolResult:
    """
    Menjalankan satu tool lewat Tool Manager.

    Status code merefleksikan tahap mana yang gagal, sesuai flow
    PRD section 12:
        404 -> tool tidak ada di allowlist
        422 -> input tidak sesuai schema tool
        403 -> permission ditolak (butuh confirmation)
        504 -> timeout saat eksekusi
        502 -> executor gagal saat dijalankan
    """
    try:
        return await tool_manager.execute(request)
    except ToolNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ToolValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ToolTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except ToolExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ToolManagerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc