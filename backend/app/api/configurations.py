"""
Configuration Engine API Endpoints (Phase 7 & 8: PRD section 19-23, 33).

Endpoint:
- POST /configurations      : Membuat proposal konfigurasi, validasi, preview (DRAFT -> VALIDATED -> PREVIEWED)
- GET  /configurations      : Menampilkan seluruh proposal konfigurasi milik user aktif
- GET  /configurations/{id} : Menampilkan detail satu proposal konfigurasi (termasuk diff & CLI preview)
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.models import Configuration, Device, User
from app.database.session import get_db
from app.network.adapters.base import NetworkDeviceAdapter
from app.network.adapters.fake import FakeNetworkAdapter
from app.network.models import ChangeSet, DeviceStateSnapshot
from app.network.preview import (
    calculate_plan_hash,
    calculate_state_fingerprint,
    generate_structured_diff,
    render_cli_preview,
)
from app.network.validation import validate_change_set
from app.schemas.configurations import ConfigurationCreateRequest, ConfigurationResponse
from app.security.audit import record_audit_event
from app.security.dependencies import get_current_user

logger = logging.getLogger("nova.api.configurations")

router = APIRouter(prefix="/configurations", tags=["configurations"])

# Registry adapter default / test override
_CUSTOM_ADAPTER: NetworkDeviceAdapter | None = None


def set_custom_adapter(adapter: NetworkDeviceAdapter | None) -> None:
    """Helper untuk unit/integration test menyuntikkan adapter khusus."""
    global _CUSTOM_ADAPTER
    _CUSTOM_ADAPTER = adapter


def get_adapter_for_device(device: Device) -> NetworkDeviceAdapter:
    """
    Mengembalikan adapter yang sesuai untuk tipe platform perangkat.
    Pada Milestone A, default adalah FakeNetworkAdapter (in-memory simulation).
    """
    if _CUSTOM_ADAPTER is not None:
        return _CUSTOM_ADAPTER

    # Default adapter simulasi aman
    return FakeNetworkAdapter()


@router.post("", response_model=ConfigurationResponse, status_code=status.HTTP_201_CREATED)
async def create_configuration(
    payload: ConfigurationCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConfigurationResponse:
    """
    Membuat proposal konfigurasi baru:
    1. Tenant isolation: device harus milik user aktif.
    2. Baca state nyata perangkat lewat adapter.
    3. Validasi skema, semantik, kebijakan, dan proteksi lockout.
    4. Buat structured diff dan CLI preview deterministik.
    5. Hitung plan_hash dan state_fingerprint.
    6. Simpan proposal ke DB dengan status PREVIEWED.
    """
    # 1. Tenant Isolation: Cek kepemilikan device
    device = (
        db.query(Device)
        .filter(Device.id == payload.device_id, Device.owner_id == current_user.id)
        .first()
    )
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device tidak ditemukan atau bukan milik pengguna ini.",
        )

    # 2. Ambil adapter dan baca state perangkat
    adapter = get_adapter_for_device(device)
    try:
        device_state = await adapter.get_device_state(device)
    except Exception as exc:
        logger.error("Gagal membaca state perangkat %s: %s", device.id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gagal membaca state dari perangkat: {exc}",
        )

    # 3. Validasi terhadap state perangkat dan kebijakan
    val_result = validate_change_set(
        change_set=payload.change_set,
        device_state=device_state,
        device_management_ip=device.host,
        proposed_risk_level=payload.proposed_risk_level,
    )

    if not val_result.is_valid:
        error_details = [
            {"field": issue.field, "message": issue.message, "severity": issue.severity}
            for issue in val_result.issues
        ]
        record_audit_event(
            action="configuration.validate",
            result_status="DENIED",
            user_id=current_user.id,
            device_id=device.id,
            permission="modify",
            risk_level=val_result.risk_level.value,
            request_metadata={"errors": error_details, "description": payload.change_set.description},
            error_message="Validasi proposal konfigurasi gagal.",
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Validasi konfigurasi gagal.", "errors": error_details},
        )

    # 4. Generate Diff dan CLI Preview
    diff = generate_structured_diff(payload.change_set, device_state)
    cli_preview_text = render_cli_preview(payload.change_set, adapter)

    # 5. Hitung Hash Kanonik
    plan_hash = calculate_plan_hash(device.id, payload.change_set)
    fingerprint = calculate_state_fingerprint(device_state)

    # 6. Simpan ke database
    config = Configuration(
        owner_id=current_user.id,
        device_id=device.id,
        status="PREVIEWED",
        risk_level=val_result.risk_level.value,
        change_set=payload.change_set.model_dump(mode="json"),
        plan_hash=plan_hash,
        state_fingerprint=fingerprint,
    )
    db.add(config)
    db.commit()
    db.refresh(config)

    # Audit log
    record_audit_event(
        action="configuration.create",
        result_status="SUCCESS",
        user_id=current_user.id,
        device_id=device.id,
        permission="modify",
        risk_level=config.risk_level,
        request_metadata={
            "configuration_id": str(config.id),
            "plan_hash": plan_hash,
            "state_fingerprint": fingerprint,
            "operation_count": len(payload.change_set.operations),
        },
        db=db,
    )

    response = ConfigurationResponse.model_validate(config)
    response.structured_diff = diff
    response.cli_preview = cli_preview_text
    return response


@router.get("", response_model=list[ConfigurationResponse])
def list_configurations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Configuration]:
    """Menampilkan seluruh proposal konfigurasi milik user aktif (tenant isolated)."""
    return (
        db.query(Configuration)
        .filter(Configuration.owner_id == current_user.id)
        .order_by(Configuration.created_at.desc())
        .all()
    )


@router.get("/{configuration_id}", response_model=ConfigurationResponse)
async def get_configuration(
    configuration_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConfigurationResponse:
    """Mendapatkan detail proposal konfigurasi berdasarkan ID (tenant isolated)."""
    config = (
        db.query(Configuration)
        .filter(
            Configuration.id == configuration_id,
            Configuration.owner_id == current_user.id,
        )
        .first()
    )
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Configuration proposal tidak ditemukan.",
        )

    response = ConfigurationResponse.model_validate(config)

    # Rekonstruksi diff dan CLI preview untuk tampilan detail
    try:
        device = db.query(Device).filter(Device.id == config.device_id).first()
        if device:
            adapter = get_adapter_for_device(device)
            cs = ChangeSet.model_validate(config.change_set)
            response.cli_preview = render_cli_preview(cs, adapter)
    except Exception as exc:
        logger.warning("Tidak dapat merekonstruksi CLI preview untuk config %s: %s", config.id, exc)

    return response


@router.post("/{configuration_id}/approve", response_model=ConfigurationResponse)
def approve_configuration_endpoint(
    configuration_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConfigurationResponse:
    """
    Menyetujui proposal konfigurasi (REST oleh user terautentikasi).
    Transisi: PREVIEWED -> APPROVED.
    """
    from app.network.orchestrator import (
        StateConflictError,
        approve_configuration as orch_approve,
    )

    try:
        config = orch_approve(
            configuration_id=configuration_id,
            user=current_user,
            db=db,
            ttl_seconds=300,
        )
        return ConfigurationResponse.model_validate(config)
    except StateConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        if "tidak ditemukan" in str(exc).lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configuration proposal tidak ditemukan.") from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{configuration_id}/apply", response_model=ConfigurationResponse)
async def apply_configuration_endpoint(
    configuration_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConfigurationResponse:
    """
    Menerapkan konfigurasi yang telah disetujui ke perangkat:
    1. Lock apply per device.
    2. Verifikasi status APPROVED & TTL.
    3. Cek kill-switch CONFIG_APPLY_ENABLED & guard lab.
    4. Cek state drift.
    5. Backup native + snapshot terstruktur.
    6. Eksekusi per-step via ToolManager.
    7. Verifikasi state nyata perangkat paska apply.
    8. Rollback LIFO otomatis jika gagal.
    """
    from app.network.orchestrator import (
        DriftDetectedError,
        StateConflictError,
        VerificationFailedError,
        apply_configuration as orch_apply,
    )

    try:
        config = await orch_apply(
            configuration_id=configuration_id,
            user=current_user,
            db=db,
        )
        return ConfigurationResponse.model_validate(config)
    except DriftDetectedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except StateConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except VerificationFailedError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except Exception as exc:
        if "tidak ditemukan" in str(exc).lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configuration proposal tidak ditemukan.") from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{configuration_id}/rollback", response_model=ConfigurationResponse)
async def rollback_configuration_endpoint(
    configuration_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConfigurationResponse:
    """
    Manual rollback paska-apply untuk membatalkan perubahan yang telah diterapkan.
    Hanya dapat dilakukan jika status konfigurasi adalah VERIFIED atau FAILED.
    """
    from app.network.orchestrator import (
        StateConflictError,
        manual_rollback_configuration as orch_rollback,
    )

    try:
        config = await orch_rollback(
            configuration_id=configuration_id,
            user=current_user,
            db=db,
        )
        return ConfigurationResponse.model_validate(config)
    except StateConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        if "tidak ditemukan" in str(exc).lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configuration proposal tidak ditemukan.") from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
