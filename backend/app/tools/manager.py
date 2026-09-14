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

from app.security.audit import log_tool_execution
from app.security.permissions import PermissionDeniedError, check_permission
from app.tools.schemas import RiskLevel, ToolDefinition, ToolRequest, ToolResult

logger = logging.getLogger("nova.tools.manager")


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

    async def execute(self, request: ToolRequest) -> ToolResult:
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
        #    keputusan boleh/tidak tetap di tahap Permission (langkah 4).
        if tool.risk_level == RiskLevel.HIGH:
            logger.warning("Tool HIGH RISK dipanggil: %s", tool.name)

        # 4. Permission — backend yang memutuskan, bukan LLM.
        try:
            check_permission(tool.permission_level, request.confirmed)
        except PermissionDeniedError as exc:
            self._log_failure(tool, request, str(exc), start)
            raise

        # 5. Executor — dijalankan dengan timeout, tidak pernah tanpa batas.
        try:
            output = await asyncio.wait_for(
                tool.executor(validated_input), timeout=tool.timeout_seconds
            )
        except asyncio.TimeoutError as exc:
            error = f"Timeout setelah {tool.timeout_seconds}s"
            self._log_failure(tool, request, error, start)
            raise ToolTimeoutError(error) from exc
        except Exception as exc:  # noqa: BLE001 — executor pihak ketiga, semua exception ditangkap
            error = f"Executor error: {exc}"
            self._log_failure(tool, request, error, start)
            raise ToolExecutionError(error) from exc

        # 6. Result — sukses hanya jika executor benar-benar selesai normal.
        duration_ms = (time.perf_counter() - start) * 1000
        result = ToolResult(
            success=True,
            tool_name=tool.name,
            permission_level=tool.permission_level,
            risk_level=tool.risk_level,
            output=output.model_dump(),
            duration_ms=duration_ms,
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