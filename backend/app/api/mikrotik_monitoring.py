"""Read-only RouterOS v6/v7 monitoring collector.

All RouterOS calls run through the authenticated device context and existing
local/Agent transport. No configuration commands are issued.
"""
from __future__ import annotations

import asyncio
import uuid
import logging
from datetime import datetime, timezone, timedelta
import re

import librouteros
from fastapi import APIRouter, Depends, HTTPException, Query
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
    _save_metric_sample(db, device, response)
    return response


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
    response = {
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
    _save_metric_sample(db, device, response)
    return response


# Per-process throttle for retention work; database throttling remains authoritative.
_LAST_MONITORING_PRUNE: dict[uuid.UUID, datetime] = {}
_INTERFACE_NAME = re.compile(r"^[A-Za-z0-9_.:@/-]{1,64}$")


def _save_metric_sample(db: Session, device: Device, snapshot: dict) -> None:
    """Best-effort persistence: monitoring response must survive DB write failures."""
    from sqlalchemy import delete
    from app.config import settings
    from app.database.models import DeviceMetricSample

    now = datetime.now(timezone.utc)
    try:
        # Serialize writes per device on PostgreSQL to avoid concurrent duplicate samples.
        db.query(Device).filter(Device.id == device.id).with_for_update().first()
        latest = db.query(DeviceMetricSample).filter(
            DeviceMetricSample.device_id == device.id
        ).order_by(DeviceMetricSample.collected_at.desc()).first()
        if latest and (now - latest.collected_at).total_seconds() < settings.monitoring_sample_interval_seconds:
            db.rollback()
            return

        router = snapshot.get("router") or {}
        interfaces = [
            {
                "name": str(item.get("name", ""))[:64],
                "rx_bps": item.get("rx_bps"),
                "tx_bps": item.get("tx_bps"),
                "running": bool(item.get("running", False)),
            }
            for item in snapshot.get("interfaces", [])
            if item.get("name")
        ]
        db.add(DeviceMetricSample(
            device_id=device.id,
            collected_at=now,
            cpu_load_percent=router.get("cpu_load_percent"),
            memory_used_percent=router.get("memory_used_percent"),
            storage_used_percent=router.get("storage_used_percent"),
            interfaces=interfaces,
        ))

        last_prune = _LAST_MONITORING_PRUNE.get(device.id)
        if last_prune is None or (now - last_prune).total_seconds() >= 3600:
            cutoff = now - timedelta(days=settings.monitoring_retention_days)
            db.execute(delete(DeviceMetricSample).where(
                DeviceMetricSample.device_id == device.id,
                DeviceMetricSample.collected_at < cutoff,
            ))
            _LAST_MONITORING_PRUNE[device.id] = now

        overflow_ids = db.query(DeviceMetricSample.id).filter(
            DeviceMetricSample.device_id == device.id
        ).order_by(DeviceMetricSample.collected_at.desc()).offset(
            settings.monitoring_max_samples_per_device
        ).subquery()
        db.execute(delete(DeviceMetricSample).where(DeviceMetricSample.id.in_(overflow_ids)))
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("Monitoring history write failed for device %s (%s)", device.id, type(exc).__name__)


@router.get("/{device_id}/monitoring/history")
def get_mikrotik_monitoring_history(
    device_id: uuid.UUID,
    minutes: int = Query(60, ge=1, le=10080),
    interface: str | None = Query(None, min_length=1, max_length=64),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return at most 500 averaged time buckets from sanitized samples."""
    from math import ceil
    from collections import defaultdict
    from app.database.models import DeviceMetricSample

    if interface is not None and not _INTERFACE_NAME.fullmatch(interface):
        raise HTTPException(status_code=422, detail="Invalid interface name.")
    device = db.query(Device).filter(
        Device.id == device_id, Device.owner_id == current_user.id,
        Device.platform == "mikrotik",
    ).first()
    if device is None:
        raise HTTPException(status_code=404, detail="MikroTik device not found.")

    now = datetime.now(timezone.utc)
    start = now - __import__("datetime").timedelta(minutes=minutes)
    samples = db.query(DeviceMetricSample).join(
        Device, Device.id == DeviceMetricSample.device_id
    ).filter(
        Device.id == device_id, Device.owner_id == current_user.id,
        DeviceMetricSample.collected_at >= start,
    ).order_by(DeviceMetricSample.collected_at.asc()).all()

    bucket_seconds = max(1, ceil(minutes * 60 / 500))
    buckets: dict[int, dict] = defaultdict(lambda: {
        "timestamps": [], "cpu": [], "memory": [], "storage": [], "rx": [], "tx": []
    })
    for sample in samples:
        epoch = sample.collected_at.timestamp()
        key = int((epoch - start.timestamp()) // bucket_seconds)
        bucket = buckets[key]
        bucket["timestamps"].append(epoch)
        for source, target in (
            (sample.cpu_load_percent, "cpu"),
            (sample.memory_used_percent, "memory"),
            (sample.storage_used_percent, "storage"),
        ):
            if source is not None:
                bucket[target].append(float(source))
        if interface is not None:
            for item in sample.interfaces or []:
                if item.get("name") == interface:
                    if item.get("rx_bps") is not None:
                        bucket["rx"].append(float(item["rx_bps"]))
                    if item.get("tx_bps") is not None:
                        bucket["tx"].append(float(item["tx_bps"]))
                    break

    def average(values):
        return round(sum(values) / len(values), 2) if values else None

    points = []
    for key in sorted(buckets):
        bucket = buckets[key]
        points.append({
            "collected_at": datetime.fromtimestamp(
                sum(bucket["timestamps"]) / len(bucket["timestamps"]), timezone.utc
            ).isoformat(),
            "cpu_load_percent": average(bucket["cpu"]),
            "memory_used_percent": average(bucket["memory"]),
            "storage_used_percent": average(bucket["storage"]),
            "rx_bps": average(bucket["rx"]) if interface is not None else None,
            "tx_bps": average(bucket["tx"]) if interface is not None else None,
            "sample_count": len(bucket["timestamps"]),
        })
    return {"points": points, "bucket_seconds": bucket_seconds, "count": len(samples)}
