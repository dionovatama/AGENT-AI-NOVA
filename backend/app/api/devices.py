"""
Device and Credential management endpoints — Foundation Data Model & Tenant Isolation.

Prinsip:
- Tenant/Owner Isolation: User A tidak pernah bisa mengakses Device/Credential milik User B.
- Zero Secret Exposure: Secret reference tidak dibocorkan di API response dan LLM reasoning.
- Identity derived exclusively from JWT (current_user.id).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.models import AuditLog, Credential, Device, User
from app.database.session import get_db
from app.schemas.devices import (
    AuditLogResponse,
    CredentialCreateRequest,
    CredentialResponse,
    DeviceCreateRequest,
    DeviceResponse,
)
from app.security.dependencies import get_current_user

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
    Plaintext password/key tidak disimpan langsung di sini.
    """
    credential = Credential(
        owner_id=current_user.id,
        name=payload.name,
        type=payload.type,
        secret_reference=payload.secret_reference,
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
