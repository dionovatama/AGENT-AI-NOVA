"""
Model state koneksi Remote Agent (Phase A).

Lima state resmi:

    offline       Belum pernah connect, atau agent pamit dengan bersih
                  (pesan 'bye' / close 1000/1001).
    connecting    Token valid, koneksi sudah di-claim, registrasi belum
                  dikonfirmasi ke agent.
    online        Registrasi terkonfirmasi dan heartbeat segar.
    disconnected  Koneksi hilang tanpa pamit: socket putus, heartbeat
                  timeout, backend restart, atau digantikan koneksi lain.
    error         Handler di backend gagal karena error tak terduga.

PENTING (multi-worker): status yang tersimpan di DB hanya "klaim terakhir
yang ditulis worker pemilik koneksi". Sumber kebenaran untuk membaca
status adalah effective_status(), yang mengecek kesegaran heartbeat.
Worker B tidak pernah menyimpulkan "offline" dari dict memorinya sendiri.
"""

from __future__ import annotations

import enum
from datetime import datetime, timedelta, timezone


class AgentStatus(str, enum.Enum):
    OFFLINE = "offline"
    CONNECTING = "connecting"
    ONLINE = "online"
    DISCONNECTED = "disconnected"
    ERROR = "error"


# Status yang mengklaim "ada koneksi hidup" -- hanya ini yang bisa basi.
LIVE_STATUSES = (AgentStatus.CONNECTING, AgentStatus.ONLINE)


def as_utc(value: datetime | None) -> datetime | None:
    """Normalisasi ke UTC-aware. Datetime naive dianggap UTC (SQLite
    mengembalikan naive; PostgreSQL timestamptz mengembalikan aware)."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def effective_status(
    status: str,
    last_heartbeat_at: datetime | None,
    now: datetime,
    heartbeat_timeout_seconds: float,
) -> AgentStatus:
    """
    Status yang boleh ditampilkan/dipakai keputusan.

    - online/connecting dengan heartbeat basi (atau tanpa heartbeat)
      dilaporkan 'disconnected', walau baris DB belum disapu sweeper
      (mis. worker pemilik koneksi crash).
    - Nilai status tak dikenal dilaporkan 'error', bukan di-crash-kan.
    """
    try:
        current = AgentStatus(status)
    except ValueError:
        return AgentStatus.ERROR

    if current in LIVE_STATUSES:
        heartbeat = as_utc(last_heartbeat_at)
        reference = as_utc(now)
        if heartbeat is None or reference is None:
            return AgentStatus.DISCONNECTED
        if reference - heartbeat > timedelta(seconds=heartbeat_timeout_seconds):
            return AgentStatus.DISCONNECTED
    return current
