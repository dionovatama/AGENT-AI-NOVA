"""Pembangun topology NOVA (Phase 6): Agent, Device, dan relay target -> node + edge.

Fungsi murni (tanpa DB/IO) supaya mudah diuji. Lapisan API yang mengambil data
milik user lalu memanggil ``build_topology``.

Prinsip status (jujur, tidak mengarang):
  * Device berjalur Agent dan Agent-nya tidak online -> ``agent_offline``
    (pasti tidak bisa dijangkau lewat relay, tanpa perlu probe).
  * Selain itu pakai hasil probe terakhir BILA masih segar; bila basi atau belum
    pernah dicek -> ``unknown`` (``stale=True`` bila pernah dicek).
  * Device tanpa relay target: ``route="direct"``, status ``unknown``. NOVA tidak
    mem-probe host sembarang dari backend (menghindari SSRF/port-scan).

``issues`` mendeteksi salah konfigurasi yang nyata terjadi di lapangan, mis.
``api-ssl`` dengan port 8728 (API polos) yang tadinya hanya muncul sebagai
"handshake timed out".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

ONLINE_AGENT = "online"
DEFAULT_STALE_AFTER_SECONDS = 300.0

# Kode issue stabil: dipakai frontend untuk teks/ikon.
ISSUE_PLAIN_API_PORT_WITH_TLS = "port_8728_with_api_ssl"
ISSUE_PIN_MISSING = "pin_missing"
ISSUE_PORT_NOT_ALLOWED = "port_not_in_target"
ISSUE_RELAY_NEEDS_API_SSL = "relay_requires_api_ssl"
ISSUE_NO_TARGET_FOR_AGENT_DEVICE = "no_relay_target"


@dataclass(frozen=True)
class AgentIn:
    id: str
    name: str
    status: str                      # status EFEKTIF (sudah lewat effective_status)
    hostname: str | None = None
    last_heartbeat_at: datetime | None = None


@dataclass(frozen=True)
class DeviceIn:
    id: str
    name: str
    platform: str
    host: str
    port: int
    connection_type: str
    reachability: str = "unknown"    # hasil probe terakhir: online | offline | unknown
    last_checked_at: datetime | None = None
    last_check_detail: str | None = None


@dataclass(frozen=True)
class TargetIn:
    id: str
    agent_id: str
    device_id: str | None
    host: str
    ports: tuple[int, ...] = field(default_factory=tuple)
    pinned: bool = False


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _pick_target(device: DeviceIn, candidates: list[TargetIn]) -> TargetIn | None:
    """Target pertama yang mengizinkan port device; kalau tak ada, yang pertama
    (supaya salah konfigurasi tetap terlihat sebagai issue)."""
    if not candidates:
        return None
    for t in candidates:
        if device.port in t.ports:
            return t
    return candidates[0]


def build_topology(
    agents: list[AgentIn],
    devices: list[DeviceIn],
    targets: list[TargetIn],
    now: datetime,
    stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
) -> dict[str, Any]:
    now = _as_utc(now)
    agent_by_id = {a.id: a for a in agents}
    targets_by_device: dict[str, list[TargetIn]] = {}
    for t in targets:
        if t.device_id is not None and t.agent_id in agent_by_id:
            targets_by_device.setdefault(t.device_id, []).append(t)

    nodes: list[dict[str, Any]] = [
        {"id": "nova", "kind": "nova", "name": "NOVA Backend", "status": "online"},
    ]
    edges: list[dict[str, Any]] = []

    for a in agents:
        nodes.append({
            "id": f"agent:{a.id}", "kind": "agent", "ref_id": a.id, "name": a.name,
            "status": a.status, "hostname": a.hostname,
            "last_heartbeat_at": _iso(a.last_heartbeat_at),
        })
        edges.append({"from": "nova", "to": f"agent:{a.id}", "kind": "control"})

    counts = {"online": 0, "offline": 0, "agent_offline": 0, "unknown": 0}

    for d in devices:
        issues: list[str] = []
        target = _pick_target(d, targets_by_device.get(d.id, []))
        conn = (d.connection_type or "").strip().lower()

        if conn == "api-ssl" and d.port == 8728:
            issues.append(ISSUE_PLAIN_API_PORT_WITH_TLS)

        route = "direct"
        agent: AgentIn | None = None
        if target is not None:
            route = "agent"
            agent = agent_by_id[target.agent_id]
            if conn != "api-ssl":
                issues.append(ISSUE_RELAY_NEEDS_API_SSL)
            if not target.pinned:
                issues.append(ISSUE_PIN_MISSING)
            if d.port not in target.ports:
                issues.append(ISSUE_PORT_NOT_ALLOWED)

        checked = _as_utc(d.last_checked_at)
        fresh = checked is not None and (now - checked).total_seconds() <= stale_after_seconds
        stale = checked is not None and not fresh

        if route == "agent" and agent is not None and agent.status != ONLINE_AGENT:
            status = "agent_offline"
        elif route == "agent" and fresh and d.reachability in ("online", "offline"):
            status = d.reachability
        else:
            status = "unknown"
        counts[status] += 1

        nodes.append({
            "id": f"device:{d.id}", "kind": "device", "ref_id": d.id, "name": d.name,
            "platform": d.platform, "host": d.host, "port": d.port,
            "connection_type": d.connection_type, "route": route, "status": status,
            "stale": stale, "last_checked_at": _iso(d.last_checked_at),
            "last_check_detail": d.last_check_detail, "issues": issues,
            "agent_id": agent.id if agent else None,
        })
        if target is not None and agent is not None:
            edges.append({
                "from": f"agent:{agent.id}", "to": f"device:{d.id}", "kind": "relay",
                "target_id": target.id, "pinned": target.pinned,
            })

    return {
        "generated_at": _iso(now),
        "nodes": nodes,
        "edges": edges,
        "summary": {
            "agents_total": len(agents),
            "agents_online": sum(1 for a in agents if a.status == ONLINE_AGENT),
            "devices_total": len(devices),
            "devices": counts,
            "devices_with_issues": sum(
                1 for n in nodes if n["kind"] == "device" and n["issues"]),
        },
    }
