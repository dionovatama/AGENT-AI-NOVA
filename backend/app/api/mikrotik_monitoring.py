"""Read-only RouterOS v6/v7 monitoring collector.

All RouterOS calls run through the authenticated device context and existing
local/Agent transport. No configuration commands are issued.
"""
from __future__ import annotations

import asyncio
import uuid
import logging
from datetime import datetime, timezone

import librouteros
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.models import Device, User
from app.database.session import get_db
from app.network.device_context import build_device_context
from app.security.dependencies import get_current_user
from app.tools.mikrotik import _run_on_device, _api_session, _safe_int, _to_bool

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/devices", tags=["mikrotik-monitoring"])


# librouteros melempar MultiTrapError (bukan subclass TrapError) saat menu tidak
# ada, mis. /system routerboard di CHR/x86/VM. Wajib ikut ditangkap.
_MENU_ERRORS = (
    librouteros.exceptions.TrapError,
    librouteros.exceptions.MultiTrapError,
    KeyError,
    AttributeError,
)


def _rows(api, *path):
    try:
        return list(api.path(*path))
    except _MENU_ERRORS:
        # RouterOS menu differs by package/version/device role; unsupported
        # optional menus are reported as empty rather than failing core metrics.
        return []


def _monitor_sync(device, password, sock=None):
    with _api_session(device, password, sock) as api:
        resource_rows = _rows(api, "system", "resource")
        identity_rows = _rows(api, "system", "identity")
        board_rows = _rows(api, "system", "routerboard")
        interfaces = _rows(api, "interface")
        # Satu call monitor-traffic untuk SEMUA interface (bukan N call berurutan)
        # -> jauh lebih cepat lewat Agent relay, mengurangi risiko timeout.
        names = [r["name"] for r in interfaces if r.get("name")]
        traffic_by_name = {}
        if names:
            try:
                for t in api.path("interface")(
                    "monitor-traffic", **{"interface": ",".join(names), "once": ""}
                ):
                    traffic_by_name[t.get("name")] = t
            except _MENU_ERRORS + (TypeError,):
                logger.warning("monitor-traffic batch gagal; traffic dikosongkan")
        iface_data = []
        for row in interfaces:
            name = row.get("name")
            if not name:
                continue
            traffic = traffic_by_name.get(name, {})
            iface_data.append({
                "name": name, "type": row.get("type"),
                "running": _to_bool(row.get("running", False)),
                "disabled": _to_bool(row.get("disabled", False)),
                "mac_address": row.get("mac-address"),
                "mtu": _safe_int(row.get("mtu")),
                "rx_bps": _safe_int(traffic.get("rx-bits-per-second")),
                "tx_bps": _safe_int(traffic.get("tx-bits-per-second")),
                "rx_packets_per_second": _safe_int(traffic.get("rx-packets-per-second")),
                "tx_packets_per_second": _safe_int(traffic.get("tx-packets-per-second")),
            })
        neighbors = _rows(api, "ip", "neighbor")
        if not neighbors:
            neighbors = _rows(api, "ip", "neighbor", "discovery")
        arp = _rows(api, "ip", "arp")
        dhcp = _rows(api, "ip", "dhcp-server", "lease")
        bridge_hosts = _rows(api, "interface", "bridge", "host")
        return {
            "resource": resource_rows[0] if resource_rows else {},
            "identity": identity_rows[0] if identity_rows else {},
            "routerboard": board_rows[0] if board_rows else {},
            "interfaces": iface_data,
            "neighbors": [{
                "identity": r.get("identity"), "address": r.get("address"),
                "mac_address": r.get("mac-address"), "interface": r.get("interface"),
                "platform": r.get("platform"), "version": r.get("version"),
            } for r in neighbors],
            "arp": [{
                "address": r.get("address"), "mac_address": r.get("mac-address"),
                "interface": r.get("interface"), "complete": _to_bool(r.get("complete", False)),
            } for r in arp],
            "dhcp_leases": [{
                "address": r.get("address"), "mac_address": r.get("mac-address"),
                "host_name": r.get("host-name"), "server": r.get("server"),
                "status": r.get("status"), "last_seen": r.get("last-seen"),
            } for r in dhcp],
            "bridge_hosts": [{
                "mac_address": r.get("mac-address"), "bridge": r.get("bridge"),
                "on_interface": r.get("on-interface"), "local": _to_bool(r.get("local", False)),
            } for r in bridge_hosts],
        }


@router.get("/{device_id}/monitoring")
async def get_mikrotik_monitoring(
    device_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Collect a live read-only snapshot from an owner-authorized MikroTik (RouterOS v6/v7)."""
    device = db.query(Device).filter(
        Device.id == device_id, Device.owner_id == current_user.id,
        Device.platform == "mikrotik",
    ).first()
    if device is None:
        raise HTTPException(status_code=404, detail="MikroTik device not found.")
    try:
        ctx = build_device_context(device, current_user, db)
        raw = await _run_on_device(_monitor_sync, ctx)
    except HTTPException:
        # Preserve actionable relay/context errors produced by the shared transport.
        raise
    except ValueError as exc:
        logger.warning("MikroTik monitoring validation failed for device %s: %s", device_id, exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        # Include the exception class in server logs, never credentials or API payloads.
        logger.exception("MikroTik monitoring failed for device %s (%s)", device_id, type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail=f"RouterOS monitoring failed ({type(exc).__name__}): {exc}",
        ) from exc

    resource = raw["resource"]
    identity = raw["identity"]
    board = raw["routerboard"]
    total = _safe_int(resource.get("total-memory"))
    free = _safe_int(resource.get("free-memory"))
    storage_total = _safe_int(resource.get("total-hdd-space"))
    storage_free = _safe_int(resource.get("free-hdd-space"))
    return {
        "device_id": str(device.id), "collected_at": datetime.now(timezone.utc).isoformat(),
        "router": {
            "identity": identity.get("name"), "board_name": resource.get("board-name"),
            "model": board.get("model"), "serial_number": board.get("serial-number"),
            "routeros_version": resource.get("version"),
            "architecture": resource.get("architecture-name"), "uptime": resource.get("uptime"),
            "cpu_load_percent": _safe_int(resource.get("cpu-load")),
            "cpu_count": _safe_int(resource.get("cpu-count")),
            "cpu_frequency_mhz": _safe_int(resource.get("cpu-frequency")),
            "free_memory_bytes": free, "total_memory_bytes": total,
            "memory_used_percent": round((total-free)*100/total, 1) if total and free is not None else None,
            "free_storage_bytes": storage_free, "total_storage_bytes": storage_total,
            "storage_used_percent": round((storage_total-storage_free)*100/storage_total, 1)
                if storage_total and storage_free is not None else None,
        },
        "interfaces": raw["interfaces"], "neighbors": raw["neighbors"],
        "arp": raw["arp"], "dhcp_leases": raw["dhcp_leases"],
        "bridge_hosts": raw["bridge_hosts"],
        "compatibility": {"routeros": "v6/v7", "collection": "read-only",
            "optional_tables_may_be_empty": True},
    }