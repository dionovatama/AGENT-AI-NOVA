"""Linux network adapter with guarded SSH operations."""
from __future__ import annotations
import asyncio
import ipaddress
import re
import shlex
from typing import TYPE_CHECKING
import asyncssh
from app.config import settings
from app.network.adapters.base import NetworkDeviceAdapter
from app.network.models import AddIpAddressOperation, DeviceStateSnapshot, InterfaceState, IpAddressState, NetworkOperation, RouteState
if TYPE_CHECKING:
    from app.database.models import Device
    from app.tools.context import ExecutionContext

_SAFE_INTERFACE = re.compile(r"^[A-Za-z0-9_.:-]{1,32}$")

def _username(device: Device) -> str:
    value = (device.device_metadata or {}).get("username")
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,31}", value):
        raise ValueError("Metadata Linux wajib memiliki username SSH yang valid.")
    return value

class LinuxNetworkAdapter(NetworkDeviceAdapter):
    """SSH adapter; accepts typed operations only, never free-form shell input."""
    async def _run(self, device: Device, command: str) -> str:
        if not settings.linux_ssh_private_key_path:
            raise RuntimeError("linux_ssh_private_key_path belum dikonfigurasi.")
        known_hosts = (settings.linux_ssh_known_hosts_path or ()) if settings.linux_ssh_host_key_checking else None
        async with asyncssh.connect(host=device.host, port=device.port or 22, username=_username(device), client_keys=[settings.linux_ssh_private_key_path], known_hosts=known_hosts, connect_timeout=settings.linux_ssh_connect_timeout_seconds) as conn:
            result = await conn.run(command, check=False, timeout=20)
            if result.exit_status != 0:
                raise RuntimeError("Perintah jaringan Linux gagal; periksa SSH, interface, dan privilege.")
            return result.stdout

    async def get_device_state(self, device: Device, ctx: ExecutionContext | None = None) -> DeviceStateSnapshot:
        links, addrs, routes_raw = await asyncio.gather(self._run(device, "ip -o link show"), self._run(device, "ip -o -4 addr show"), self._run(device, "ip -4 route show"))
        interfaces = []
        for line in links.splitlines():
            match = re.match(r"^\\d+:\\s+([^:@]+)(?:@[^:]+)?:\\s+<([^>]*)>", line)
            if match:
                flags = set(match.group(2).split(","))
                interfaces.append(InterfaceState(name=match.group(1), type="loopback" if "LOOPBACK" in flags else "ethernet", running="UP" in flags, disabled="UP" not in flags))
        addresses = []
        for line in addrs.splitlines():
            match = re.match(r"^\\d+:\\s+([^\\s]+)\\s+inet\\s+(\\S+)", line)
            if match:
                addresses.append(IpAddressState(address=match.group(2), interface=match.group(1).split("@", 1)[0]))
        routes = []
        for line in routes_raw.splitlines():
            tokens = line.split()
            if not tokens: continue
            dst = "0.0.0.0/0" if tokens[0] == "default" else tokens[0]
            gateway = tokens[tokens.index("via") + 1] if "via" in tokens else (tokens[tokens.index("dev") + 1] if "dev" in tokens else "")
            if gateway: routes.append(RouteState(dst_address=dst, gateway=gateway))
        return DeviceStateSnapshot(interfaces=interfaces, ip_addresses=addresses, routes=routes)

    async def apply_operation(self, op: NetworkOperation, device: Device, ctx: ExecutionContext | None = None) -> str:
        if not isinstance(op, AddIpAddressOperation): raise ValueError("Linux saat ini mendukung penambahan IP statis saja.")
        if not _SAFE_INTERFACE.fullmatch(op.interface): raise ValueError("Nama interface tidak valid.")
        address = str(ipaddress.IPv4Interface(op.address))
        await self._run(device, f"ip address add {shlex.quote(address)} dev {shlex.quote(op.interface)}")
        return f"{op.interface}:{address}"

    async def remove_operation(self, op: NetworkOperation, object_id: str, device: Device, ctx: ExecutionContext | None = None) -> bool:
        if not isinstance(op, AddIpAddressOperation) or not _SAFE_INTERFACE.fullmatch(op.interface): return False
        address = str(ipaddress.IPv4Interface(op.address))
        await self._run(device, f"ip address del {shlex.quote(address)} dev {shlex.quote(op.interface)}")
        return True

    async def verify_operation(self, op: NetworkOperation, device: Device, ctx: ExecutionContext | None = None) -> bool:
        if not isinstance(op, AddIpAddressOperation): return False
        state = await self.get_device_state(device, ctx)
        return any(x.address == str(ipaddress.IPv4Interface(op.address)) and x.interface == op.interface for x in state.ip_addresses)

    def render_cli_preview(self, op: NetworkOperation) -> str:
        if isinstance(op, AddIpAddressOperation): return f"ip address add {op.address} dev {op.interface}  # runtime only; not persistent"
        return f"# Unsupported Linux operation: {op.type.value}"
