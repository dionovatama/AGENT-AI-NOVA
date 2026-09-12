"""
Permission System — menentukan apakah sebuah tool request boleh
dieksekusi berdasarkan permission_level tool tersebut.

Sesuai PRD section 23:
- READ      : boleh dijalankan langsung tanpa konfirmasi tambahan.
- MODIFY    : butuh confirmation sesuai policy (minimal flag
              confirmed=True, yang di production akan berasal dari
              persetujuan user atas Configuration Preview).
- HIGH_RISK : butuh confirmation kuat + policy tambahan.

CATATAN SKELETON:
Ini BUKAN implementasi RBAC final. Untuk saat ini, permission MODIFY
dan HIGH_RISK sama-sama memakai flag confirmed=True sebagai placeholder.
Perbedaan keduanya (mis. multi-step confirmation, role-based check)
akan ditambahkan saat Phase 10 (Multi-Tenant) dan integrasi database
dikerjakan. Yang penting di skeleton ini: backend — bukan LLM — yang
memutuskan boleh/tidaknya eksekusi (Core Principle PRD).
"""

from app.tools.schemas import PermissionLevel


class PermissionDeniedError(Exception):
    """Dilempar saat permission tidak terpenuhi untuk tool request."""


def check_permission(permission_level: PermissionLevel, confirmed: bool) -> None:
    """
    Memvalidasi apakah request boleh lanjut ke tahap eksekusi.

    Tidak mengembalikan apa pun jika diizinkan; melempar
    PermissionDeniedError jika ditolak.
    """
    if permission_level == PermissionLevel.READ:
        return  # READ selalu diizinkan tanpa konfirmasi tambahan.

    if permission_level == PermissionLevel.MODIFY:
        if not confirmed:
            raise PermissionDeniedError(
                "Tool ini memerlukan confirmation (permission level: "
                "MODIFY). Kirim ulang request dengan 'confirmed': true "
                "setelah user menyetujui preview perubahan."
            )
        return

    if permission_level == PermissionLevel.HIGH_RISK:
        if not confirmed:
            raise PermissionDeniedError(
                "Tool ini memerlukan confirmation kuat (permission "
                "level: HIGH_RISK). Operasi ini berisiko tinggi dan "
                "tidak boleh dijalankan tanpa persetujuan eksplisit "
                "dari user."
            )
        return

    # Guard — seharusnya tidak pernah tercapai karena enum sudah exhaustive.
    raise PermissionDeniedError(
        f"Permission level tidak dikenal: {permission_level}"
    )