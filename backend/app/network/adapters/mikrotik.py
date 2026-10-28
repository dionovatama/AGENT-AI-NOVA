"""
MikroTik Network Device Adapter for N.O.V.A Configuration Engine.

Mengimplementasikan NetworkDeviceAdapter untuk perangkat MikroTik RouterOS (v6 & v7)
menggunakan library librouteros melalui koneksi API / API-SSL (port 8728 / 8729).
(PRD section 17, 19, 21, 22).

CATATAN KEAMANAN:
- Menggunakan ulang _connect() dari app/tools/mikrotik.py agar konsisten.
- Seluruh panggilan synchronous librouteros dibungkus asyncio.to_thread().
- Gap ssl.CERT_NONE tetap berlaku untuk environment lab development.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

import librouteros.exceptions

from app.network.adapters.base import NetworkDeviceAdapter
from app.network.models import (
    AddIpAddressOperation,
    AddStaticRouteOperation,
    AddVlanInterfaceOperation,
    DeviceStateSnapshot,
    InterfaceState,
    IpAddressState,
    NetworkOperation,
    RouteState,
)
from app.tools.mikrotik import _api_session, _safe_int, _to_bool

if TYPE_CHECKING:
    from app.database.models import Device
    from app.tools.context import ExecutionContext

logger = logging.getLogger("nova.network.adapters.mikrotik")


def _get_device_state_sync(device: Device, password: str | None) -> DeviceStateSnapshot:
    """Membaca state nyata router secara sync di dalam thread."""
    with _api_session(device, password) as api:
        # 1. Interface state
        iface_rows = list(api.path("interface"))
        interfaces = [
            InterfaceState(
                name=row.get("name", ""),
                type=row.get("type", "ethernet"),
                running=_to_bool(row.get("running", True)),
                disabled=_to_bool(row.get("disabled", False)),
                comment=row.get("comment"),
            )
            for row in iface_rows
            if row.get("name")
        ]

        # 2. IP addresses
        ip_rows = list(api.path("ip", "address"))
        ip_addresses = [
            IpAddressState(
                address=row.get("address", ""),
                interface=row.get("interface", ""),
                network=row.get("network"),
                disabled=_to_bool(row.get("disabled", False)),
                comment=row.get("comment"),
                id=row.get(".id"),
            )
            for row in ip_rows
            if row.get("address")
        ]

        # 3. Static routes
        route_rows = list(api.path("ip", "route"))
        routes = [
            RouteState(
                dst_address=row.get("dst-address", ""),
                gateway=row.get("gateway", ""),
                distance=_safe_int(row.get("distance")) or 1,
                active=_to_bool(row.get("active", True)),
                disabled=_to_bool(row.get("disabled", False)),
                comment=row.get("comment"),
                id=row.get(".id"),
            )
            for row in route_rows
            if row.get("dst-address")
        ]

    return DeviceStateSnapshot(
        interfaces=interfaces,
        ip_addresses=ip_addresses,
        routes=routes,
    )


def _apply_operation_sync(op: NetworkOperation, device: Device, password: str | None) -> str:
    """Menerapkan satu operasi konfigurasi ke router via librouteros."""
    with _api_session(device, password) as api:
        if isinstance(op, AddIpAddressOperation):
            kwargs: dict[str, Any] = {
                "address": op.address,
                "interface": op.interface,
            }
            if op.comment:
                kwargs["comment"] = op.comment
            return api.path("ip", "address").add(**kwargs)

        elif isinstance(op, AddVlanInterfaceOperation):
            kwargs = {
                "name": op.name,
                "vlan-id": str(op.vlan_id),
                "interface": op.interface,
            }
            if op.comment:
                kwargs["comment"] = op.comment
            return api.path("interface", "vlan").add(**kwargs)

        elif isinstance(op, AddStaticRouteOperation):
            kwargs = {
                "dst-address": op.dst_address,
                "gateway": op.gateway,
                "distance": str(op.distance),
            }
            if op.comment:
                kwargs["comment"] = op.comment
            return api.path("ip", "route").add(**kwargs)

        raise ValueError(f"Operasi tidak didukung: {type(op)}")


def _remove_operation_sync(op: NetworkOperation, object_id: str, device: Device, password: str | None) -> bool:
    """Menghapus objek dari router berdasarkan object_id internal (mis. *1A)."""
    with _api_session(device, password) as api:
        try:
            if isinstance(op, AddIpAddressOperation):
                api.path("ip", "address").remove(object_id)
                return True
            elif isinstance(op, AddVlanInterfaceOperation):
                api.path("interface", "vlan").remove(object_id)
                return True
            elif isinstance(op, AddStaticRouteOperation):
                api.path("ip", "route").remove(object_id)
                return True
        except librouteros.exceptions.TrapError as exc:
            logger.error("RouterOS TrapError saat menghapus objek %s: %s", object_id, exc)
            return False
    return False


def _trigger_native_backup_sync(backup_name: str, device: Device, password: str | None) -> None:
    """Memicu pembuatan backup native (.backup) di flash router."""
    with _api_session(device, password) as api:
        # Eksekusi /system/backup/save =name=backup_name
        list(api.path("system", "backup")("save", **{"name": backup_name}))


class MikrotikNetworkAdapter(NetworkDeviceAdapter):
    """Adapter resmi untuk MikroTik RouterOS API/API-SSL."""

    async def get_device_state(
        self, device: Device, ctx: ExecutionContext | None = None
    ) -> DeviceStateSnapshot:
        password = ctx.credential_plaintext if ctx else None
        return await asyncio.to_thread(_get_device_state_sync, device, password)

    async def apply_operation(
        self, op: NetworkOperation, device: Device, ctx: ExecutionContext | None = None
    ) -> str:
        password = ctx.credential_plaintext if ctx else None
        return await asyncio.to_thread(_apply_operation_sync, op, device, password)

    async def remove_operation(
        self,
        op: NetworkOperation,
        object_id: str,
        device: Device,
        ctx: ExecutionContext | None = None,
    ) -> bool:
        password = ctx.credential_plaintext if ctx else None
        return await asyncio.to_thread(_remove_operation_sync, op, object_id, device, password)

    async def verify_operation(
        self, op: NetworkOperation, device: Device, ctx: ExecutionContext | None = None
    ) -> bool:
        # Verifikasi membaca state nyata router (bukan berasumsi dari status kembalian tool)
        state = await self.get_device_state(device, ctx)

        if isinstance(op, AddIpAddressOperation):
            return any(
                ip.address == op.address and ip.interface == op.interface
                for ip in state.ip_addresses
            )
        elif isinstance(op, AddVlanInterfaceOperation):
            return any(
                iface.name == op.name and iface.type == "vlan"
                for iface in state.interfaces
            )
        elif isinstance(op, AddStaticRouteOperation):
            return any(
                r.dst_address == op.dst_address and r.gateway == op.gateway
                for r in state.routes
            )

        return False

    async def create_native_backup(
        self, backup_name: str, device: Device, ctx: ExecutionContext | None = None
    ) -> None:
        """Membuat backup native di router sebelum apply."""
        password = ctx.credential_plaintext if ctx else None
        await asyncio.to_thread(_trigger_native_backup_sync, backup_name, device, password)

    def render_cli_preview(self, op: NetworkOperation) -> str:
        """Template perintah CLI MikroTik RouterOS deterministik."""
        comment_part = f' comment="{op.comment}"' if getattr(op, "comment", None) else ""
        if isinstance(op, AddIpAddressOperation):
            return f'/ip address add address="{op.address}" interface="{op.interface}"{comment_part}'
        elif isinstance(op, AddVlanInterfaceOperation):
            return f'/interface vlan add name="{op.name}" vlan-id={op.vlan_id} interface="{op.interface}"{comment_part}'
        elif isinstance(op, AddStaticRouteOperation):
            return f'/ip route add dst-address="{op.dst_address}" gateway="{op.gateway}" distance={op.distance}{comment_part}'
        return f"# Unknown operation: {op}"
