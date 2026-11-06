"""Pinned TLS over RelayChannel (Phase 5).

Server TLS palsu (self-signed, soket TCP lokal sungguhan) berperan sebagai MikroTik.
``FakeChannel`` meniru RelayChannel (send/recv/close). Klien memakai soket BLOCKING
dari thread -- persis cara librouteros memakainya -- jadi jembatan thread<->async
teruji dengan I/O nyata, bukan mock.

Tes ini hanya butuh stdlib + cryptography (untuk membuat sertifikat uji); tidak butuh DB.
"""
from __future__ import annotations

import asyncio
import datetime
import ssl
import tempfile
import os

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.network.relay_tls import (
    RelayTlsError, fingerprint_of_der, normalize_fingerprint, open_pinned_tls_socket,
)


# -- helper ---------------------------------------------------------------

def _make_cert(cn: str = "router.test"):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .sign(key, hashes.SHA256()))
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    fp = fingerprint_of_der(cert.public_bytes(serialization.Encoding.DER))
    return cert_pem, key_pem, fp


def _server_ctx(cert_pem: bytes, key_pem: bytes) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    with tempfile.TemporaryDirectory() as d:
        c, k = os.path.join(d, "c.pem"), os.path.join(d, "k.pem")
        open(c, "wb").write(cert_pem)
        open(k, "wb").write(key_pem)
        ctx.load_cert_chain(c, k)
    return ctx


class FakeChannel:
    """RelayChannel palsu: byte mentah ke/dari server TLS lokal lewat TCP nyata."""

    def __init__(self, reader, writer):
        self._r, self._w = reader, writer
        self.closed = False
        self.close_reason = None
        self.session_id = "test-session"

    async def send(self, data: bytes) -> None:
        if self.closed:
            raise ConnectionError("closed")
        self._w.write(data)
        await self._w.drain()

    async def recv(self):
        try:
            data = await self._r.read(65536)
        except (ConnectionError, asyncio.IncompleteReadError):
            return None
        return data or None

    async def close(self, reason: str = "requested") -> None:
        if self.closed:
            return
        self.closed = True
        self.close_reason = reason
        self._w.close()


class Router:
    """Server TLS: balas uppercase per potongan data; catat byte aplikasi yang diterima."""

    def __init__(self, ctx, mode="echo"):
        self.received = bytearray()
        self.mode = mode
        self.server = None
        self.port = 0
        self.ctx = ctx

    async def __aenter__(self):
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0, ssl=self.ctx)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *a):
        self.server.close()
        await self.server.wait_closed()

    async def _handle(self, reader, writer):
        try:
            if self.mode == "close_after_first":
                data = await reader.read(65536)
                self.received += data
                writer.close()
                return
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                self.received += data
                writer.write(data.upper())
                await writer.drain()
        except (ConnectionError, ssl.SSLError):
            pass
        finally:
            writer.close()


class SilentServer:
    """Terima TCP tapi tidak pernah bicara TLS (handshake menggantung)."""

    async def __aenter__(self):
        self.server = await asyncio.start_server(self._h, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *a):
        self.server.close()
        await self.server.wait_closed()

    async def _h(self, reader, writer):
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        writer.close()


async def _channel_to(port: int) -> FakeChannel:
    r, w = await asyncio.open_connection("127.0.0.1", port)
    return FakeChannel(r, w)


def _blocking_roundtrip(sock, payload: bytes) -> bytes:
    sock.sendall(payload)
    got = bytearray()
    while len(got) < len(payload):
        chunk = sock.recv(65536)
        if not chunk:
            break
        got += chunk
    return bytes(got)


async def _raises(coro, exc_type):
    try:
        await coro
    except exc_type as e:
        return e
    raise AssertionError(f"{exc_type.__name__} not raised")


# -- tes -------------------------------------------------------------------

def test_normalize_fingerprint_accepts_common_formats():
    plain = "ab" * 32
    colon = ":".join(["AB"] * 32)
    assert normalize_fingerprint(plain) == plain
    assert normalize_fingerprint(colon) == plain
    assert normalize_fingerprint("sha256:" + colon) == plain
    for bad in ("", "abc", "zz" * 32, "ab" * 31, "ab" * 33):
        try:
            normalize_fingerprint(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad!r}")


async def test_matching_fingerprint_passes_bytes_both_ways():
    cert, key, fp = _make_cert()
    async with Router(_server_ctx(cert, key)) as router:
        ch = await _channel_to(router.port)
        tls = await open_pinned_tls_socket(ch, fingerprint=fp)
        out = await asyncio.to_thread(_blocking_roundtrip, tls.sock, b"hello routeros")
        assert out == b"HELLO ROUTEROS"
        await tls.aclose()
        assert ch.closed


async def test_colon_uppercase_pin_is_accepted():
    cert, key, fp = _make_cert()
    pretty = ":".join(fp[i:i + 2].upper() for i in range(0, 64, 2))
    async with Router(_server_ctx(cert, key)) as router:
        ch = await _channel_to(router.port)
        tls = await open_pinned_tls_socket(ch, fingerprint=pretty)
        assert await asyncio.to_thread(_blocking_roundtrip, tls.sock, b"x") == b"X"
        await tls.aclose()


async def test_wrong_fingerprint_is_rejected_and_no_app_data_sent():
    cert, key, fp = _make_cert()
    other_fp = "00" * 32
    async with Router(_server_ctx(cert, key)) as router:
        ch = await _channel_to(router.port)
        err = await _raises(open_pinned_tls_socket(ch, fingerprint=other_fp), RelayTlsError)
        assert err.reason == "FINGERPRINT_MISMATCH"
        assert err.observed == fp
        assert fp not in str(err)  # pesan aman; fingerprint hanya di atribut
        assert ch.closed
        await asyncio.sleep(0.1)
        assert bytes(router.received) == b""  # tidak ada byte aplikasi yang bocor


async def test_swapped_certificate_is_rejected():
    """Router asli di-pin, lalu penyerang (cert lain) menjawab di alamat yang sama."""
    _, _, pinned_fp = _make_cert("real-router")
    evil_cert, evil_key, evil_fp = _make_cert("evil")
    assert pinned_fp != evil_fp
    async with Router(_server_ctx(evil_cert, evil_key)) as router:
        ch = await _channel_to(router.port)
        err = await _raises(open_pinned_tls_socket(ch, fingerprint=pinned_fp), RelayTlsError)
        assert err.reason == "FINGERPRINT_MISMATCH"
        assert bytes(router.received) == b""


async def test_non_tls_peer_fails_handshake():
    async def plain(reader, writer):
        writer.write(b"HTTP/1.1 400 nope\r\n\r\n")
        await writer.drain()
        await asyncio.sleep(0.2)
        writer.close()

    server = await asyncio.start_server(plain, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        ch = await _channel_to(port)
        err = await _raises(open_pinned_tls_socket(ch, fingerprint="aa" * 32), RelayTlsError)
        assert err.reason in {"HANDSHAKE_FAILED", "CHANNEL_CLOSED"}
        assert ch.closed
    finally:
        server.close()
        await server.wait_closed()


async def test_handshake_timeout():
    async with SilentServer() as srv:
        ch = await _channel_to(srv.port)
        err = await _raises(
            open_pinned_tls_socket(ch, fingerprint="aa" * 32, handshake_timeout=0.3), RelayTlsError)
        assert err.reason == "HANDSHAKE_TIMEOUT"
        assert ch.closed


async def test_peer_closes_gives_eof_not_hang():
    cert, key, fp = _make_cert()
    async with Router(_server_ctx(cert, key), mode="close_after_first") as router:
        ch = await _channel_to(router.port)
        tls = await open_pinned_tls_socket(ch, fingerprint=fp, io_timeout=3.0)

        def go():
            tls.sock.sendall(b"bye")
            return tls.sock.recv(1024)  # b"" = EOF; hang akan kena io_timeout

        assert await asyncio.wait_for(asyncio.to_thread(go), 5) == b""
        await tls.aclose()
        assert ch.closed


async def test_local_close_closes_channel():
    """Thread menutup soketnya (seperti api.close()) -> channel ikut ditutup, tanpa kebocoran."""
    cert, key, fp = _make_cert()
    async with Router(_server_ctx(cert, key)) as router:
        ch = await _channel_to(router.port)
        tls = await open_pinned_tls_socket(ch, fingerprint=fp)
        await asyncio.to_thread(_blocking_roundtrip, tls.sock, b"ping")
        await asyncio.to_thread(tls.sock.close)
        for _ in range(50):
            if ch.closed:
                break
            await asyncio.sleep(0.05)
        assert ch.closed
        await tls.aclose()  # idempoten


async def test_large_payload_roundtrip():
    cert, key, fp = _make_cert()
    payload = bytes(range(65, 91)) * 40000  # ~1 MB huruf besar, upper() tidak mengubahnya
    async with Router(_server_ctx(cert, key)) as router:
        ch = await _channel_to(router.port)
        tls = await open_pinned_tls_socket(ch, fingerprint=fp, io_timeout=15.0)

        def go():
            import threading
            result = bytearray()

            def reader():
                while len(result) < len(payload):
                    c = tls.sock.recv(65536)
                    if not c:
                        break
                    result.extend(c)

            t = threading.Thread(target=reader)
            t.start()
            tls.sock.sendall(payload)
            t.join(20)
            return bytes(result)

        assert await asyncio.wait_for(asyncio.to_thread(go), 30) == payload
        await tls.aclose()


async def test_aclose_is_idempotent_and_closes_channel():
    cert, key, fp = _make_cert()
    async with Router(_server_ctx(cert, key)) as router:
        ch = await _channel_to(router.port)
        tls = await open_pinned_tls_socket(ch, fingerprint=fp)
        await tls.aclose()
        await tls.aclose()
        assert ch.closed
