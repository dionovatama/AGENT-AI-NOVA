"""
Authorization Service for N.O.V.A — Backend-enforced Policy Boundary.

Prinsip Utama:
- Identitas berasal DARI JWT (current_user), bukan input client.
- 'confirmed: true' BUKAN autentikasi, melainkan sinyal persetujuan tindakan.
- Backend yang berwenang menentukan boleh/tidaknya eksekusi tool sebelum
  executor dijalankan (Core Principle: LLM is untrusted decision maker).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.database.models import User
from app.security.permissions import PermissionDeniedError
from app.tools.schemas import PermissionLevel

logger = logging.getLogger("nova.security.authorization")

# Mapping tool namespace prefix -> expected device platform(s).
# FIX-J: Platform compatibility gate.
_TOOL_PLATFORM_MAP: dict[str, list[str]] = {
    "linux": ["linux"],
    "mikrotik": ["mikrotik"],
    "cisco": ["cisco"],
    "windows": ["windows"],
    # Tools tanpa prefix (web.*, dll) tidak memerlukan device platform.
}


class AuthorizationError(PermissionDeniedError):
    """Dilempar saat eksekusi tool ditolak oleh kebijakan otorisasi backend."""


# ---------------------------------------------------------------------------
# FIX-G: ApprovalContext — abstraksi stateless untuk sinyal persetujuan user.
#
# ApprovalContext merepresentasikan persetujuan yang sudah diberikan user
# untuk satu kombinasi spesifik (user, tool, device, arguments, TTL).
#
# Prinsip: 'confirmed=True' dalam request bukan bukti persetujuan yang cukup
# untuk MODIFY/HIGH_RISK — ia harus diperkuat dengan konteks yang terverifikasi.
# Saat ini digunakan sebagai abstraksi struktural; validasinya aktif dipakai
# ketika MODIFY/HIGH_RISK endpoint diimplementasikan.
# ---------------------------------------------------------------------------

@dataclass
class ApprovalContext:
    """
    Konteks persetujuan yang diberikan user untuk satu tindakan spesifik.

    Fields:
        user_id: ID pengguna yang memberikan persetujuan.
        tool_name: Nama tool yang disetujui.
        device_id: ID device target (None jika tidak relevan).
        arguments_hash: SHA-256 hex digest dari JSON-serialized arguments.
            Memastikan approval hanya berlaku untuk argumen yang persis sama.
        created_at: Waktu persetujuan diberikan (UTC).
        expires_at: Waktu kadaluarsa persetujuan (UTC).
    """
    user_id: str
    tool_name: str
    arguments_hash: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    device_id: str | None = None

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at


def build_approval_context(
    user: User,
    tool_name: str,
    arguments: dict[str, Any],
    device_id: str | None = None,
    ttl_seconds: int = 300,
) -> ApprovalContext:
    """
    Factory untuk membuat ApprovalContext dari sebuah request.
    arguments_hash dihitung dari JSON serialisasi deterministik argumen,
    sehingga approval hanya berlaku untuk argumen yang persis sama.
    """
    args_canonical = json.dumps(arguments, sort_keys=True, ensure_ascii=True)
    args_hash = hashlib.sha256(args_canonical.encode()).hexdigest()

    now = datetime.now(timezone.utc)
    # Avoid circular import: import timedelta inline
    from datetime import timedelta
    return ApprovalContext(
        user_id=str(user.id),
        tool_name=tool_name,
        arguments_hash=args_hash,
        device_id=str(device_id) if device_id else None,
        created_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
    )


def validate_approval_context(
    ctx: ApprovalContext,
    user: User,
    tool_name: str,
    arguments: dict[str, Any],
    device_id: str | None = None,
) -> None:
    """
    Memvalidasi ApprovalContext untuk sebuah request eksekusi.

    Memeriksa:
    - Sama user (user_id match)
    - Sama tool (tool_name match)
    - Sama argumen (SHA-256 hash match — mencegah argument tampering)
    - Sama device (device_id match, jika relevan)
    - Belum kadaluarsa

    Melempar AuthorizationError jika validasi gagal.
    """
    if ctx.is_expired:
        raise AuthorizationError(
            "Approval context sudah kadaluarsa. Minta persetujuan user ulang."
        )

    if ctx.user_id != str(user.id):
        raise AuthorizationError(
            "Approval context bukan milik user yang sedang melakukan request."
        )

    if ctx.tool_name != tool_name:
        raise AuthorizationError(
            f"Approval context untuk tool '{ctx.tool_name}' "
            f"tidak cocok dengan tool yang diminta '{tool_name}'."
        )

    args_canonical = json.dumps(arguments, sort_keys=True, ensure_ascii=True)
    args_hash = hashlib.sha256(args_canonical.encode()).hexdigest()
    if ctx.arguments_hash != args_hash:
        raise AuthorizationError(
            "Argumen request tidak cocok dengan yang telah disetujui user. "
            "Approval tidak berlaku untuk argumen yang berbeda."
        )

    if (ctx.device_id or None) != (str(device_id) if device_id else None):
        raise AuthorizationError(
            "Approval context untuk device yang berbeda. "
            "Approval tidak dapat ditransfer antar device."
        )


# ---------------------------------------------------------------------------
# FIX-J: Platform compatibility validation
# ---------------------------------------------------------------------------

def validate_platform_compatibility(tool_name: str, platform: str | None) -> None:
    """
    Memvalidasi bahwa namespace tool sesuai dengan platform device.

    Contoh: tool 'linux.system_info' hanya valid untuk device platform 'linux'.
    Jika platform=None (tidak ada device context), validasi dilewati (fail-open
    untuk tool yang tidak memerlukan device, mis. web.*).

    Melempar AuthorizationError jika platform tidak kompatibel.
    """
    if platform is None:
        return

    # Ekstrak prefix namespace dari nama tool (mis. "linux" dari "linux.system_info")
    namespace = tool_name.split(".")[0] if "." in tool_name else None
    if namespace is None:
        return

    allowed_platforms = _TOOL_PLATFORM_MAP.get(namespace)
    if allowed_platforms is None:
        # Namespace tidak memerlukan platform restriction
        return

    if platform.lower() not in allowed_platforms:
        raise AuthorizationError(
            f"Tool '{tool_name}' hanya kompatibel dengan platform "
            f"{allowed_platforms}, tapi device platform adalah '{platform}'."
        )


def authorize_tool_execution(
    user: User | None,
    tool_name: str,
    permission: PermissionLevel,
    confirmed: bool,
    context: dict[str, Any] | None = None,
    approval_ctx: ApprovalContext | None = None,
) -> None:
    """
    Otorisasi eksekusi tool di level backend.

    Memeriksa:
    1. Pengguna terautentikasi dan aktif.
    2. Kebijakan permission (READ, MODIFY, HIGH_RISK).
    3. Status konfirmasi eksplisit (approval signal).
    4. ApprovalContext jika tersedia (FIX-G).
    5. Kebijakan tambahan untuk high risk / tenant scope.

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
        # FIX-G: Validate ApprovalContext jika disediakan.
        if approval_ctx is not None:
            validate_approval_context(
                approval_ctx, user, tool_name,
                (context or {}).get("request", {}).arguments if hasattr((context or {}).get("request", {}), "arguments") else {},
            )
        return

    if permission == PermissionLevel.HIGH_RISK:
        if not confirmed:
            raise AuthorizationError(
                "Tool ini memerlukan confirmation kuat (permission level: HIGH_RISK). "
                "Operasi ini berisiko tinggi dan tidak boleh dijalankan tanpa "
                "persetujuan eksplisit dari user."
            )
        # FIX-G: HIGH_RISK requires ApprovalContext — simple confirmed=True is insufficient.
        if approval_ctx is None:
            raise AuthorizationError(
                "Tool HIGH_RISK memerlukan ApprovalContext yang terverifikasi, "
                "bukan hanya 'confirmed': true. "
                "Gunakan Configuration Flow eksplisit untuk tindakan berisiko tinggi."
            )
        validate_approval_context(
            approval_ctx, user, tool_name,
            (context or {}).get("request", {}).arguments if hasattr((context or {}).get("request", {}), "arguments") else {},
        )
        # Boundary tambahan: HIGH_RISK tidak pernah dieksekusi hanya karena
        # tool ada di allowlist — konfirmasi eksplisit + ApprovalContext wajib ada.
        return

    raise AuthorizationError(f"Permission level tidak dikenal: {permission}")
