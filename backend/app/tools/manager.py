"""
Tool Manager — security boundary antara LLM dan sistem (PRD section 12).

Flow:
    LLM -> Tool Request -> Schema Validation -> Authorization ->
    Risk Assessment -> Permission -> Executor -> Result

LLM tidak pernah memanggil executor secara langsung. Semua request
tool WAJIB melalui ToolManager.execute(). Tool yang tidak didaftarkan
lewat ToolManager.register() tidak bisa dipanggil sama sekali —
ini adalah allowlist eksplisit (section 30: Tool Allowlist), bukan
blocklist.
"""

import asyncio
import logging
import time

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database.models import User
from app.security.audit import log_tool_execution, record_audit_event, update_audit_event
from app.security.authorization import AuthorizationError, authorize_tool_execution
from app.security.permissions import PermissionDeniedError, check_permission
from app.security.sanitization import sanitize_error_message, sanitize_metadata
from app.tools.schemas import RiskLevel, ToolDefinition, ToolRequest, ToolResult

logger = logging.getLogger("nova.tools.manager")

# FIX-L: Concurrency limits — mencegah LLM loop abuse.
# Global cap: maks 20 concurrent tool executions di seluruh instance.
# Per-user cap: maks 5 concurrent tool executions per user.
_GLOBAL_SEMAPHORE = asyncio.Semaphore(20)
# Keyed by str(user_id). Dibuat lazily di execute().
_USER_SEMAPHORES: dict[str, asyncio.Semaphore] = {}
_USER_SEMAPHORE_LOCK = asyncio.Lock()
_USER_SEMAPHORE_MAX = 5
_SEMAPHORE_ACQUIRE_TIMEOUT = 5.0  # detik sebelum dianggap concurrency limit reached


class ToolManagerError(Exception):
    """Base error untuk semua kegagalan di Tool Manager."""


class ToolNotFoundError(ToolManagerError):
    """Tool tidak terdaftar di allowlist."""


class ToolValidationError(ToolManagerError):
    """Input tidak sesuai schema tool."""


class ToolTimeoutError(ToolManagerError):
    """Eksekusi tool melebihi timeout yang ditentukan."""


class ToolExecutionError(ToolManagerError):
    """Executor melempar exception saat dijalankan."""


class ToolManager:
    """
    Registry + orkestrator eksekusi tool. Satu instance dipakai untuk
    seluruh lifetime aplikasi (tool-tool didaftarkan sekali saat startup).
    """

    def __init__(self) -> None:
        self._registry: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """Mendaftarkan tool ke allowlist."""
        if tool.name in self._registry:
            raise ValueError(f"Tool '{tool.name}' sudah terdaftar.")
        self._registry[tool.name] = tool
        logger.info(
            "Tool terdaftar: %s (permission=%s, risk=%s)",
            tool.name, tool.permission_level.value, tool.risk_level.value,
        )

    def list_tools(self) -> list[str]:
        return list(self._registry.keys())

    def get_tool(self, name: str) -> ToolDefinition | None:
        """Lookup read-only satu ToolDefinition, atau None kalau tidak terdaftar.

        Dipakai oleh caller yang butuh metadata tool (mis. input_model
        untuk membangun function-calling schema di app/ai/tool_calling.py)
        tanpa perlu mengakses _registry secara langsung.
        """
        return self._registry.get(name)

    async def _get_user_semaphore(self, user_key: str) -> asyncio.Semaphore:
        """Lazily create a per-user semaphore (thread-safe via asyncio Lock)."""
        if user_key not in _USER_SEMAPHORES:
            async with _USER_SEMAPHORE_LOCK:
                if user_key not in _USER_SEMAPHORES:
                    _USER_SEMAPHORES[user_key] = asyncio.Semaphore(_USER_SEMAPHORE_MAX)
        return _USER_SEMAPHORES[user_key]

    async def execute(
        self,
        request: ToolRequest,
        user: User | None = None,
        db: Session | None = None,
    ) -> ToolResult:
        start = time.perf_counter()

        # 1. Allowlist check.
        tool = self._registry.get(request.tool_name)
        if tool is None:
            raise ToolNotFoundError(
                f"Tool '{request.tool_name}' tidak dikenal atau tidak "
                f"ada di allowlist."
            )

        # 2. Schema Validation.
        try:
            validated_input = tool.input_model(**request.arguments)
        except ValidationError as exc:
            raise ToolValidationError(
                f"Input tidak valid untuk tool '{tool.name}': {exc}"
            ) from exc

        # 3. Risk Assessment — untuk skeleton ini sebatas logging;
        #    keputusan boleh/tidak tetap di tahap Authorization & Permission (langkah 4).
        if tool.risk_level == RiskLevel.HIGH:
            logger.warning("Tool HIGH RISK dipanggil: %s", tool.name)

        # 4. Authorization Boundary — identitas JWT wajib, backend yang memutuskan bukan LLM.
        try:
            authorize_tool_execution(
                user=user,
                tool_name=tool.name,
                permission=tool.permission_level,
                confirmed=request.confirmed,
                context={"tool": tool, "request": request},
            )
        except (AuthorizationError, PermissionDeniedError) as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            record_audit_event(
                action="tool.execute",
                result_status="DENIED",
                user_id=getattr(user, "id", None),
                tool_name=tool.name,
                permission=tool.permission_level.value,
                risk_level=tool.risk_level.value,
                request_metadata=request.arguments,
                error_message=str(exc),
                duration_ms=duration_ms,
                db=db,
            )
            self._log_failure(tool, request, str(exc), start)
            raise

        # FIX-L: Concurrency enforcement.
        user_key = str(getattr(user, "id", "anonymous"))
        user_sem = await self._get_user_semaphore(user_key)

        try:
            await asyncio.wait_for(user_sem.acquire(), timeout=_SEMAPHORE_ACQUIRE_TIMEOUT)
        except asyncio.TimeoutError:
            raise ToolExecutionError(
                "Terlalu banyak request bersamaan dari pengguna ini. Coba lagi sebentar."
            )

        try:
            await asyncio.wait_for(_GLOBAL_SEMAPHORE.acquire(), timeout=_SEMAPHORE_ACQUIRE_TIMEOUT)
        except asyncio.TimeoutError:
            user_sem.release()
            raise ToolExecutionError(
                "Sistem sedang sibuk. Terlalu banyak tool execution bersamaan secara global. "
                "Coba lagi sebentar."
            )

        # 5. Executor — dijalankan dengan timeout, tidak pernah tanpa batas.
        try:
            # FIX-M: Audit event EXECUTING — catat saat executor benar-benar mulai.
            # BUG (ditemukan Tuan lewat log, konfirmasi 2025-...): baris ini
            # cuma pernah INSERT, tidak pernah di-UPDATE lagi setelah
            # eksekusi selesai -- setiap tool call selalu menyisakan satu
            # baris EXECUTING yang nyangkut selamanya, terpisah dari baris
            # status akhir (SUCCESS/FAILED/TIMEOUT). audit_id di-capture di
            # sini supaya TIMEOUT/FAILED/SUCCESS di bawah bisa UPDATE baris
            # yang SAMA (lewat update_audit_event) alih-alih INSERT baris
            # baru -- lifecycle satu baris yang bertransisi, sesuai
            # docstring app/security/audit.py, bukan satu baris per tahap.
            # DENIED sengaja TETAP INSERT (lihat langkah 4 di atas): itu
            # terjadi di Authorization/Permission, SEBELUM baris EXECUTING
            # ini pernah ditulis, jadi tidak ada baris untuk di-update.
            executing_entry = record_audit_event(
                action="tool.execute",
                result_status="EXECUTING",
                user_id=getattr(user, "id", None),
                tool_name=tool.name,
                permission=tool.permission_level.value,
                risk_level=tool.risk_level.value,
                request_metadata=request.arguments,
                db=db,
            )
            # getattr, bukan akses langsung .id -- kalau record_audit_event
            # gagal persist (mis. DB down saat itu), audit_entry tetap
            # dikembalikan (lihat audit.py) tapi .id bisa None/belum ter-
            # assign. update_audit_event() sendiri sudah menangani
            # audit_id=None dengan diam-diam no-op (lihat docstring-nya),
            # jadi ini tetap aman tanpa exception baru.
            audit_id = getattr(executing_entry, "id", None)
            output = await asyncio.wait_for(
                tool.executor(validated_input), timeout=tool.timeout_seconds
            )
        except asyncio.TimeoutError as exc:
            error = f"Timeout setelah {tool.timeout_seconds}s"
            duration_ms = (time.perf_counter() - start) * 1000
            # UPDATE baris EXECUTING yang sama, bukan INSERT baris baru.
            update_audit_event(
                audit_id=audit_id,
                result_status="TIMEOUT",
                error_message=error,
                duration_ms=duration_ms,
                db=db,
            )
            self._log_failure(tool, request, error, start)
            raise ToolTimeoutError(error) from exc
        except asyncio.CancelledError:
            # BUG YANG DITEMUKAN: asyncio.CancelledError adalah subclass
            # BaseException (sejak Python 3.8), BUKAN Exception -- jadi
            # "except Exception" di bawah TIDAK PERNAH menangkapnya. Tanpa
            # branch ini, request yang dibatalkan di tengah jalan (client
            # disconnect, atau server di-restart --reload saat request
            # masih in-flight) membuat baris EXECUTING nyangkut selamanya,
            # tidak pernah ter-update ke status manapun.
            #
            # WAJIB raise ulang (bukan ditelan) -- menelan CancelledError
            # merusak semantik cancellation asyncio, bisa bikin task lain
            # yang menunggu cancellation ini jadi hang.
            duration_ms = (time.perf_counter() - start) * 1000
            update_audit_event(
                audit_id=audit_id,
                result_status="FAILED",
                error_message="Request dibatalkan sebelum selesai (client disconnect atau server restart di tengah eksekusi).",
                duration_ms=duration_ms,
                db=db,
            )
            raise
        except Exception as exc:  # noqa: BLE001 — executor pihak ketiga, semua exception ditangkap
            # FIX-D: Sanitasi pesan error sebelum diekspos ke caller/LLM.
            # Internal detail (raw exc) hanya dicatat di server-side logger.
            safe_error = sanitize_error_message(str(exc)) or "Executor error."
            logger.error(
                "Tool '%s' executor error (internal): %s",
                tool.name,
                sanitize_error_message(str(exc)),
            )
            duration_ms = (time.perf_counter() - start) * 1000
            # UPDATE baris EXECUTING yang sama, bukan INSERT baris baru.
            update_audit_event(
                audit_id=audit_id,
                result_status="FAILED",
                error_message=safe_error,
                duration_ms=duration_ms,
                db=db,
            )
            self._log_failure(tool, request, safe_error, start)
            raise ToolExecutionError(safe_error) from exc
        finally:
            # FIX-L: Always release both semaphores.
            user_sem.release()
            _GLOBAL_SEMAPHORE.release()

        # 6. Result — sukses hanya jika executor benar-benar selesai normal.
        duration_ms = (time.perf_counter() - start) * 1000

        # FIX-E: Sanitasi output sebelum disimpan ke ToolResult dan dikirim ke LLM.
        # Kunci jaringan aman (ip, subnet, interface, routes) dipertahankan;
        # hanya kunci sensitif (password, token, key, dll) yang di-redact.
        raw_output = output.model_dump()
        sanitized_output = sanitize_metadata(raw_output)

        result = ToolResult(
            success=True,
            tool_name=tool.name,
            permission_level=tool.permission_level,
            risk_level=tool.risk_level,
            output=sanitized_output,
            duration_ms=duration_ms,
        )
        # UPDATE baris EXECUTING yang sama, bukan INSERT baris baru.
        update_audit_event(
            audit_id=audit_id,
            result_status="SUCCESS",
            duration_ms=duration_ms,
            db=db,
        )
        log_tool_execution(tool.name, tool.logging_policy, request.arguments, result)
        return result

    def _log_failure(
        self, tool: ToolDefinition, request: ToolRequest, error: str, start: float
    ) -> None:
        duration_ms = (time.perf_counter() - start) * 1000
        result = ToolResult(
            success=False,
            tool_name=tool.name,
            permission_level=tool.permission_level,
            risk_level=tool.risk_level,
            error=error,
            duration_ms=duration_ms,
        )
        log_tool_execution(tool.name, tool.logging_policy, request.arguments, result)


# Singleton instance — tool-tool didaftarkan ke sini saat startup aplikasi.
tool_manager = ToolManager()