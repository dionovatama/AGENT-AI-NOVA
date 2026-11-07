"""
Device and Credential management endpoints — Foundation Data Model & Tenant Isolation.

Prinsip:
- Tenant/Owner Isolation: User A tidak pernah bisa mengakses Device/Credential milik User B.
- Zero Secret Exposure: Secret reference tidak dibocorkan di API response dan LLM reasoning.
- Identity derived exclusively from JWT (current_user.id).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database.models import AuditLog, Credential, Device, User
from app.database.session import get_db
from app.schemas.devices import (
    AuditLogResponse,
    CredentialCreateRequest,
    CredentialResponse,
    DeviceCreateRequest,
    DeviceResponse,
    DeviceUpdateRequest,
)
from app.security.dependencies import get_current_user
from app.security.credential_encryption import CredentialEncryptionError, encrypt_credential
from app.network.relay_tls import normalize_fingerprint
from app.security.audit import record_audit_event
from app.network.remote_transport import clear_observed_fingerprint, get_observed_fingerprint

router = APIRouter(tags=["devices", "credentials", "audit"])


# ============================================================
# Device Endpoints
# ============================================================

@router.post("/devices", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
def create_device(
    payload: DeviceCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Device:
    """Membuat device baru yang terikat secara eksklusif ke owner_id pengguna saat ini."""
    if payload.credential_id is not None:
        # Validasi bahwa credential yang direferensikan benar-benar milik user ini
        credential = (
            db.query(Credential)
            .filter(
                Credential.id == payload.credential_id,
                Credential.owner_id == current_user.id,
            )
            .first()
        )
        if credential is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Credential not found or does not belong to the authenticated user.",
            )

    device = Device(
        owner_id=current_user.id,
        name=payload.name,
        platform=payload.platform.lower(),
        host=payload.host,
        port=payload.port,
        connection_type=payload.connection_type,
        status=payload.status,
        credential_id=payload.credential_id,
        device_metadata=payload.metadata,
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


@router.get("/devices", response_model=list[DeviceResponse])
def list_devices(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Device]:
    """Mendapatkan semua device milik user saat ini (tenant isolated)."""
    return db.query(Device).filter(Device.owner_id == current_user.id).all()


@router.get("/devices/{device_id}", response_model=DeviceResponse)
def get_device(
    device_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Device:
    """Mendapatkan detail device berdasarkan ID. Menolak akses (404) jika bukan milik user."""
    device = (
        db.query(Device)
        .filter(Device.id == device_id, Device.owner_id == current_user.id)
        .first()
    )
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found.",
        )
    return device


@router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_device(
    device_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Menghapus device milik pengguna yang sedang login."""
    device = (
        db.query(Device)
        .filter(Device.id == device_id, Device.owner_id == current_user.id)
        .first()
    )
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found.")

    db.delete(device)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/devices/{device_id}", response_model=DeviceResponse)
def update_device(
    device_id: uuid.UUID,
    payload: DeviceUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Device:
    """Memperbarui field device secara parsial, dengan isolasi owner."""
    device = (
        db.query(Device)
        .filter(Device.id == device_id, Device.owner_id == current_user.id)
        .first()
    )
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found.",
        )

    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No device fields supplied for update.",
        )

    pin_supplied = "tls_fingerprint" in changes
    new_pin = changes.pop("tls_fingerprint", None)
    confirm_pin_change = changes.pop("confirm_tls_fingerprint_change", False)
    old_pin = (device.device_metadata or {}).get("tls_fingerprint")
    if pin_supplied:
        try:
            new_pin = normalize_fingerprint(new_pin) if new_pin else None
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="tls_fingerprint must be a SHA-256 fingerprint.") from None
        old_prefix = old_pin[:16] if isinstance(old_pin, str) else None
        if payload.expected_tls_fingerprint_prefix != old_prefix:
            raise HTTPException(status_code=409, detail="The current device pin changed. Refresh and confirm again.")
        if new_pin != old_pin and not confirm_pin_change:
            raise HTTPException(status_code=409, detail="Explicit confirmation is required to change the device TLS pin.")

    if "credential_id" in changes and changes["credential_id"] is not None:
        credential = (
            db.query(Credential)
            .filter(
                Credential.id == changes["credential_id"],
                Credential.owner_id == current_user.id,
            )
            .first()
        )
        if credential is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Credential not found or does not belong to the authenticated user.",
            )

    for field, value in changes.items():
        if field == "platform" and value is not None:
            value = value.lower()
        if field == "metadata":
            device.device_metadata = value
        else:
            setattr(device, field, value)

    if pin_supplied:
        metadata = dict(device.device_metadata or {})
        if new_pin:
            metadata["tls_fingerprint"] = new_pin
        else:
            metadata.pop("tls_fingerprint", None)
        device.device_metadata = metadata

    db.commit()
    db.refresh(device)
    if pin_supplied and new_pin != old_pin:
        clear_observed_fingerprint(current_user.id, device.id)
        record_audit_event(
            action="device.tls_pin_updated", result_status="SUCCESS", user_id=current_user.id,
            device_id=device.id,
            request_metadata={
                "old_fingerprint_prefix": old_pin[:12] if isinstance(old_pin, str) else None,
                "new_fingerprint_prefix": new_pin[:12] if isinstance(new_pin, str) else None,
                "operator_confirmed": True,
            },
            db=db,
        )
    return device


@router.get("/devices/{device_id}/observed-tls-fingerprint")
def get_observed_device_tls_fingerprint(
    device_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return a recent observed certificate only to the owning operator."""
    device = db.query(Device).filter(
        Device.id == device_id, Device.owner_id == current_user.id
    ).first()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found.")
    observed = get_observed_fingerprint(current_user.id, device.id)
    if observed is None:
        raise HTTPException(status_code=404, detail="No recent observed certificate fingerprint.")
    return {"observed": observed, "expires_in_seconds": 900}


# ============================================================
# Credential Endpoints
# ============================================================

@router.post("/credentials", response_model=CredentialResponse, status_code=status.HTTP_201_CREATED)
def create_credential(
    payload: CredentialCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Credential:
    """
    Membuat referensi credential baru yang terikat secara eksklusif ke owner_id pengguna saat ini.
    Secret dienkripsi dengan AES-256-GCM sebelum disimpan.
    """
    credential_id = uuid.uuid4()
    try:
        encrypted = encrypt_credential(
            payload.secret_reference,
            owner_id=current_user.id,
            credential_id=credential_id,
        )
    except CredentialEncryptionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Credential encryption is unavailable or misconfigured.",
        ) from exc

    credential = Credential(
        id=credential_id,
        owner_id=current_user.id,
        name=payload.name,
        type=payload.type,
        encrypted_secret=encrypted.ciphertext,
        encryption_nonce=encrypted.nonce,
        encryption_key_id=encrypted.key_id,
        secret_reference=None,
    )
    db.add(credential)
    db.commit()
    db.refresh(credential)
    return credential


@router.get("/credentials", response_model=list[CredentialResponse])
def list_credentials(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Credential]:
    """Mendapatkan daftar credential milik user saat ini tanpa membocorkan secret_reference."""
    return db.query(Credential).filter(Credential.owner_id == current_user.id).all()


@router.get("/credentials/{credential_id}", response_model=CredentialResponse)
def get_credential(
    credential_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Credential:
    """Mendapatkan detail credential. Menolak akses (404) jika bukan milik user."""
    credential = (
        db.query(Credential)
        .filter(Credential.id == credential_id, Credential.owner_id == current_user.id)
        .first()
    )
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found.",
        )
    return credential


@router.delete("/credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_credential(
    credential_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Menghapus credential milik pengguna; FK device akan di-set NULL."""
    credential = (
        db.query(Credential)
        .filter(Credential.id == credential_id, Credential.owner_id == current_user.id)
        .first()
    )
    if credential is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found.")

    db.delete(credential)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ============================================================
# Audit Log Endpoints
# ============================================================

@router.get("/audit-logs", response_model=list[AuditLogResponse])
def list_audit_logs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AuditLog]:
    """Mendapatkan catatan audit persisten milik user saat ini (tenant isolated)."""
    return (
        db.query(AuditLog)
        .filter(AuditLog.user_id == current_user.id)
        .order_by(AuditLog.created_at.desc())
        .all()
    )
