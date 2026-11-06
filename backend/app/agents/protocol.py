"""
Protokol WebSocket Remote Agent (versi 1) -- JSON text frame.

Token TIDAK pernah ada di URL (masuk access log) maupun log aplikasi.
Autentikasi lewat frame pertama ('auth') setelah handshake, dibatasi
timeout. Endpoint: wss://<host>/ws/agent/<agent_uuid>

Agent -> Server
    {"type":"auth","protocol_version":1,"token":"nova_agt_...",
     "os":"Windows 11 x64","agent_version":"0.1.0"}
    {"type":"heartbeat","seq":12}            (seq opsional)
    {"type":"bye"}                           (shutdown bersih)

Server -> Agent
    {"type":"registered","protocol_version":1,"agent_id":"...",
     "connection_id":"...","heartbeat_interval_seconds":30,
     "heartbeat_timeout_seconds":90,"server_time":"..."}
    {"type":"heartbeat_ack","seq":12,"server_time":"..."}
    {"type":"error","code":"protocol_error","message":"..."}

Close code (4000-4999 = privat aplikasi):
    1000/1001  penutupan bersih          1003  frame biner tidak didukung
    1008       request ditolak (UUID/TLS) 1009  pesan terlalu besar
    1011       error internal backend
    4009       digantikan koneksi baru / agent dihapus / token di-rotate
    4400       pelanggaran protokol
    4401       autentikasi gagal
    4408       timeout (auth atau heartbeat)
    4429       rate limit terlampaui (percobaan auth gagal / pesan terlalu sering)

Catatan untuk Agent: 4401, 4009, dan 4429 JANGAN di-retry agresif. 4009 yang
berulang biasanya berarti dua instance agent memakai kredensial yang
sama dan saling mengusir.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime

PROTOCOL_VERSION = 1


class CloseCode:
    NORMAL = 1000
    GOING_AWAY = 1001
    UNSUPPORTED = 1003
    POLICY = 1008
    TOO_BIG = 1009
    INTERNAL = 1011
    REPLACED = 4009
    PROTOCOL = 4400
    AUTH_FAILED = 4401
    TIMEOUT = 4408
    RATE_LIMITED = 4429


# Close code yang dianggap "agent pamit baik-baik" -> status offline.
CLEAN_CLOSE_CODES = frozenset({CloseCode.NORMAL, CloseCode.GOING_AWAY})


class SocketClosed(Exception):
    """Peer menutup koneksi (atau kirim gagal karena socket sudah mati)."""

    def __init__(self, code: int = 1006, reason: str = "") -> None:
        super().__init__(f"socket closed code={code}")
        self.code = code
        self.reason = reason


class UnsupportedFrame(Exception):
    """Frame biner diterima; protokol hanya memakai teks."""


class ProtocolError(Exception):
    """Pesan tidak valid. str(exc) aman dikirim ke peer (tanpa data sensitif)."""


class MessageTooLarge(ProtocolError):
    pass


@dataclass(frozen=True)
class AuthMessage:
    token: str
    os: str
    agent_version: str
    hostname: str | None = None

    def __repr__(self) -> str:  # token tidak boleh bocor lewat repr/log
        return f"AuthMessage(os={self.os!r}, agent_version={self.agent_version!r}, hostname={self.hostname!r})"


@dataclass(frozen=True)
class ClientMessage:
    type: str  # "heartbeat" | "bye" | relay message type
    seq: int | None = None


def parse_agent_id(raw: object) -> uuid.UUID | None:
    """UUID v4 dalam bentuk kanonik huruf kecil/besar saja; selain itu None."""
    if not isinstance(raw, str) or len(raw) != 36:
        return None
    try:
        parsed = uuid.UUID(raw)
    except ValueError:
        return None
    if parsed.version != 4 or str(parsed) != raw.lower():
        return None
    return parsed


def _load(raw: str, max_bytes: int) -> dict:
    if len(raw.encode("utf-8", "ignore")) > max_bytes:
        raise MessageTooLarge("message too large")
    try:
        data = json.loads(raw)
    except ValueError:
        raise ProtocolError("malformed JSON") from None
    if not isinstance(data, dict) or not isinstance(data.get("type"), str):
        raise ProtocolError("message must be an object with a string 'type'")
    return data


def _clean_text(value: object, field: str, max_len: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProtocolError(f"'{field}' is required")
    value = value.strip()
    if len(value) > max_len or not all(ch.isprintable() for ch in value):
        raise ProtocolError(f"'{field}' is invalid")
    return value


_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+_-]{0,31}$")


def parse_auth(raw: str, max_bytes: int) -> AuthMessage:
    data = _load(raw, max_bytes)
    if data["type"] != "auth":
        raise ProtocolError("first message must be 'auth'")
    if data.get("protocol_version") != PROTOCOL_VERSION:
        raise ProtocolError("unsupported protocol_version")
    token = data.get("token")
    if not isinstance(token, str):
        raise ProtocolError("'token' is required")
    agent_version = _clean_text(data.get("agent_version"), "agent_version", 32)
    if not _VERSION_RE.fullmatch(agent_version):
        raise ProtocolError("'agent_version' is invalid")
    # hostname bersifat informasi opsional: nilai tak valid diabaikan,
    # bukan alasan menolak autentikasi.
    hostname = data.get("hostname")
    if not (isinstance(hostname, str) and hostname.strip()
            and len(hostname.strip()) <= 255 and hostname.strip().isprintable()):
        hostname = None
    else:
        hostname = hostname.strip()
    return AuthMessage(
        token=token,
        os=_clean_text(data.get("os"), "os", 50),
        agent_version=agent_version,
        hostname=hostname,
    )


def parse_client_message(raw: str, max_bytes: int) -> ClientMessage:
    data = _load(raw, max_bytes)
    msg_type = data["type"]
    if msg_type == "bye":
        return ClientMessage(type="bye")
    if msg_type in {"OPEN_TUNNEL", "TUNNEL_OPENED", "TUNNEL_ERROR", "DATA", "CLOSE_TUNNEL"}:
        return ClientMessage(type=msg_type)
    if msg_type == "heartbeat":
        seq = data.get("seq")
        if seq is not None and (
            isinstance(seq, bool) or not isinstance(seq, int) or not 0 <= seq < 2**53
        ):
            raise ProtocolError("'seq' must be a non-negative integer")
        return ClientMessage(type="heartbeat", seq=seq)
    raise ProtocolError("unknown message type")


def registered_message(
    agent_id: uuid.UUID,
    connection_id: uuid.UUID,
    interval: float,
    timeout: float,
    now: datetime,
) -> dict:
    return {
        "type": "registered",
        "protocol_version": PROTOCOL_VERSION,
        "agent_id": str(agent_id),
        "connection_id": str(connection_id),
        "heartbeat_interval_seconds": interval,
        "heartbeat_timeout_seconds": timeout,
        "server_time": now.isoformat(),
    }


def heartbeat_ack_message(seq: int | None, now: datetime) -> dict:
    return {"type": "heartbeat_ack", "seq": seq, "server_time": now.isoformat()}


def error_message(code: str, message: str) -> dict:
    return {"type": "error", "code": code, "message": message}
