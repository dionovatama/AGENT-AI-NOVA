"""
Tool execution endpoint — boundary autentikasi dan otorisasi eksekusi tool.

Endpoint:
- GET  /tools/list    : Menampilkan daftar tool allowlist (memerlukan JWT terautentikasi)
- POST /tools/execute : Menjalankan tool lewat Tool Manager (memerlukan JWT, otorisasi policy, dan audit)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.models import User
from app.database.session import get_db
from app.security.dependencies import get_current_user
from app.security.permissions import PermissionDeniedError
from app.security.sanitization import sanitize_error_message
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
async def list_tools(current_user: User = Depends(get_current_user)) -> list[str]:
    """Menampilkan semua tool yang terdaftar di allowlist bagi user terautentikasi."""
    return tool_manager.list_tools()


@router.post("/execute", response_model=ToolResult)
async def execute_tool(
    request: ToolRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ToolResult:
    """
    Menjalankan satu tool lewat Tool Manager dengan konteks user terautentikasi.

    Alur:
        1. Validasi JWT -> current_user (HTTP 401 jika invalid/expired/absen)
        2. Authorization Boundary (READ / MODIFY / HIGH_RISK)
        3. Schema Validation & Allowlist Check
        4. Eksekusi dengan Timeout
        5. Pencatatan Audit Persisten (AuditLog)

    Status code:
        401 -> Unauthenticated (token tidak valid/absen)
        404 -> tool tidak ada di allowlist
        422 -> input tidak sesuai schema tool
        403 -> permission/otorisasi ditolak
        504 -> timeout saat eksekusi
        502 -> executor gagal saat dijalankan
    """
    try:
        return await tool_manager.execute(request, user=current_user, db=db)
    except ToolNotFoundError as exc:
        raise HTTPException(status_code=404, detail=sanitize_error_message(str(exc))) from exc
    except ToolValidationError as exc:
        raise HTTPException(status_code=422, detail=sanitize_error_message(str(exc))) from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=sanitize_error_message(str(exc))) from exc
    except ToolTimeoutError as exc:
        raise HTTPException(status_code=504, detail=sanitize_error_message(str(exc))) from exc
    except ToolExecutionError as exc:
        raise HTTPException(status_code=502, detail=sanitize_error_message(str(exc))) from exc
    except ToolManagerError as exc:
        raise HTTPException(status_code=400, detail=sanitize_error_message(str(exc))) from exc