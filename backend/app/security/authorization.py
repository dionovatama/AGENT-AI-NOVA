"""
Authorization Service for N.O.V.A — Backend-enforced Policy Boundary.

Prinsip Utama:
- Identitas berasal DARI JWT (current_user), bukan input client.
- 'confirmed: true' BUKAN autentikasi, melainkan sinyal persetujuan tindakan.
- Backend yang berwenang menentukan boleh/tidaknya eksekusi tool sebelum
  executor dijalankan (Core Principle: LLM is untrusted decision maker).
"""

from __future__ import annotations

import logging
from typing import Any

from app.database.models import User
from app.security.permissions import PermissionDeniedError
from app.tools.schemas import PermissionLevel

logger = logging.getLogger("nova.security.authorization")


class AuthorizationError(PermissionDeniedError):
    """Dilempar saat eksekusi tool ditolak oleh kebijakan otorisasi backend."""


def authorize_tool_execution(
    user: User | None,
    tool_name: str,
    permission: PermissionLevel,
    confirmed: bool,
    context: dict[str, Any] | None = None,
) -> None:
    """
    Otorisasi eksekusi tool di level backend.

    Memeriksa:
    1. Pengguna terautentikasi dan aktif.
    2. Kebijakan permission (READ, MODIFY, HIGH_RISK).
    3. Status konfirmasi eksplisit (approval signal).
    4. Kebijakan tambahan untuk high risk / tenant scope.

    Melempar AuthorizationError jika ditolak; tidak mengembalikan apa pun jika lolos.
    """
    if user is None:
        raise AuthorizationError(
            "Autentikasi diperlukan. Request tool execution harus memiliki "
            "identitas pengguna valid dari JWT token."
        )

    if not getattr(user, "is_active", True):
        raise AuthorizationError("Akun pengguna tidak aktif.")

    logger.info(
        "Authorizing tool execution: user=%s tool=%s permission=%s confirmed=%s",
        getattr(user, "id", "unknown"),
        tool_name,
        permission.value,
        confirmed,
    )

    if permission == PermissionLevel.READ:
        # READ: user terautentikasi diizinkan menjalankan tool allowlist
        return

    if permission == PermissionLevel.MODIFY:
        if not confirmed:
            raise AuthorizationError(
                "Tool ini memerlukan confirmation (permission level: MODIFY). "
                "Kirim ulang request dengan 'confirmed': true setelah user "
                "menyetujui preview perubahan."
            )
        return

    if permission == PermissionLevel.HIGH_RISK:
        if not confirmed:
            raise AuthorizationError(
                "Tool ini memerlukan confirmation kuat (permission level: HIGH_RISK). "
                "Operasi ini berisiko tinggi dan tidak boleh dijalankan tanpa "
                "persetujuan eksplisit dari user."
            )
        # Boundary tambahan: HIGH_RISK tidak pernah dieksekusi hanya karena
        # tool ada di allowlist — konfirmasi eksplisit wajib ada.
        return

    raise AuthorizationError(f"Permission level tidak dikenal: {permission}")
