"""Client side of the NOVA Remote Agent protocol, version 1 (Phase A).

Source of truth: ``backend/app/agents/protocol.py`` and ``manager.py``.

Agent -> Server
    {"type":"auth","protocol_version":1,"token":...,"os":...,"agent_version":...}
    {"type":"heartbeat","seq":N}
    {"type":"bye"}

Server -> Agent
    {"type":"registered","protocol_version":1,"agent_id":...,"connection_id":...,
     "heartbeat_interval_seconds":F,"heartbeat_timeout_seconds":F,"server_time":ISO}
    {"type":"heartbeat_ack","seq":N|null,"server_time":ISO}
    {"type":"error","code":...,"message":...}

This module is pure (stdlib only, no I/O) so it can be unit tested without a
socket. Nothing here ever logs or formats the token.
"""

from __future__ import annotations

import json
import math
import re
import uuid
from dataclasses import dataclass
from datetime import datetime

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 65536  # backend: agent_max_message_bytes default

# Sanity bounds for server-supplied timings (a misbehaving server must not be
# able to make the agent sleep for days or spin in a tight loop).
MAX_HEARTBEAT_INTERVAL = 3600.0
MAX_HEARTBEAT_TIMEOUT = 7200.0

_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+_-]{0,31}$")  # same as backend
MAX_OS_LENGTH = 50  # same as backend


class CloseCode:
    NORMAL = 1000
    GOING_AWAY = 1001
    PROTOCOL_ERROR = 1002  # sent by the agent on malformed server traffic
    UNSUPPORTED = 1003
    POLICY = 1008
    TOO_BIG = 1009
    INTERNAL = 1011
    REPLACED = 4009
    PROTOCOL = 4400
    AUTH_FAILED = 4401
    TIMEOUT = 4408
    RATE_LIMITED = 4429


class ProtocolViolation(Exception):
    """The server sent something that is not valid protocol traffic."""


class HeartbeatMismatch(ProtocolViolation):
    """heartbeat_ack carried a seq different from the heartbeat in flight."""


class ServerError(Exception):
    """The server sent an explicit ``error`` message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"server error: {code}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Registered:
    agent_id: str
    connection_id: str
    heartbeat_interval: float
    heartbeat_timeout: float
    server_time: str


# ---------------------------------------------------------------------------
# Identity helpers
# ---------------------------------------------------------------------------

def parse_agent_id(raw: object) -> uuid.UUID | None:
    """UUID v4 in canonical 36-char form (case-insensitive), else None.

    Mirrors the backend, which closes anything else with 1008 before accept
    (a client then sees an HTTP 403 on the handshake)."""
    if not isinstance(raw, str) or len(raw) != 36:
        return None
    try:
        parsed = uuid.UUID(raw)
    except ValueError:
        return None
    if parsed.version != 4 or str(parsed) != raw.lower():
        return None
    return parsed


def normalize_os_name(raw: str) -> str:
    """Make an OS description acceptable to the backend (printable, <= 50)."""
    cleaned = "".join(ch for ch in str(raw) if ch.isprintable()).strip()
    cleaned = " ".join(cleaned.split())[:MAX_OS_LENGTH].strip()
    return cleaned or "unknown"


def is_valid_agent_version(value: object) -> bool:
    return isinstance(value, str) and _VERSION_RE.fullmatch(value) is not None


# ---------------------------------------------------------------------------
# Outgoing messages
# ---------------------------------------------------------------------------

def _dump(payload: dict) -> str:
    return json.dumps(payload, separators=(",", ":"))


def build_auth_message(
    token: str, os_name: str, agent_version: str, hostname: str | None = None
) -> str:
    message = {
        "type": "auth",
        "protocol_version": PROTOCOL_VERSION,
        "token": token,
        "os": os_name,
        "agent_version": agent_version,
    }
    if hostname:
        message["hostname"] = hostname[:255]
    return _dump(message)


def build_heartbeat_message(seq: int) -> str:
    return _dump({"type": "heartbeat", "seq": seq})


BYE_MESSAGE = _dump({"type": "bye"})


# ---------------------------------------------------------------------------
# Incoming messages
# ---------------------------------------------------------------------------

def _safe_text(value: object, limit: int = 64) -> str:
    """Bounded printable rendering of untrusted text for logs/exceptions."""
    if not isinstance(value, str):
        return "?"
    return "".join(ch for ch in value if ch.isprintable())[:limit]


def _reject_constant(name: str):
    raise ValueError(f"invalid JSON constant {name}")  # NaN / Infinity


def decode_message(raw: object) -> dict:
    """Decode one server frame. Raises ProtocolViolation for anything unusable."""
    if not isinstance(raw, str):
        raise ProtocolViolation("binary frames are not supported")
    if len(raw.encode("utf-8", "ignore")) > MAX_MESSAGE_BYTES:
        raise ProtocolViolation("message too large")
    try:
        data = json.loads(raw, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise ProtocolViolation("malformed JSON") from None
    if not isinstance(data, dict) or not isinstance(data.get("type"), str):
        raise ProtocolViolation("message must be an object with a string 'type'")
    return data


def raise_if_error(data: dict) -> None:
    if data.get("type") == "error":
        raise ServerError(_safe_text(data.get("code")), _safe_text(data.get("message"), 120))


def _positive_number(value: object, field: str, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolViolation(f"'{field}' must be a number")
    number = float(value)
    if not math.isfinite(number) or number <= 0 or number > maximum:
        raise ProtocolViolation(f"'{field}' is out of range")
    return number


def parse_registered(raw: object, expected_agent_id: str | uuid.UUID) -> Registered:
    """Validate the server's answer to ``auth``."""
    data = decode_message(raw)
    raise_if_error(data)
    if data["type"] != "registered":
        raise ProtocolViolation(f"expected 'registered', got '{_safe_text(data['type'])}'")

    version = data.get("protocol_version")
    if isinstance(version, bool) or version != PROTOCOL_VERSION:
        raise ProtocolViolation("unsupported protocol_version")

    agent_id = parse_agent_id(data.get("agent_id"))
    if agent_id is None or agent_id != uuid.UUID(str(expected_agent_id)):
        raise ProtocolViolation("agent_id mismatch")

    connection_raw = data.get("connection_id")
    if (
        not isinstance(connection_raw, str)
        or len(connection_raw) != 36
    ):
        raise ProtocolViolation("'connection_id' is invalid")
    try:
        connection_id = str(uuid.UUID(connection_raw))
    except ValueError:
        raise ProtocolViolation("'connection_id' is invalid") from None

    interval = _positive_number(
        data.get("heartbeat_interval_seconds"), "heartbeat_interval_seconds", MAX_HEARTBEAT_INTERVAL
    )
    timeout = _positive_number(
        data.get("heartbeat_timeout_seconds"), "heartbeat_timeout_seconds", MAX_HEARTBEAT_TIMEOUT
    )
    if timeout <= interval:
        raise ProtocolViolation("heartbeat timeout must exceed heartbeat interval")

    server_time = data.get("server_time")
    if not isinstance(server_time, str):
        raise ProtocolViolation("'server_time' is invalid")
    try:
        datetime.fromisoformat(server_time)
    except ValueError:
        raise ProtocolViolation("'server_time' is invalid") from None

    return Registered(str(agent_id), connection_id, interval, timeout, server_time)


def validate_heartbeat_ack(data: dict, expected_seq: int) -> None:
    """``data`` is an already decoded message of type heartbeat_ack."""
    seq = data.get("seq")
    if isinstance(seq, bool) or not isinstance(seq, int):
        raise HeartbeatMismatch("heartbeat_ack without a valid seq")
    if seq != expected_seq:
        raise HeartbeatMismatch(f"heartbeat_ack seq {seq} != expected {expected_seq}")
    server_time = data.get("server_time")
    if server_time is not None and not isinstance(server_time, str):
        raise ProtocolViolation("'server_time' is invalid")


def parse_heartbeat_ack(raw: object, expected_seq: int) -> None:
    data = decode_message(raw)
    raise_if_error(data)
    if data["type"] != "heartbeat_ack":
        raise ProtocolViolation(f"expected 'heartbeat_ack', got '{_safe_text(data['type'])}'")
    validate_heartbeat_ack(data, expected_seq)
