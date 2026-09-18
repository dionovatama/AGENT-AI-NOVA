"""
Audit Log Retention — pembersihan otomatis baris `audit_logs` yang sudah
lewat masa retensi (PRD section 32/33).

KEPUTUSAN DESAIN: ini SENGAJA otomatis & terjadwal, BUKAN tombol hapus
manual di UI/API. Fitur hapus yang gampang diakses dari aplikasi
melemahkan fungsi audit_logs sebagai bukti — siapa pun bisa menutupi
jejak tindakannya sendiri kalau itu ada. Retention policy tetap
membersihkan data lama supaya tabel tidak tumbuh tanpa henti, tapi lewat
jalur yang konsisten (policy tetap, bukan keputusan sesaat user) dan
tidak bisa dipicu sembarang waktu dari dalam aplikasi.

Tidak pakai APScheduler/Celery — project ini belum punya infra worker
terpisah (lihat PRD: "Redis jika diperlukan, Worker system jika
diperlukan" — opsional, belum diimplementasikan). Loop asyncio
in-process sederhana ini cukup untuk skala single-instance saat ini.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.config import settings
from app.database.models import AuditLog
from app.database.session import SessionLocal

logger = logging.getLogger("nova.audit.retention")

# Jarak antar pengecekan. Audit log lama tidak mendesak untuk dihapus
# detik itu juga begitu melewati batas retensi — sekali sehari cukup.
_CHECK_INTERVAL_SECONDS = 24 * 60 * 60


def purge_old_audit_logs() -> int:
    """
    Menghapus baris audit_logs yang created_at lebih lama dari
    AUDIT_LOG_RETENTION_DAYS. Mengembalikan jumlah baris yang dihapus.

    Sinkron secara sengaja (SessionLocal bukan async session) —
    konsisten dengan pola app.security.audit lainnya. Dipanggil lewat
    asyncio.to_thread() dari audit_retention_loop() supaya tidak
    memblokir event loop utama.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.audit_log_retention_days)

    db = SessionLocal()
    try:
        result = db.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
        db.commit()
        deleted_count = result.rowcount or 0
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.error("Gagal menjalankan audit log retention purge: %s", exc)
        return 0
    finally:
        db.close()

    if deleted_count > 0:
        logger.info(
            "Audit log retention: %d baris lebih tua dari %d hari dihapus (cutoff=%s).",
            deleted_count,
            settings.audit_log_retention_days,
            cutoff.isoformat(),
        )
    return deleted_count


async def audit_retention_loop() -> None:
    """
    Background task — dipicu sekali saat startup (lihat app/main.py),
    lalu mengecek retensi setiap _CHECK_INTERVAL_SECONDS selamanya
    sampai aplikasi berhenti.
    """
    while True:
        try:
            await asyncio.to_thread(purge_old_audit_logs)
        except Exception as exc:  # noqa: BLE001
            # Retention gagal TIDAK BOLEH menjatuhkan aplikasi -- ini
            # housekeeping, bukan request-critical path.
            logger.error("audit_retention_loop: iterasi gagal: %s", exc)
        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)