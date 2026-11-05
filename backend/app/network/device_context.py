"""Build an authenticated, owner-scoped device execution context for network adapters."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.database.models import Credential, Device, User
from app.tools.context import ExecutionContext
from app.security.credential_resolver import resolve_credential_secret
from app.security.credential_encryption import CredentialEncryptionError


def build_device_context(device: Device, user: User, db: Session) -> ExecutionContext:
    """Resolve a device credential without exposing it in responses or logs."""
    if device.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Device tidak ditemukan.")
    if device.credential_id is None:
        raise ValueError("Device belum memiliki credential yang terpasang.")
    credential = (
        db.query(Credential)
        .filter(Credential.id == device.credential_id, Credential.owner_id == user.id)
        .first()
    )
    if credential is None:
        raise ValueError("Credential device tidak ditemukan atau bukan milik pengguna ini.")
    try:
        secret = resolve_credential_secret(credential)
    except CredentialEncryptionError as exc:
        raise HTTPException(
            status_code=503,
            detail="Credential encryption is unavailable or the credential needs migration.",
        ) from exc
    return ExecutionContext(user=user, db=db, device=device, credential_plaintext=secret)
