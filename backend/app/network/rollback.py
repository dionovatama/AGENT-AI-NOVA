"""
Rollback Engine for N.O.V.A Configuration Engine.

Menangani pembalikan (rollback) operasi konfigurasi secara terbalik (LIFO),
menggunakan object_id RouterOS internal atau snapshot state pembanding,
serta memverifikasi hasil rollback dari state nyata perangkat (PRD section 22).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.network.adapters.base import NetworkDeviceAdapter
from app.network.models import NetworkOperation
from app.security.audit import record_audit_event
from app.security.authorization import ApprovalContext
from app.tools.manager import tool_manager
from app.tools.schemas import ToolRequest

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from app.database.models import Configuration, Device, User

logger = logging.getLogger("nova.network.rollback")


class RollbackError(Exception):
    """Dilempar saat eksekusi atau verifikasi rollback gagal."""


async def execute_lifo_rollback(
    applied_steps: list[tuple[NetworkOperation, str]],  # (operation, object_id)
    device: Device,
    user: User,
    adapter: NetworkDeviceAdapter,
    db: Session | None = None,
    approval_ctx: ApprovalContext | None = None,
    config: Configuration | None = None,
) -> bool:
    """
    Mengeksekusi pembatalan operasi secara LIFO (Last-In, First-Out).
    
    Langkah:
    1. Membalik urutan operasi yang telah berhasil diterapkan.
    2. Menghapus objek menggunakan tool penulis via ToolManager.execute(is_internal=True).
    3. Memverifikasi ke state nyata bahwa objek benar-benar telah hilang.
    4. Jika verifikasi gagal -> lempar RollbackError (menuju status ROLLBACK_FAILED).
    """
    logger.warning(
        "MEMULAI ROLLBACK OTOMATIS (LIFO): %d langkah untuk device %s",
        len(applied_steps),
        device.id,
    )

    rollback_tool_name = f"{device.platform}.config_apply"
    failed_steps: list[str] = []

    # Balik urutan: eksekusi dari yang paling terakhir dibuat
    for op, obj_id in reversed(applied_steps):
        logger.info("Rollback step: menghapus objek %s untuk operasi %s", obj_id, op.type.value)
        try:
            req = ToolRequest(
                tool_name=rollback_tool_name,
                arguments={
                    "operation": op.model_dump(mode="json"),
                    "action": "remove",
                    "object_id": obj_id,
                    "plan_hash": config.plan_hash if config else "",
                    "state_fingerprint": config.state_fingerprint if config else "",
                },
                confirmed=True,
                device_id=device.id,
            )
            result = await tool_manager.execute(
                request=req,
                user=user,
                db=db,
                is_internal=True,
                approval_ctx=approval_ctx,
            )
            if not result.success:
                failed_steps.append(f"Objek {obj_id}: {result.error}")
        except Exception as exc:
            failed_steps.append(f"Objek {obj_id}: {exc}")

    # Verifikasi state nyata paska rollback
    try:
        live_state = await adapter.get_device_state(device)
        unreverted_items: list[str] = []

        for op, obj_id in applied_steps:
            # Pastikan objek yang di-apply sudah tidak ada lagi di state nyata
            is_still_present = await adapter.verify_operation(op, device)
            if is_still_present:
                unreverted_items.append(f"Operasi {op.type.value} ({obj_id}) masih ditemukan di perangkat.")

        if failed_steps or unreverted_items:
            err_msg = f"ROLLBACK GAGAL! Gagal remove: {failed_steps}. Masih tertinggal: {unreverted_items}"
            logger.critical(err_msg)
            record_audit_event(
                action="configuration.rollback",
                result_status="FAILED",
                verification_status="ROLLBACK_FAILED",
                user_id=user.id,
                device_id=device.id,
                error_message=err_msg,
                db=db,
            )
            raise RollbackError(err_msg)

    except RollbackError:
        raise
    except Exception as exc:
        err_msg = f"Gagal membaca state perangkat saat verifikasi rollback: {exc}"
        logger.critical(err_msg)
        record_audit_event(
            action="configuration.rollback",
            result_status="FAILED",
            verification_status="ROLLBACK_FAILED",
            user_id=user.id,
            device_id=device.id,
            error_message=err_msg,
            db=db,
        )
        raise RollbackError(err_msg) from exc

    logger.info("Rollback berhasil dan terverifikasi penuh untuk device %s", device.id)
    record_audit_event(
        action="configuration.rollback",
        result_status="SUCCESS",
        verification_status="ROLLED_BACK",
        user_id=user.id,
        device_id=device.id,
        db=db,
    )
    return True
