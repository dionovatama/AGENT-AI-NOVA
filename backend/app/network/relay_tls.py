"""TLS dengan pin sertifikat di atas ``RelayChannel`` (Phase 5).

Masalah yang dipecahkan
-----------------------
librouteros itu SYNC (soket blocking, dipanggil dari ``asyncio.to_thread``),
sedangkan ``RelayChannel`` itu ASYNC (``await send/recv``). Jembatannya:

    thread librouteros --(socket blocking)--> app_sock
                                                 |  socketpair (lokal, tanpa jaringan)
    event loop  <---------- pump_sock <----------+
        |  plaintext <-> TLS (ssl.MemoryBIO)
        v
    RelayChannel  ->  WSS  ->  Agent  ->  TCP  ->  MikroTik (API-SSL)

TLS dihentikan DI BACKEND, bukan di Agent. Agent hanya meneruskan byte
terenkripsi, jadi Agent tidak pernah melihat password RouterOS.

Kepercayaan sertifikat = PIN fingerprint SHA-256 (bukan CA)
-----------------------------------------------------------
MikroTik biasanya self-signed. Handshake memakai ``verify_mode=CERT_NONE``
HANYA karena Python tidak bisa memvalidasi rantai self-signed; itu BUKAN
"tanpa verifikasi". Segera setelah handshake selesai dan SEBELUM satu byte
aplikasi pun mengalir (termasuk login/password), DER sertifikat peer dihash
dan dibandingkan dengan pin (``hmac.compare_digest``). Beda -> channel
ditutup, ``RelayTlsError("FINGERPRINT_MISMATCH")``.

Catatan: router harus punya sertifikat yang ditetapkan ke service api-ssl.
Tanpa sertifikat RouterOS memakai anonymous-DH (tidak ada sertifikat untuk
di-pin; OpenSSL modern juga menolaknya) -> handshake gagal. Itu disengaja.

Modul ini sengaja hanya memakai stdlib supaya bisa diuji tanpa DB/librouteros.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import re
import socket
import ssl
from typing import Any

logger = logging.getLogger("nova.network.relay_tls")

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_READ_CHUNK = 16 * 1024


class RelayTlsError(Exception):
    """Gagal membangun TLS terpin. ``reason`` adalah kode tetap dan aman ditampilkan."""

    def __init__(self, reason: str, message: str = "", *, observed: str | None = None) -> None:
        super().__init__(message or reason)
        self.reason = reason
        # Fingerprint yang dilihat (info publik, berguna untuk re-pin). Hanya untuk log/UI
        # operator; JANGAN dimasukkan ke pesan yang dikirim ke LLM.
        self.observed = observed


def normalize_fingerprint(value: str) -> str:
    """Terima ``AA:BB:..``, ``aabb..``, atau ``sha256:aabb..`` -> 64 hex huruf kecil."""
    if not isinstance(value, str):
        raise ValueError("fingerprint must be a string")
    v = value.strip().lower()
    if v.startswith("sha256:"):
        v = v[len("sha256:"):]
    v = v.replace(":", "").replace(" ", "")
    if not _HEX64.fullmatch(v):
        raise ValueError("fingerprint must be a SHA-256 hash (64 hex characters)")
    return v


def fingerprint_of_der(der: bytes) -> str:
    return hashlib.sha256(der).hexdigest()


def verify_certificate_pin(der: bytes, expected_fingerprint: str) -> str:
    """Shared SHA-256 pin verification for relay and direct local TLS sockets."""
    if not der:
        raise RelayTlsError("NO_CERTIFICATE", "peer presented no certificate")
    expected = normalize_fingerprint(expected_fingerprint)
    observed = fingerprint_of_der(der)
    if not hmac.compare_digest(observed, expected):
        raise RelayTlsError(
            "FINGERPRINT_MISMATCH",
            "peer certificate does not match the configured fingerprint",
            observed=observed,
        )
    return observed


def _client_context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    # Rantai CA tidak dipakai; kepercayaan dari pin (lihat docstring modul).
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class PinnedTlsSocket:
    """Handle sesi. ``sock`` = soket BLOCKING untuk thread librouteros."""

    def __init__(self, *, sock: socket.socket, pump_sock: socket.socket, channel: Any,
                 sslobj: ssl.SSLObject, incoming: ssl.MemoryBIO, outgoing: ssl.MemoryBIO,
                 send_lock: asyncio.Lock) -> None:
        self.sock = sock
        self._pump_sock = pump_sock
        self._channel = channel
        self._ssl = sslobj
        self._incoming = incoming
        self._outgoing = outgoing
        self._send_lock = send_lock
        self._task: asyncio.Task | None = None
        self._cleaned = False
        self.close_reason: str | None = None

    # -- pompa ------------------------------------------------------------

    async def _flush(self) -> None:
        # Baca BIO DI DALAM lock supaya urutan byte ke channel terjaga
        # walau dua task (tx/rx) sama-sama ingin mengirim.
        async with self._send_lock:
            data = self._outgoing.read()
            if data:
                await self._channel.send(data)

    async def _tx(self, loop: asyncio.AbstractEventLoop) -> str:
        """thread librouteros -> TLS -> channel."""
        while True:
            data = await loop.sock_recv(self._pump_sock, _READ_CHUNK)
            if not data:
                return "local_closed"
            view = memoryview(data)
            while view:
                n = self._ssl.write(view)
                view = view[n:]
            await self._flush()

    async def _rx(self, loop: asyncio.AbstractEventLoop) -> str:
        """channel -> TLS -> thread librouteros."""
        while True:
            chunk = await self._channel.recv()
            if chunk is None:
                return "channel_closed"
            self._incoming.write(chunk)
            while True:
                try:
                    plain = self._ssl.read(_READ_CHUNK)
                except ssl.SSLWantReadError:
                    break
                except ssl.SSLZeroReturnError:
                    return "peer_close_notify"
                if not plain:
                    # SSLObject.read() mengembalikan b'' (bukan exception) saat peer
                    # mengirim close_notify. Itu EOF: tanpa ini kita menunggu TCP
                    # yang tidak akan ditutup peer sebelum kita membalas.
                    return "peer_close_notify"
                await loop.sock_sendall(self._pump_sock, plain)
            await self._flush()  # alert / key update / session ticket

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        tx = asyncio.ensure_future(self._tx(loop))
        rx = asyncio.ensure_future(self._rx(loop))
        try:
            done, pending = await asyncio.wait({tx, rx}, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for t in done:
                exc = t.exception()
                self.close_reason = type(exc).__name__ if exc else t.result()
        except asyncio.CancelledError:
            tx.cancel()
            rx.cancel()
            await asyncio.gather(tx, rx, return_exceptions=True)
            self.close_reason = self.close_reason or "cancelled"
            raise
        finally:
            await self._cleanup()

    async def _cleanup(self) -> None:
        if self._cleaned:
            return
        self._cleaned = True
        try:
            await self._channel.close("tls session ended")
        except Exception:  # noqa: BLE001 -- cleanup tidak boleh melempar
            logger.debug("relay channel close failed", exc_info=True)
        # Menutup pump_sock -> app_sock (thread librouteros) mendapat EOF, bukan hang.
        for s in (self._pump_sock,):
            try:
                s.close()
            except OSError:
                pass

    # -- API --------------------------------------------------------------

    def start(self) -> None:
        self._task = asyncio.ensure_future(self._run())

    async def aclose(self) -> None:
        """Idempoten. Aman dipanggil dari event loop setelah thread selesai."""
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self._cleanup()
        try:
            self.sock.close()
        except OSError:
            pass


async def open_pinned_tls_socket(
    channel: Any, *, fingerprint: str, handshake_timeout: float = 10.0, io_timeout: float = 30.0,
) -> PinnedTlsSocket:
    """Handshake TLS lewat ``channel``, cek pin, lalu kembalikan soket blocking.

    ``channel`` cukup punya ``async send(bytes)``, ``async recv() -> bytes|None``,
    ``async close(reason)``. Pada kegagalan apa pun channel DITUTUP dan
    ``RelayTlsError`` dilempar -- tidak ada byte aplikasi yang pernah dikirim.
    """
    expected = normalize_fingerprint(fingerprint)
    incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
    sslobj = _client_context().wrap_bio(incoming, outgoing, server_side=False)
    send_lock = asyncio.Lock()

    async def _flush() -> None:
        async with send_lock:
            data = outgoing.read()
            if data:
                await channel.send(data)

    async def _handshake() -> None:
        while True:
            try:
                sslobj.do_handshake()
                await _flush()  # Finished milik client (TLS1.3) harus terkirim
                return
            except ssl.SSLWantReadError:
                await _flush()
                chunk = await channel.recv()
                if chunk is None:
                    raise RelayTlsError("CHANNEL_CLOSED", "channel closed during TLS handshake")
                incoming.write(chunk)
            except ssl.SSLWantWriteError:
                await _flush()

    async def _abort(reason: str) -> None:
        try:
            await channel.close(reason)
        except Exception:  # noqa: BLE001
            logger.debug("relay channel close failed", exc_info=True)

    try:
        await asyncio.wait_for(_handshake(), handshake_timeout)
    except asyncio.TimeoutError:
        await _abort("tls handshake timeout")
        raise RelayTlsError("HANDSHAKE_TIMEOUT", "TLS handshake timed out") from None
    except RelayTlsError:
        await _abort("tls handshake failed")
        raise
    except ssl.SSLError:
        await _abort("tls handshake failed")
        raise RelayTlsError("HANDSHAKE_FAILED", "TLS handshake failed") from None
    except Exception:  # send() pada channel yang sudah tertutup, dsb.
        await _abort("tls handshake failed")
        raise RelayTlsError("CHANNEL_CLOSED", "relay channel failed during TLS handshake") from None

    der = sslobj.getpeercert(binary_form=True)
    if not der:
        await _abort("no peer certificate")
        raise RelayTlsError("NO_CERTIFICATE", "router presented no certificate")
    try:
        verify_certificate_pin(der, expected)
    except RelayTlsError as exc:
        logger.warning("relay tls pin mismatch session=%s reason=%s",
                       getattr(channel, "session_id", "?"), exc.reason)
        await _abort("fingerprint mismatch")
        raise

    app_sock, pump_sock = socket.socketpair()
    app_sock.settimeout(io_timeout)
    pump_sock.setblocking(False)
    handle = PinnedTlsSocket(sock=app_sock, pump_sock=pump_sock, channel=channel, sslobj=sslobj,
                             incoming=incoming, outgoing=outgoing, send_lock=send_lock)
    handle.start()
    return handle
