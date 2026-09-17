"""
Audit Logging — mencatat setiap tool execution & lifecycle tindakan sistem (PRD section 32).

Flow lifecycle:
REQUESTED / AUTHORIZED / DENIED -> EXECUTING -> SUCCESS / FAILED / TIMEOUT

Keamanan:
- Zero Secret Exposure: password, API keys, private keys, JWT tidak pernah disimpan ke DB.
- Request metadata disanitasi sebelum persistensi melalui app.security.sanitization.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.database.models import AuditLog
from app.database.session import SessionLocal
from app.security.sanitization import sanitize_error_message, sanitize_metadata
from app.tools.schemas import LoggingPolicy, ToolResult

logger = logging.getLogger("nova.audit")


def record_audit_event(
    action: str,
    result_status: str,
    user_id: uuid.UUID | str | None = None,
    device_id: uuid.UUID | str | None = None,
    tool_name: str | None = None,
    permission: str | None = None,
    risk_level: str | None = None,
    request_metadata: dict[str, Any] | None = None,
    verification_status: str | None = None,
    error_message: str | None = None,
    duration_ms: float | None = None,
    db: Session | None = None,
) -> AuditLog:
    """
    Menyimpan catatan audit ke database dan mencatat ke application logger.
    Sanitasi otomatis dijalankan terhadap metadata dan pesan error sebelum persistensi.
    """
    # 1. Parsing UUIDs
    parsed_user_id: uuid.UUID | None = None
    if user_id is not None:
        try:
            parsed_user_id = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
        except (ValueError, TypeError):
            parsed_user_id = None

    parsed_device_id: uuid.UUID | None = None
    if device_id is not None:
        try:
            parsed_device_id = device_id if isinstance(device_id, uuid.UUID) else uuid.UUID(str(device_id))
        except (ValueError, TypeError):
            parsed_device_id = None

    # 2. Zero Secret Exposure — Sanitasi metadata dan error
    sanitized_metadata = sanitize_metadata(request_metadata) if request_metadata is not None else None
    sanitized_error = sanitize_error_message(error_message) if error_message is not None else None

    # 3. Buat instance model AuditLog
    audit_entry = AuditLog(
        user_id=parsed_user_id,
        device_id=parsed_device_id,
        tool_name=tool_name,
        permission=str(permission) if permission else None,
        risk_level=str(risk_level) if risk_level else None,
        action=action,
        request_metadata=sanitized_metadata,
        result_status=result_status,
        verification_status=verification_status,
        error_message=sanitized_error,
        duration_ms=duration_ms,
    )

    # 4. Simpan ke database secara persisten
    should_close_db = False
    active_db = db
    if active_db is None:
        try:
            active_db = SessionLocal()
            should_close_db = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gagal membuat DB session untuk audit log: %s", exc)
            active_db = None

    if active_db is not None:
        try:
            active_db.add(audit_entry)
            active_db.commit()
            active_db.refresh(audit_entry)
        except Exception as exc:  # noqa: BLE001
            active_db.rollback()
            logger.error("Gagal menyimpan audit log ke database: %s", exc)
        finally:
            if should_close_db:
                active_db.close()

    # 5. Output ke console/file logger
    logger.info(
        "AUDIT_EVENT action=%s status=%s user=%s tool=%s duration_ms=%s error=%s",
        action,
        result_status,
        parsed_user_id,
        tool_name,
        duration_ms,
        sanitized_error,
    )

    return audit_entry


def log_tool_execution(
    tool_name: str,
    logging_policy: LoggingPolicy,
    arguments: dict,
    result: ToolResult,
) -> None:
    """Mencatat hasil eksekusi tool sesuai kebijakan logging tool tsb (legacy/compat logger)."""
    sanitized_args = sanitize_metadata(arguments)
    sanitized_error = sanitize_error_message(result.error)

    if logging_policy == LoggingPolicy.MINIMAL:
        logger.info("TOOL_EXEC name=%s success=%s", tool_name, result.success)
        return

    if logging_policy == LoggingPolicy.RESULT_ONLY:
        logger.info(
            "TOOL_EXEC name=%s success=%s duration_ms=%.1f output=%s error=%s",
            tool_name,
            result.success,
            result.duration_ms,
            result.output,
            sanitized_error,
        )
        return

    logger.info(
        "TOOL_EXEC name=%s success=%s duration_ms=%.1f arguments=%s output=%s error=%s",
        tool_name,
        result.success,
        result.duration_ms,
        sanitized_args,
        result.output,
        sanitized_error,
    )