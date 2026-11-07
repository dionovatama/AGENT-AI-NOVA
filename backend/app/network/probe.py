"""Probe jangkauan device lewat Remote Agent (Phase 6).

Yang dicek: relay terbuka + handshake TLS berhasil + sertifikat cocok dengan pin.
TIDAK login ke RouterOS dan tidak mengirim credential. ``online`` berarti
"router terjangkau lewat Agent dan sertifikatnya sesuai pin", bukan "perintah berhasil".

Keamanan: hanya device yang punya relay target yang di-probe. Device berjalur
langsung TIDAK di-probe dari backend (akan menjadikan backend pemindai port
untuk host yang diketik pengguna).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.agents.relay_service import RelayUnavailable, open_relay
from app.database.models import Device
from app.network.relay_tls import RelayTlsError, open_pinned_tls_socket
from app.network.remote_transport import _TLS_MESSAGES, RemoteTransportError, find_target_for_device

logger = logging.getLogger("nova.network.probe")

MIN_INTERVAL_SECONDS = 5.0   # tekan "refresh" berulang tidak membanjiri Agent
PROBE_TIMEOUT_SECONDS = 15.0
_MAX_DETAIL = 200


@dataclass(frozen=True)
class ProbeResult:
    reachability: str            # online | offline | unknown
    detail: str
    checked_at: datetime
    cached: bool = False


def _save(db: Session, device: Device, reachability: str, detail: str) -> ProbeResult:
    now = datetime.now(timezone.utc)
    device.reachability = reachability
    device.last_checked_at = now
    device.last_check_detail = detail[:_MAX_DETAIL]
    db.commit()
    return ProbeResult(reachability, device.last_check_detail, now)


async def probe_device(db: Session, device: Device) -> ProbeResult:
    now = datetime.now(timezone.utc)
    last = device.last_checked_at
    if last is not None:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if (now - last).total_seconds() < MIN_INTERVAL_SECONDS:
            return ProbeResult(device.reachability, device.last_check_detail or "", last, cached=True)

    try:
        target = find_target_for_device(db, device)
    except RemoteTransportError as exc:
        return _save(db, device, "offline", str(exc))
    if target is None:
        return _save(db, device, "unknown", "Tidak lewat Agent; NOVA tidak mem-probe koneksi langsung.")
    if (device.connection_type or "").strip().lower() != "api-ssl":
        return _save(db, device, "offline", "Jalur Agent hanya mendukung api-ssl.")
    if not target.tls_fingerprint:
        return _save(db, device, "offline", "Relay target belum punya fingerprint (pin).")

    async def _run() -> None:
        channel = await open_relay(db, owner_id=device.owner_id, target_id=target.id, port=device.port)
        tls = await open_pinned_tls_socket(channel, fingerprint=target.tls_fingerprint)
        await tls.aclose()   # cukup sampai handshake + pin; tanpa login

    try:
        await asyncio.wait_for(_run(), PROBE_TIMEOUT_SECONDS)
    except RelayUnavailable as exc:
        return _save(db, device, "offline", f"Relay tidak tersedia: {exc.reason}")
    except RelayTlsError as exc:
        return _save(db, device, "offline", _TLS_MESSAGES.get(exc.reason, "Gagal membangun TLS ke router."))
    except asyncio.TimeoutError:
        return _save(db, device, "offline", "Timeout saat menjangkau router lewat Agent.")
    except Exception:  # noqa: BLE001 - jangan bocorkan detail internal ke pengguna
        logger.exception("probe failed device=%s", device.id)
        return _save(db, device, "offline", "Probe gagal (kesalahan tak terduga).")
    return _save(db, device, "online", "Router terjangkau lewat Agent; sertifikat cocok dengan pin.")
