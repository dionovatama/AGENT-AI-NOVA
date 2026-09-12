"""
Audit Logging — mencatat setiap tool execution sesuai PRD section 32.

Flow yang idealnya dicatat: User -> Request -> Intent -> Tool Request ->
Authorization -> Permission -> Execution -> Result -> Verification ->
Response.

CATATAN SKELETON:
Untuk saat ini logging masih ke logger biasa (belum ke tabel
audit_logs di PostgreSQL — itu menyusul saat Phase 3 masuk ke tahap
integrasi database). Prinsip 'sensitive secrets tidak boleh dicatat'
tetap dipegang dari awal lewat LoggingPolicy per tool.
"""

import logging

from app.tools.schemas import LoggingPolicy, ToolResult

logger = logging.getLogger("nova.audit")


def log_tool_execution(
    tool_name: str,
    logging_policy: LoggingPolicy,
    arguments: dict,
    result: ToolResult,
) -> None:
    """Mencatat hasil eksekusi tool sesuai kebijakan logging tool tsb."""

    if logging_policy == LoggingPolicy.MINIMAL:
        logger.info("TOOL_EXEC name=%s success=%s", tool_name, result.success)
        return

    if logging_policy == LoggingPolicy.RESULT_ONLY:
        logger.info(
            "TOOL_EXEC name=%s success=%s duration_ms=%.1f output=%s error=%s",
            tool_name, result.success, result.duration_ms,
            result.output, result.error,
        )
        return

    # ALWAYS — termasuk argumen mentah. Tool yang argumennya berpotensi
    # mengandung credential WAJIB memakai device_id reference (section 29),
    # bukan LoggingPolicy.ALWAYS dengan credential mentah di dalamnya.
    logger.info(
        "TOOL_EXEC name=%s success=%s duration_ms=%.1f arguments=%s "
        "output=%s error=%s",
        tool_name, result.success, result.duration_ms, arguments,
        result.output, result.error,
    )