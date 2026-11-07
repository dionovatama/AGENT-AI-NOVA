"""Pilih jalur ke router: langsung (lokal) atau lewat Remote Agent (Phase 5).

Aturan:
  * Device TANPA ``RelayTarget`` (device_id cocok) -> jalur lokal lama, tidak berubah.
  * Device DENGAN ``RelayTarget`` -> HANYA lewat relay. Tidak pernah fallback ke
    koneksi langsung (IP privat pelanggan salah dijangkau / bocor ke jaringan lain).
  * Jalur relay wajib: connection_type ``api-ssl``, port ada di target.ports,
    ``tls_fingerprint`` terisi. Kurang satu -> ditolak (fail closed).

``remote_api_socket`` dipanggil dari event loop; soket yang diberikan dipakai oleh
thread librouteros (``asyncio.to_thread``) dan ditutup di sini setelah thread selesai.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

from app.agents.relay_service import RelayUnavailable, open_relay
from app.database.models import RelayTarget
from app.network.relay_tls import RelayTlsError, open_pinned_tls_socket
from app.tools.mikrotik import MikrotikConnectionError

if TYPE_CHECKING:
    import socket

    from app.database.models import Device
    from app.tools.context import ExecutionContext

logger = logging.getLogger("nova.network.remote_transport")

_TLS_MESSAGES = {
    "FINGERPRINT_MISMATCH": "Sertifikat router tidak cocok dengan fingerprint yang di-pin. "
                            "Koneksi ditolak. Jika sertifikat router memang diganti, perbarui pin.",
    "HANDSHAKE_FAILED": "Handshake TLS ke router gagal (pastikan API-SSL aktif dan punya sertifikat).",
    "HANDSHAKE_TIMEOUT": "Handshake TLS ke router timeout.",
    "NO_CERTIFICATE": "Router tidak menyodorkan sertifikat.",
    "CHANNEL_CLOSED": "Koneksi relay ke router terputus saat handshake TLS.",
}


class RemoteTransportError(MikrotikConnectionError):
    """Gagal membuka jalur remote. Pesan aman (tanpa IP, password, atau fingerprint)."""


def find_target_for_device(db, device: "Device") -> RelayTarget | None:
    """Target relay milik owner untuk device ini, atau None bila device berjalur lokal."""
    candidates = (
        db.query(RelayTarget)
        .filter(RelayTarget.device_id == device.id, RelayTarget.owner_id == device.owner_id)
        .order_by(RelayTarget.created_at)
        .all()
    )
    if not candidates:
        return None
    for t in candidates:  # target pertama yang mengizinkan port device
        if device.port in (t.ports or []):
            return t
    raise RemoteTransportError("Port device tidak terdaftar pada relay target mana pun.")


def find_relay_target(ctx: "ExecutionContext", device: "Device") -> RelayTarget | None:
    return find_target_for_device(ctx.db, device)


@asynccontextmanager
async def remote_api_socket(
    device: "Device", ctx: "ExecutionContext | None"
) -> AsyncIterator["socket.socket | None"]:
    """Yield soket blocking terpin ke router, atau ``None`` bila device berjalur lokal."""
    if ctx is None or ctx.db is None or ctx.user is None or device is None:
        yield None
        return
    target = find_relay_target(ctx, device)
    if target is None:
        yield None
        return

    if ctx.user.id != device.owner_id:  # defense in depth; resolusi device sudah owner-scoped
        raise RemoteTransportError("Device tidak ditemukan.")
    if (device.connection_type or "").strip().lower() != "api-ssl":
        raise RemoteTransportError(
            "Akses remote lewat Agent hanya mendukung connection_type 'api-ssl' (port 8729).")
    if not target.tls_fingerprint:
        raise RemoteTransportError(
            "Relay target belum punya fingerprint sertifikat (tls_fingerprint). "
            "Pin dulu fingerprint SHA-256 sertifikat API-SSL router.")

    try:
        channel = await open_relay(
            ctx.db, owner_id=ctx.user.id, target_id=target.id, port=device.port)
    except RelayUnavailable as exc:
        raise RemoteTransportError(f"Relay tidak tersedia: {exc.reason}") from None

    try:
        tls = await open_pinned_tls_socket(channel, fingerprint=target.tls_fingerprint)
    except RelayTlsError as exc:  # channel sudah ditutup oleh open_pinned_tls_socket
        logger.warning("remote tls failed device=%s target=%s reason=%s",
                       device.id, target.id, exc.reason)
        raise RemoteTransportError(
            _TLS_MESSAGES.get(exc.reason, "Gagal membangun TLS ke router.")) from None
    except BaseException:
        await channel.close("tls setup aborted")
        raise

    try:
        yield tls.sock
    finally:
        await tls.aclose()
