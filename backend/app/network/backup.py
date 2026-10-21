"""
Backup Storage Management for N.O.V.A Configuration Engine.

Menangani penyimpanan backup fisik/native dan snapshot state terstruktur
dengan proteksi path traversal, permissions platform-aware (Linux/Windows),
sanitasi rahasia, dan retensi (PRD section 22, 29, 39).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from app.security.sanitization import sanitize_metadata

logger = logging.getLogger("nova.network.backup")

# Base directory untuk seluruh backup fisik
# Path relatif terhadap direktori kerja backend
BACKUP_BASE_DIR = Path("backups").resolve()

MAX_BACKUPS_PER_DEVICE = 10


def _set_platform_permissions(target_path: Path, is_dir: bool = False) -> None:
    """
    Menetapkan izin akses ketat secara sadar platform:
    - POSIX / Linux: dir 0700, file 0600 (owner only).
    - Windows: menggunakan icacls untuk membatasi akses hanya ke user saat ini.
    """
    if platform.system() == "Windows":
        try:
            # Pada Windows, gunakan icacls untuk menghapus inheritance dan memberi full control ke user saat ini
            username = os.environ.get("USERNAME")
            if username:
                # /inheritance:r (remove inherited ACEs)
                # /grant:r "%USERNAME%":(OI)(CI)F (grant Full control)
                cmd = [
                    "icacls",
                    str(target_path),
                    "/inheritance:r",
                    "/grant:r",
                    f"{username}:(OI)(CI)F" if is_dir else f"{username}:F",
                ]
                subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
        except Exception as exc:
            logger.warning("Gagal menetapkan izin file Windows via icacls: %s", exc)
    else:
        # Linux / POSIX
        try:
            mode = 0o700 if is_dir else 0o600
            os.chmod(target_path, mode)
        except Exception as exc:
            logger.warning("Gagal menetapkan izin file POSIX: %s", exc)


def get_device_backup_dir(owner_id: uuid.UUID | str, device_id: uuid.UUID | str) -> Path:
    """
    Mendapatkan path direktori backup untuk device tertentu dengan proteksi path traversal.
    """
    parsed_owner_id = owner_id if isinstance(owner_id, uuid.UUID) else uuid.UUID(str(owner_id))
    parsed_device_id = device_id if isinstance(device_id, uuid.UUID) else uuid.UUID(str(device_id))

    device_dir = (BACKUP_BASE_DIR / str(parsed_owner_id) / str(parsed_device_id)).resolve()

    # Proteksi Path Traversal: pastikan device_dir berada di dalam BACKUP_BASE_DIR
    if not str(device_dir).startswith(str(BACKUP_BASE_DIR)):
        raise ValueError("Path traversal terdeteksi dalam resolusi direktori backup.")

    device_dir.mkdir(parents=True, exist_ok=True)
    _set_platform_permissions(device_dir, is_dir=True)
    return device_dir


def save_state_snapshot(
    owner_id: uuid.UUID | str,
    device_id: uuid.UUID | str,
    state_data: dict[str, Any],
) -> dict[str, Any]:
    """
    Menyimpan snapshot state terstruktur perangkat sebelum atau setelah perubahan.
    1. Melewatkan data ke sanitization.py (Zero Secret Exposure).
    2. Menyimpan sebagai file JSON dengan nama yang digenerate backend.
    3. Mengembalikan backup_ref yang memuat relative path, SHA-256, dan ukuran file.
    
    CATATAN GAP KEAMANAN EKSPLISIT:
    File backup saat ini disimpan ter-sanitasi dan diproteksi permission OS (0600/icacls),
    namun belum dienkripsi at-rest menggunakan kunci vault/KMS. Enkripsi at-rest
    adalah item backlog terpisah bersamaan dengan pengamanan secret_reference.
    """
    device_dir = get_device_backup_dir(owner_id, device_id)

    # 1. Zero Secret Exposure — Sanitasi konten state sebelum persistensi ke disk
    sanitized_state = sanitize_metadata(state_data)
    json_bytes = json.dumps(sanitized_state, indent=2, sort_keys=True).encode("utf-8")

    # 2. Generate filename unik
    timestamp_str = time.strftime("%Y%m%d_%H%M%S")
    file_id = uuid.uuid4().hex[:12]
    filename = f"{timestamp_str}_{file_id}_snapshot.json"
    file_path = device_dir / filename

    # Verifikasi path traversal
    resolved_file = file_path.resolve()
    if not str(resolved_file).startswith(str(BACKUP_BASE_DIR)):
        raise ValueError("Path traversal terdeteksi dalam nama file backup.")

    # 3. Tulis file
    resolved_file.write_bytes(json_bytes)
    _set_platform_permissions(resolved_file, is_dir=False)

    # 4. Hitung SHA-256 dan ukuran
    sha256_hash = hashlib.sha256(json_bytes).hexdigest()
    size_bytes = len(json_bytes)

    # Path relatif terhadap BACKUP_BASE_DIR untuk portabilitas
    rel_path = str(resolved_file.relative_to(BACKUP_BASE_DIR)).replace("\\", "/")

    # 5. Terapkan retensi
    enforce_backup_retention(owner_id, device_id)

    return {
        "path": rel_path,
        "sha256": sha256_hash,
        "size_bytes": size_bytes,
        "backup_type": "state_snapshot_json",
    }


def verify_backup_file(backup_ref: dict[str, Any]) -> bool:
    """
    Memverifikasi keberadaan dan integritas file backup (mencocokkan SHA-256 hash)
    sebelum operasi rollback atau restore.
    """
    rel_path = backup_ref.get("path")
    expected_hash = backup_ref.get("sha256")
    if not rel_path or not expected_hash:
        return False

    full_path = (BACKUP_BASE_DIR / rel_path).resolve()
    if not str(full_path).startswith(str(BACKUP_BASE_DIR)):
        logger.error("Path traversal terdeteksi saat verifikasi backup: %s", rel_path)
        return False

    if not full_path.is_file():
        logger.error("File backup tidak ditemukan di disk: %s", full_path)
        return False

    content = full_path.read_bytes()
    actual_hash = hashlib.sha256(content).hexdigest()
    if actual_hash != expected_hash:
        logger.critical(
            "INTEGRITY FAILURE: Hash file backup %s tidak cocok! Diharapkan: %s, Aktual: %s",
            rel_path,
            expected_hash,
            actual_hash,
        )
        return False

    return True


def enforce_backup_retention(
    owner_id: uuid.UUID | str,
    device_id: uuid.UUID | str,
    max_backups: int = MAX_BACKUPS_PER_DEVICE,
) -> None:
    """
    Menghapus file backup tertua jika jumlah backup untuk device ini melebihi ambang batas.
    """
    try:
        device_dir = get_device_backup_dir(owner_id, device_id)
        backup_files = sorted(
            [f for f in device_dir.iterdir() if f.is_file()],
            key=lambda x: x.stat().st_mtime,
        )
        while len(backup_files) > max_backups:
            oldest = backup_files.pop(0)
            try:
                oldest.unlink(missing_ok=True)
                logger.info("Retensi backup: menghapus backup lama %s", oldest.name)
            except Exception as exc:
                logger.warning("Gagal menghapus file backup lama %s: %s", oldest.name, exc)
    except Exception as exc:
        logger.warning("Gagal menjalankan retensi backup: %s", exc)


def cleanup_device_backups(owner_id: uuid.UUID | str, device_id: uuid.UUID | str) -> None:
    """
    Membersihkan seluruh direktori backup perangkat saat perangkat dihapus oleh user.
    """
    try:
        device_dir = get_device_backup_dir(owner_id, device_id)
        for item in device_dir.iterdir():
            if item.is_file():
                item.unlink(missing_ok=True)
        device_dir.rmdir()
        logger.info("Seluruh backup untuk device %s telah dibersihkan.", device_id)
    except Exception as exc:
        logger.warning("Gagal membersihkan direktori backup device %s: %s", device_id, exc)
