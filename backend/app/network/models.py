"""
Models for N.O.V.A Configuration Engine.

Mendefinisikan tipe operasi yang diizinkan (discriminated union), ChangeSet,
dan model snapshot state perangkat (PRD section 19-21, 39).
"""

from __future__ import annotations

import enum
import ipaddress
import re
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, field_validator, model_validator


class OperationType(str, enum.Enum):
    """
    Whitelist tipe operasi MVP (hanya operasi ADD yang diizinkan).
    Semua operasi di luar enum ini ditolak langsung di level schema (Pydantic).
    """
    ADD_IP_ADDRESS = "add_ip_address"
    ADD_VLAN_INTERFACE = "add_vlan_interface"
    ADD_STATIC_ROUTE = "add_static_route"


_SAFE_NAME_REGEX = re.compile(r"^[a-zA-Z0-9_.-]+$")
_SAFE_COMMENT_REGEX = re.compile(r"^[a-zA-Z0-9 _.-]*$")


class AddIpAddressOperation(BaseModel):
    """Operasi menambahkan IP address pada interface tertentu."""
    type: Literal[OperationType.ADD_IP_ADDRESS] = OperationType.ADD_IP_ADDRESS
    interface: str = Field(..., min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9_.-]+$")
    address: str = Field(..., min_length=7, max_length=49, description="IPv4 CIDR misal 192.168.10.1/24")
    comment: str | None = Field(default=None, max_length=64, pattern=r"^[a-zA-Z0-9 _.-]*$")

    @field_validator("address")
    @classmethod
    def validate_ipv4_cidr(cls, v: str) -> str:
        try:
            # Harus memiliki netmask/prefix
            if "/" not in v:
                raise ValueError("Address harus dalam format CIDR lengkap (mis. 192.168.10.1/24)")
            iface = ipaddress.IPv4Interface(v)
            # Pastikan host IP bukan network IP jika mask < 31
            if iface.network.prefixlen < 31:
                if iface.ip == iface.network.network_address:
                    raise ValueError(f"Address {v} adalah network address, bukan host address")
                if iface.ip == iface.network.broadcast_address:
                    raise ValueError(f"Address {v} adalah broadcast address, bukan host address")
            return str(iface)
        except (ipaddress.AddressValueError, ipaddress.NetmaskValueError) as exc:
            raise ValueError(f"Invalid IPv4 CIDR address: {exc}") from exc


class AddVlanInterfaceOperation(BaseModel):
    """Operasi membuat interface VLAN baru pada parent interface tertentu."""
    type: Literal[OperationType.ADD_VLAN_INTERFACE] = OperationType.ADD_VLAN_INTERFACE
    name: str = Field(..., min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9_.-]+$")
    vlan_id: int = Field(..., ge=1, le=4094, description="VLAN ID IEEE 802.1Q (1-4094)")
    interface: str = Field(..., min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9_.-]+$")
    comment: str | None = Field(default=None, max_length=64, pattern=r"^[a-zA-Z0-9 _.-]*$")


class AddStaticRouteOperation(BaseModel):
    """Operasi menambahkan static route baru."""
    type: Literal[OperationType.ADD_STATIC_ROUTE] = OperationType.ADD_STATIC_ROUTE
    dst_address: str = Field(..., min_length=7, max_length=49, description="Destination CIDR misal 10.0.0.0/24")
    gateway: str = Field(..., min_length=1, max_length=64, description="Gateway IP atau nama interface")
    distance: int = Field(default=1, ge=1, le=255, description="Administrative distance / metric (1-255)")
    comment: str | None = Field(default=None, max_length=64, pattern=r"^[a-zA-Z0-9 _.-]*$")

    @field_validator("dst_address")
    @classmethod
    def validate_destination_network(cls, v: str) -> str:
        try:
            if "/" not in v:
                raise ValueError("dst_address harus dalam format CIDR lengkap (mis. 10.0.0.0/24)")
            net = ipaddress.IPv4Network(v, strict=False)
            return str(net)
        except (ipaddress.AddressValueError, ipaddress.NetmaskValueError) as exc:
            raise ValueError(f"Invalid IPv4 destination network: {exc}") from exc

    @field_validator("gateway")
    @classmethod
    def validate_gateway(cls, v: str) -> str:
        v_clean = v.strip()
        # Gateway bisa berupa IP address valid
        try:
            ip = ipaddress.IPv4Address(v_clean)
            return str(ip)
        except ipaddress.AddressValueError:
            pass

        # Atau nama interface valid
        if _SAFE_NAME_REGEX.match(v_clean):
            return v_clean

        raise ValueError(
            f"Gateway '{v}' harus berupa alamat IPv4 yang valid atau nama interface yang aman."
        )


# Discriminated union untuk seluruh tipe operasi yang didukung
NetworkOperation = Annotated[
    Union[AddIpAddressOperation, AddVlanInterfaceOperation, AddStaticRouteOperation],
    Field(discriminator="type"),
]


class ChangeSet(BaseModel):
    """Kumpulan operasi konfigurasi yang diusulkan untuk satu perangkat."""
    description: str = Field(..., min_length=3, max_length=255)
    operations: list[NetworkOperation] = Field(..., min_length=1, max_length=20)


# ============================================================
# Model State Perangkat (Snapshot & Evidence)
# ============================================================

class InterfaceState(BaseModel):
    name: str
    type: str = "ethernet"
    running: bool = True
    disabled: bool = False
    comment: str | None = None


class IpAddressState(BaseModel):
    address: str
    interface: str
    network: str | None = None
    disabled: bool = False
    comment: str | None = None
    id: str | None = None


class RouteState(BaseModel):
    dst_address: str
    gateway: str
    distance: int = 1
    active: bool = True
    disabled: bool = False
    comment: str | None = None
    id: str | None = None


class DeviceStateSnapshot(BaseModel):
    interfaces: list[InterfaceState] = Field(default_factory=list)
    ip_addresses: list[IpAddressState] = Field(default_factory=list)
    routes: list[RouteState] = Field(default_factory=list)
