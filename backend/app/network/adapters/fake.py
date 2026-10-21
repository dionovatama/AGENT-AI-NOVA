"""
Fake/In-Memory Network Device Adapter for Testing and Simulation.

Menyediakan simulasi state perangkat jaringan in-memory tanpa memerlukan
perangkat keras fisik nyata (PRD section 27, 43).
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    from app.database.models import Device
    from app.tools.context import ExecutionContext


class FakeNetworkAdapter(NetworkDeviceAdapter):
    """
    Adapter simulasi in-memory untuk pengujian end-to-end tanpa perangkat fisik.
    """

    def __init__(
        self,
        initial_interfaces: list[InterfaceState] | None = None,
        initial_ip_addresses: list[IpAddressState] | None = None,
        initial_routes: list[RouteState] | None = None,
    ) -> None:
        self.interfaces = initial_interfaces if initial_interfaces is not None else [
            InterfaceState(name="ether1", type="ethernet", running=True),
            InterfaceState(name="ether2", type="ethernet", running=True),
            InterfaceState(name="ether3", type="ethernet", running=True),
        ]
        self.ip_addresses = initial_ip_addresses if initial_ip_addresses is not None else [
            IpAddressState(address="192.168.88.1/24", interface="ether1", id="*fake_init_ip"),
        ]
        self.routes = initial_routes if initial_routes is not None else [
            RouteState(dst_address="0.0.0.0/0", gateway="192.168.88.254", distance=1, id="*fake_init_route"),
        ]

        self._id_counter = 1
        self.fail_on_step: int | None = None
        self.fail_on_verify: bool = False
        self.fail_on_rollback: bool = False
        self.current_step = 0
        self.applied_operations: list[tuple[NetworkOperation, str]] = []
        self.removed_operations: list[str] = []

    async def get_device_state(
        self, device: Device, ctx: ExecutionContext | None = None
    ) -> DeviceStateSnapshot:
        return DeviceStateSnapshot(
            interfaces=copy.deepcopy(self.interfaces),
            ip_addresses=copy.deepcopy(self.ip_addresses),
            routes=copy.deepcopy(self.routes),
        )

    async def apply_operation(
        self, op: NetworkOperation, device: Device, ctx: ExecutionContext | None = None
    ) -> str:
        self.current_step += 1
        if self.fail_on_step is not None and self.current_step == self.fail_on_step:
            raise RuntimeError(f"Simulated hardware failure on step #{self.current_step} ({op.type.value})")

        obj_id = f"*fake_{self._id_counter}"
        self._id_counter += 1

        if isinstance(op, AddIpAddressOperation):
            self.ip_addresses.append(
                IpAddressState(
                    address=op.address,
                    interface=op.interface,
                    comment=op.comment,
                    id=obj_id,
                )
            )
        elif isinstance(op, AddVlanInterfaceOperation):
            self.interfaces.append(
                InterfaceState(
                    name=op.name,
                    type="vlan",
                    running=True,
                    comment=op.comment,
                )
            )
        elif isinstance(op, AddStaticRouteOperation):
            self.routes.append(
                RouteState(
                    dst_address=op.dst_address,
                    gateway=op.gateway,
                    distance=op.distance,
                    comment=op.comment,
                    id=obj_id,
                )
            )

        self.applied_operations.append((op, obj_id))
        return obj_id

    async def remove_operation(
        self,
        op: NetworkOperation,
        object_id: str,
        device: Device,
        ctx: ExecutionContext | None = None,
    ) -> bool:
        if self.fail_on_rollback:
            raise RuntimeError(f"Simulated failure during rollback of object {object_id}")

        self.removed_operations.append(object_id)

        if isinstance(op, AddIpAddressOperation):
            self.ip_addresses = [ip for ip in self.ip_addresses if ip.id != object_id]
            return True
        elif isinstance(op, AddVlanInterfaceOperation):
            self.interfaces = [iface for iface in self.interfaces if iface.name != op.name]
            return True
        elif isinstance(op, AddStaticRouteOperation):
            self.routes = [r for r in self.routes if r.id != object_id]
            return True

        return False

    async def verify_operation(
        self, op: NetworkOperation, device: Device, ctx: ExecutionContext | None = None
    ) -> bool:
        if self.fail_on_verify:
            return False

        if isinstance(op, AddIpAddressOperation):
            return any(
                ip.address == op.address and ip.interface == op.interface
                for ip in self.ip_addresses
            )
        elif isinstance(op, AddVlanInterfaceOperation):
            return any(
                iface.name == op.name and iface.type == "vlan"
                for iface in self.interfaces
            )
        elif isinstance(op, AddStaticRouteOperation):
            return any(
                r.dst_address == op.dst_address and r.gateway == op.gateway
                for r in self.routes
            )

        return False

    def render_cli_preview(self, op: NetworkOperation) -> str:
        """Render sintaks perintah CLI bergaya MikroTik RouterOS deterministik."""
        comment_part = f' comment="{op.comment}"' if getattr(op, "comment", None) else ""
        if isinstance(op, AddIpAddressOperation):
            return f'/ip address add address="{op.address}" interface="{op.interface}"{comment_part}'
        elif isinstance(op, AddVlanInterfaceOperation):
            return f'/interface vlan add name="{op.name}" vlan-id={op.vlan_id} interface="{op.interface}"{comment_part}'
        elif isinstance(op, AddStaticRouteOperation):
            return f'/ip route add dst-address="{op.dst_address}" gateway="{op.gateway}" distance={op.distance}{comment_part}'
        return f"# Unknown operation: {op}"
