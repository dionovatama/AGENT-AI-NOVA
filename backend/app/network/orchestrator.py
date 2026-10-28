"""
Orchestrator for N.O.V.A Configuration Engine.

Mengorkestrasi seluruh siklus hidup konfigurasi:
Plan -> Validate -> Preview -> Approve -> Apply -> Verify -> Rollback.
Menegakkan State Machine ketat, concurrency apply lock per-device,
guard lab, kill-switch, deteksi state drift, dan pencatatan audit
(PRD section 19, 20, 22, 33, 39).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import Configuration, ConfigurationVersion, Device, User
from app.network.adapters.base import NetworkDeviceAdapter
from app.network.adapters.fake import FakeNetworkAdapter
from app.network.adapters.mikrotik import MikrotikNetworkAdapter
from app.network.backup import save_state_snapshot
from app.network.device_context import build_device_context
from app.network.models import ChangeSet, NetworkOperation
from app.network.preview import calculate_state_fingerprint
from app.network.rollback import RollbackError, execute_lifo_rollback
from app.security.audit import record_audit_event
from app.security.authorization import ApprovalContext
from app.tools.manager import tool_manager
from app.tools.schemas import ToolRequest

logger = logging.getLogger("nova.network.orchestrator")

# Concurrency apply lock per device
# CATATAN ARSITEKTUR & BATASAN:
# asyncio.Lock ini berlaku untuk satu proses backend (in-memory per-process).
# Jika backend dijalankan dengan multi-worker (mis. gunicorn -w 4 atau uvicorn cluster),
# lock ini perlu ditingkatkan menjadi distributed lock (mis. Postgres Advisory Lock
# atau Redis lock). Untuk scope MVP, asyncio.Lock dikombinasikan dengan check kolom
# status == 'APPLYING' di PostgreSQL untuk mencegah race condition lintas worker.
_DEVICE_APPLY_LOCKS: dict[str, asyncio.Lock] = {}
_DEVICE_LOCKS_GUARD = asyncio.Lock()
_APPLY_LOCK_TIMEOUT_SECONDS = 5.0


class OrchestratorError(Exception):
    """Base error untuk kegagalan alur orkestrasi konfigurasi."""


class StateConflictError(OrchestratorError):
    """Dilempar saat transisi status ilegal atau ada apply lain yang sedang berjalan."""


class DriftDetectedError(OrchestratorError):
    """Dilempar saat state perangkat telah berubah sejak approval diberikan."""


class VerificationFailedError(OrchestratorError):
    """Dilempar saat verifikasi state nyata perangkat paska-apply tidak cocok."""


async def _get_device_lock(device_id: str) -> asyncio.Lock:
    """Mengambil atau membuat asyncio.Lock untuk device tertentu secara thread-safe."""
    if device_id not in _DEVICE_APPLY_LOCKS:
        async with _DEVICE_LOCKS_GUARD:
            if device_id not in _DEVICE_APPLY_LOCKS:
                _DEVICE_APPLY_LOCKS[device_id] = asyncio.Lock()
    return _DEVICE_APPLY_LOCKS[device_id]


def _resolve_adapter(device: Device) -> NetworkDeviceAdapter:
    """Mengembalikan adapter yang sesuai dengan platform dan metadata device."""
    from app.api.configurations import _CUSTOM_ADAPTER
    if _CUSTOM_ADAPTER is not None:
        return _CUSTOM_ADAPTER

    metadata = device.device_metadata or {}
    if metadata.get("mock") is True:
        return FakeNetworkAdapter()

    if device.platform == "mikrotik":
        return MikrotikNetworkAdapter()

    return FakeNetworkAdapter()


def approve_configuration(
    configuration_id: uuid.UUID,
    user: User,
    db: Session,
    ttl_seconds: int = 300,
) -> Configuration:
    """
    Menyetujui proposal konfigurasi (REST oleh user terautentikasi).
    Transisi: PREVIEWED -> APPROVED.
    Mengikat TTL, user_id, device_id, plan_hash, dan state_fingerprint.
    """
    config = (
        db.query(Configuration)
        .filter(Configuration.id == configuration_id, Configuration.owner_id == user.id)
        .first()
    )
    if config is None:
        raise OrchestratorError("Proposal konfigurasi tidak ditemukan.")

    # Transisi ketat: Hanya boleh approve dari PREVIEWED atau VALIDATED
    if config.status not in ("PREVIEWED", "VALIDATED"):
        raise StateConflictError(
            f"Tidak dapat menyetujui konfigurasi dengan status '{config.status}'. "
            "Hanya proposal berstatus PREVIEWED yang dapat disetujui."
        )

    now = datetime.now(timezone.utc)
    config.status = "APPROVED"
    config.approved_by = user.id
    config.approved_at = now
    config.expires_at = now + timedelta(seconds=ttl_seconds)

    db.commit()
    db.refresh(config)

    record_audit_event(
        action="configuration.approve",
        result_status="SUCCESS",
        user_id=user.id,
        device_id=config.device_id,
        permission="modify",
        risk_level=config.risk_level,
        request_metadata={
            "configuration_id": str(config.id),
            "plan_hash": config.plan_hash,
            "expires_at": config.expires_at.isoformat(),
        },
        db=db,
    )
    return config


async def apply_configuration(
    configuration_id: uuid.UUID,
    user: User,
    db: Session,
) -> Configuration:
    """
    Menerapkan proposal konfigurasi ke perangkat jaringan:
    1. Lock apply per device (anti double-apply).
    2. Cek izin status APPROVED, TTL approval, kill-switch, dan guard lab.
    3. Cek drift (bandingkan state_fingerprint terkini).
    4. Ambil backup native & snapshot state_before.
    5. Terapkan operasi satu per satu via ToolManager.execute(is_internal=True).
    6. Verifikasi state nyata perangkat paska apply.
    7. Rollback otomatis LIFO jika gagal di tengah jalan atau verifikasi gagal.
    """
    config = (
        db.query(Configuration)
        .filter(Configuration.id == configuration_id, Configuration.owner_id == user.id)
        .first()
    )
    if config is None:
        raise OrchestratorError("Proposal konfigurasi tidak ditemukan.")

    device = db.query(Device).filter(Device.id == config.device_id, Device.owner_id == user.id).first()
    if device is None:
        raise OrchestratorError("Device target tidak ditemukan.")

    dev_key = str(device.id)
    dev_lock = await _get_device_lock(dev_key)

    try:
        await asyncio.wait_for(dev_lock.acquire(), timeout=_APPLY_LOCK_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        raise StateConflictError(
            f"Perangkat {device.name} sedang dalam proses konfigurasi oleh plan lain. Coba beberapa saat lagi."
        )

    try:
        # Cek DB apakah ada config lain yang berstatus APPLYING pada device ini
        active_applying = (
            db.query(Configuration)
            .filter(
                Configuration.device_id == device.id,
                Configuration.status == "APPLYING",
                Configuration.id != config.id,
            )
            .first()
        )
        if active_applying:
            raise StateConflictError(
                f"Perangkat {device.name} sedang menerapkan konfigurasi lain (ID: {active_applying.id})."
            )

        # 1. Validasi Status
        if config.status != "APPROVED":
            raise StateConflictError(
                f"Konfigurasi berstatus '{config.status}' tidak dapat di-apply. "
                "Hanya konfigurasi berstatus APPROVED yang dapat diterapkan."
            )

        # 2. Cek Expiry TTL
        now = datetime.now(timezone.utc)
        if config.expires_at and now >= config.expires_at:
            config.status = "EXPIRED"
            db.commit()
            record_audit_event(
                action="configuration.apply",
                result_status="DENIED",
                user_id=user.id,
                device_id=device.id,
                error_message="Approval context telah kadaluarsa (TTL habis).",
                db=db,
            )
            raise OrchestratorError("Approval telah kadaluarsa. Silakan generate plan dan approve ulang.")

        # 3. Kill-switch check (server-side authority)
        if not settings.config_apply_enabled:
            record_audit_event(
                action="configuration.apply",
                result_status="DENIED",
                user_id=user.id,
                device_id=device.id,
                error_message="DENIED: config_apply_enabled kill-switch is OFF",
                db=db,
            )
            raise OrchestratorError(
                "Eksekusi konfigurasi ditolak: CONFIG_APPLY_ENABLED=false pada environment backend. "
                "Untuk pengujian di MikroTik CHR yang terisolasi, set CONFIG_APPLY_ENABLED=true "
                "di backend/.env lalu restart backend. Jangan aktifkan untuk router produksi "
                "atau perangkat yang tidak terisolasi; kill-switch ini sengaja fail-closed."
            )

        # 4. Lab guard check
        # CATATAN GAP KEAMANAN: metadata['lab'] saat ini diisi oleh user.
        # Server-side kill-switch di atas adalah batas keamanan sesungguhnya sampai RBAC Phase 10 selesai.
        device_meta = device.device_metadata or {}
        if device_meta.get("lab") is not True:
            record_audit_event(
                action="configuration.apply",
                result_status="DENIED",
                user_id=user.id,
                device_id=device.id,
                error_message="DENIED: Device is not marked as a lab device",
                db=db,
            )
            raise OrchestratorError(
                f"Perangkat '{device.name}' tidak ditandai sebagai lab (metadata.lab != true). "
                "NOVA menolak menerapkan perubahan ke perangkat non-lab."
            )

        adapter = _resolve_adapter(device)
        ctx = build_device_context(device, user, db) if device.platform == "mikrotik" else None

        # 5. Baca state perangkat untuk cek Drift
        current_state = await adapter.get_device_state(device, ctx)
        current_fingerprint = calculate_state_fingerprint(current_state)

        if current_fingerprint != config.state_fingerprint:
            config.status = "EXPIRED"
            db.commit()
            err_msg = "State drift terdeteksi: kondisi perangkat berubah sejak preview dibuat. Wajib re-plan."
            record_audit_event(
                action="configuration.apply",
                result_status="DENIED",
                user_id=user.id,
                device_id=device.id,
                error_message=err_msg,
                db=db,
            )
            raise DriftDetectedError(err_msg)

        # 6. Transisi status ke APPLYING
        config.status = "APPLYING"
        db.commit()

        # 7. Simpan snapshot state_before ke disk
        snapshot_ref = save_state_snapshot(
            owner_id=user.id,
            device_id=device.id,
            state_data=current_state.model_dump(mode="json"),
        )

        # Coba backup native di router jika didukung
        backup_name = f"nova_backup_{config.id.hex[:8]}"
        if hasattr(adapter, "create_native_backup"):
            try:
                await adapter.create_native_backup(backup_name, device, ctx)
                snapshot_ref["native_backup_name"] = backup_name
            except Exception as exc:
                logger.warning("Gagal membuat backup native di flash router: %s", exc)

        # 8. Siapkan ApprovalContext terverifikasi untuk ToolManager
        approval_ctx = ApprovalContext(
            user_id=str(user.id),
            tool_name=f"{device.platform}.config_apply",
            arguments_hash="",
            created_at=config.approved_at or now,
            expires_at=config.expires_at or (now + timedelta(minutes=5)),
            device_id=str(device.id),
            configuration_id=str(config.id),
            plan_hash=config.plan_hash,
            state_fingerprint=config.state_fingerprint,
            used=False,
        )

        change_set = ChangeSet.model_validate(config.change_set)
        applied_steps: list[tuple[NetworkOperation, str]] = []
        op_results: list[dict[str, Any]] = []

        # 9. Terapkan operasi satu per satu via ToolManager
        apply_tool_name = f"{device.platform}.config_apply"
        apply_failed = False
        apply_error = None

        for idx, op in enumerate(change_set.operations, start=1):
            logger.info("Applying step %d/%d (%s) for config %s", idx, len(change_set.operations), op.type.value, config.id)
            tool_req = ToolRequest(
                tool_name=apply_tool_name,
                arguments={
                    "operation": op.model_dump(mode="json"),
                    "action": "apply",
                    "plan_hash": config.plan_hash,
                    "state_fingerprint": config.state_fingerprint,
                },
                confirmed=True,
                device_id=device.id,
            )

            try:
                result = await tool_manager.execute(
                    request=tool_req,
                    user=user,
                    db=db,
                    is_internal=True,
                    approval_ctx=approval_ctx,
                )
                if not result.success:
                    apply_failed = True
                    apply_error = f"Step #{idx} ({op.type.value}) gagal: {result.error}"
                    break

                obj_id = (result.output or {}).get("object_id") or f"*obj_{idx}"
                applied_steps.append((op, obj_id))
                op_results.append({
                    "step": idx,
                    "type": op.type.value,
                    "object_id": obj_id,
                    "status": "SUCCESS",
                })
            except Exception as exc:
                apply_failed = True
                apply_error = f"Step #{idx} ({op.type.value}) exception: {exc}"
                break

        # 10. Tangani kegagalan eksekusi -> Rollback Otomatis
        if apply_failed:
            logger.error("Apply gagal pada konfigurasi %s: %s", config.id, apply_error)
            config.status = "FAILED"
            db.commit()

            try:
                await execute_lifo_rollback(
                    applied_steps=applied_steps,
                    device=device,
                    user=user,
                    adapter=adapter,
                    db=db,
                    approval_ctx=approval_ctx,
                    config=config,
                )
                config.status = "ROLLED_BACK"
            except RollbackError as r_err:
                config.status = "ROLLBACK_FAILED"
                logger.critical("CRITICAL: ROLLBACK_FAILED untuk config %s: %s", config.id, r_err)

            db.commit()

            # Simpan version record kegagalan
            version_rec = ConfigurationVersion(
                configuration_id=config.id,
                owner_id=user.id,
                device_id=device.id,
                version_number=1,
                backup_ref=snapshot_ref,
                state_before=current_state.model_dump(mode="json"),
                state_after=None,
                operation_results=op_results,
                verification_results={"status": "FAILED", "error": apply_error},
            )
            db.add(version_rec)
            db.commit()

            raise OrchestratorError(f"Apply gagal: {apply_error}. Status konfigurasi: {config.status}")

        # 11. Verifikasi State Nyata Perangkat (Bukti Nyata)
        logger.info("Memulai verifikasi state nyata untuk config %s", config.id)
        verified_all = True
        verification_details: dict[str, Any] = {}

        for idx, (op, obj_id) in enumerate(applied_steps, start=1):
            is_verified = await adapter.verify_operation(op, device, ctx)
            verification_details[f"step_{idx}"] = {
                "type": op.type.value,
                "verified": is_verified,
            }
            if not is_verified:
                verified_all = False
                logger.error("Verifikasi gagal untuk step #%d (%s)", idx, op.type.value)

        if not verified_all:
            logger.error("Verifikasi state gagal untuk config %s! Memicu rollback...", config.id)
            config.status = "FAILED"
            db.commit()

            try:
                await execute_lifo_rollback(
                    applied_steps=applied_steps,
                    device=device,
                    user=user,
                    adapter=adapter,
                    db=db,
                    approval_ctx=approval_ctx,
                    config=config,
                )
                config.status = "ROLLED_BACK"
            except RollbackError:
                config.status = "ROLLBACK_FAILED"

            db.commit()
            raise VerificationFailedError("Verifikasi state nyata perangkat gagal setelah apply.")

        # 12. Sukses Penuh
        approval_ctx.used = True
        config.status = "VERIFIED"
        config.applied_at = datetime.now(timezone.utc)

        state_after = await adapter.get_device_state(device, ctx)
        db.commit()
        db.refresh(config)

        version_rec = ConfigurationVersion(
            configuration_id=config.id,
            owner_id=user.id,
            device_id=device.id,
            version_number=1,
            backup_ref=snapshot_ref,
            state_before=current_state.model_dump(mode="json"),
            state_after=state_after.model_dump(mode="json"),
            operation_results=op_results,
            verification_results={"status": "VERIFIED", "details": verification_details},
        )
        db.add(version_rec)
        db.commit()

        record_audit_event(
            action="configuration.apply",
            result_status="SUCCESS",
            verification_status="VERIFIED",
            user_id=user.id,
            device_id=device.id,
            permission="modify",
            risk_level=config.risk_level,
            request_metadata={
                "configuration_id": str(config.id),
                "plan_hash": config.plan_hash,
                "operations_count": len(applied_steps),
            },
            db=db,
        )
        return config

    finally:
        dev_lock.release()


async def manual_rollback_configuration(
    configuration_id: uuid.UUID,
    user: User,
    db: Session,
) -> Configuration:
    """
    Manual rollback paska-apply (hanya untuk status VERIFIED atau FAILED).
    """
    config = (
        db.query(Configuration)
        .filter(Configuration.id == configuration_id, Configuration.owner_id == user.id)
        .first()
    )
    if config is None:
        raise OrchestratorError("Proposal konfigurasi tidak ditemukan.")

    if config.status not in ("VERIFIED", "FAILED"):
        raise StateConflictError(
            f"Rollback manual hanya dapat dilakukan pada konfigurasi berstatus VERIFIED atau FAILED (status saat ini: '{config.status}')."
        )

    device = db.query(Device).filter(Device.id == config.device_id, Device.owner_id == user.id).first()
    if device is None:
        raise OrchestratorError("Device target tidak ditemukan.")

    dev_lock = await _get_device_lock(str(device.id))
    try:
        await asyncio.wait_for(dev_lock.acquire(), timeout=_APPLY_LOCK_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        raise StateConflictError(f"Perangkat {device.name} sedang sibuk.")

    try:
        # Ambil riwayat eksekusi dari configuration_versions
        version_rec = (
            db.query(ConfigurationVersion)
            .filter(ConfigurationVersion.configuration_id == config.id)
            .order_by(ConfigurationVersion.version_number.desc())
            .first()
        )
        if version_rec is None or not version_rec.operation_results:
            raise OrchestratorError("Tidak ada riwayat operasi yang tersimpan untuk di-rollback.")

        adapter = _resolve_adapter(device)
        ctx = build_device_context(device, user, db) if device.platform == "mikrotik" else None
        change_set = ChangeSet.model_validate(config.change_set)

        # Mapping operasi dan object_id
        applied_steps: list[tuple[NetworkOperation, str]] = []
        for op, op_res in zip(change_set.operations, version_rec.operation_results):
            obj_id = op_res.get("object_id")
            if obj_id:
                applied_steps.append((op, obj_id))

        approval_ctx = ApprovalContext(
            user_id=str(user.id),
            tool_name=f"{device.platform}.config_apply",
            arguments_hash="",
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            device_id=str(device.id),
            configuration_id=str(config.id),
            plan_hash=config.plan_hash,
            state_fingerprint=config.state_fingerprint,
            used=False,
        )

        try:
            await execute_lifo_rollback(
                applied_steps=applied_steps,
                device=device,
                user=user,
                adapter=adapter,
                db=db,
                approval_ctx=approval_ctx,
                config=config,
            )
            config.status = "ROLLED_BACK"
        except RollbackError:
            config.status = "ROLLBACK_FAILED"

        db.commit()
        db.refresh(config)
        return config

    finally:
        dev_lock.release()
