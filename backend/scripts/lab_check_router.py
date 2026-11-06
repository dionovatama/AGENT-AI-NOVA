"""Tes lab: pin TLS + login librouteros lewat jembatan, TANPA Agent dan TANPA database.

Taruh di backend/scripts/lab_check_router.py, jalankan dari folder backend:

  # 1) lihat fingerprint cert router (untuk di-pin)
  python scripts/lab_check_router.py 192.168.56.10 --user admin --show-fingerprint

  # 2) pin benar -> harus tampil info router
  python scripts/lab_check_router.py 192.168.56.10 --user admin --fingerprint AA:BB:...

  # 3) pin salah -> harus DITOLAK sebelum login
  python scripts/lab_check_router.py 192.168.56.10 --user admin --fingerprint 00:11:...

Password ditanya lewat prompt (tidak lewat argumen/riwayat shell).
Channel di sini = TCP langsung ke router (pengganti Agent). Yang diuji nyata:
TLS RouterOS, cek pin, _connect_over_socket, perintah librouteros di thread.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import hashlib
import socket
import ssl
import sys

sys.path.insert(0, ".")

from app.network.relay_tls import RelayTlsError, open_pinned_tls_socket  # noqa: E402


class TcpChannel:
    """Pengganti RelayChannel: byte mentah ke router lewat TCP."""

    session_id = "lab"

    def __init__(self, reader, writer):
        self._r, self._w = reader, writer

    async def send(self, data: bytes) -> None:
        self._w.write(data)
        await self._w.drain()

    async def recv(self):
        try:
            data = await self._r.read(65536)
        except ConnectionError:
            return None
        return data or None

    async def close(self, reason: str = "requested") -> None:
        self._w.close()


def show_fingerprint(host: str, port: int) -> None:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=10) as raw:
        with ctx.wrap_socket(raw) as tls:
            der = tls.getpeercert(binary_form=True)
            print("TLS version :", tls.version())
            print("Cipher      :", tls.cipher()[0])
    fp = hashlib.sha256(der).hexdigest()
    print("SHA-256     :", ":".join(fp[i:i + 2].upper() for i in range(0, 64, 2)))


def query_router(sock, user: str, password: str) -> dict:
    """Jalan di THREAD, persis seperti tool mikrotik.*."""
    from app.tools.mikrotik import _connect_over_socket

    api = _connect_over_socket(sock, user, password)
    try:
        res = list(api.path("system", "resource"))[0]
        ident = list(api.path("system", "identity"))[0]
        return {"identity": ident.get("name"), "version": res.get("version"),
                "board": res.get("board-name"), "uptime": res.get("uptime")}
    finally:
        api.close()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("host")
    ap.add_argument("--port", type=int, default=8729)
    ap.add_argument("--user", default="admin")
    ap.add_argument("--fingerprint")
    ap.add_argument("--show-fingerprint", action="store_true")
    args = ap.parse_args()

    if args.show_fingerprint:
        show_fingerprint(args.host, args.port)
        return 0
    if not args.fingerprint:
        ap.error("--fingerprint wajib (atau pakai --show-fingerprint)")

    password = getpass.getpass(f"Password {args.user}@{args.host}: ")
    reader, writer = await asyncio.open_connection(args.host, args.port)
    channel = TcpChannel(reader, writer)
    try:
        tls = await open_pinned_tls_socket(channel, fingerprint=args.fingerprint)
    except RelayTlsError as exc:
        print(f"DITOLAK  reason={exc.reason}")
        if exc.observed:
            print("fingerprint yang dilihat:", exc.observed)
        print("-> password TIDAK dikirim (cek /log di router: tidak ada login).")
        return 2

    print("TLS OK, pin cocok. Login librouteros ...")
    try:
        info = await asyncio.to_thread(query_router, tls.sock, args.user, password)
        print("BERHASIL:", info)
        return 0
    except Exception as exc:  # noqa: BLE001 - skrip diagnosa: tampilkan jenis errornya
        print(f"GAGAL di librouteros: {type(exc).__name__}: {exc}")
        return 1
    finally:
        await tls.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))