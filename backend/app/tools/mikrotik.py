"""
MikroTik Engine — Diagnostic tools (PRD section 17, batch pertama).

Ini adalah tool pertama yang benar-benar memakai pola ExecutionContext +
device_id yang didokumentasikan di README Tools ("N.O.V.A Tools —
Panduan Menambah Tool Baru", section 3). Berbeda dari linux.* dan ping
yang membaca koneksi dari .env (single-device, pola lama yang sengaja
TIDAK dipaksa migrasi), tool mikrotik.* SELALU menyasar device yang
didaftarkan lewat POST /devices dan mengambil kredensialnya lewat
POST /credentials + Device.credential_id — bukan config global.

Kenapa READ + LOW/MEDIUM untuk seluruh batch ini:
- Batch pertama murni membaca state device, tidak ada satu pun
  perubahan konfigurasi (README section 5, tabel Permission/Risk:
  "Diagnostic tools (semua mikrotik.* batch pertama) = READ + LOW").
- interface/ip/route/arp = LOW (topologi jaringan biasa, sama semangat
  dengan linux.network_info).
- dhcp_leases & firewall_rules = MEDIUM (README section 5: "baca data
  yang lebih sensitif — firewall rules, DHCP lease berisi MAC/hostname
  client").
- Tool KONFIGURASI (buat VLAN, ubah firewall, dst — PRD section 17
  "Configuration") BELUM ada di sini. Itu scope terpisah (MODIFY/
  HIGH_RISK + Configuration Flow PRD section 20: Preview -> Confirm ->
  Apply -> Verify -> Rollback), bukan bagian dari batch diagnostic ini.

Komunikasi: RouterOS API (port 8728) atau API-SSL (port 8729) lewat
library `librouteros` (sync) — PRD section 17 "Communication: RouterOS
API/API-SSL, prefer structured API". Library ini murni sync, jadi
SETIAP panggilan dibungkus asyncio.to_thread() (README section 4)
supaya tidak memblokir event loop FastAPI. Fungsi `_xxx_sync()` dipisah
dari executor async-nya masing-masing supaya bisa (kalau perlu) diuji
tanpa mock asyncio.to_thread, konsisten dengan pola `_parse_interfaces`
di linux.py.

CATATAN KEAMANAN — GAP YANG DISENGAJA TETAP TERLIHAT (lihat juga
komentar senada di app/tools/manager.py, blok "4.5 Device Resolution"):
- Verifikasi sertifikat API-SSL DIMATIKAN (ssl.CERT_NONE) di bawah.
  Ini cukup untuk lab dengan RouterOS self-signed cert, TAPI TIDAK
  BOLEH dibawa ke production apa adanya — akan digantikan certificate
  pinning per-device saat Device Management masuk fase produksi. Sama
  persis semangatnya dengan `known_hosts=None` di app/tools/linux.py.
- credential_plaintext (dari ctx) HANYA dipakai untuk connect, TIDAK
  PERNAH dimasukkan ke output/log/exception message yang di-return.

Dependency baru (tambahkan ke requirements.txt):
    librouteros==3.4.1
"""

from __future__ import annotations

import asyncio
import logging
import ssl

import librouteros
import librouteros.exceptions
from pydantic import BaseModel, Field

from app.database.models import Device
from app.tools.context import ExecutionContext
from app.tools.schemas import (
    LoggingPolicy,
    PermissionLevel,
    RiskLevel,
    ToolDefinition,
)

logger = logging.getLogger("nova.tools.mikrotik")

_CONNECT_TIMEOUT_SECONDS = 10.0


class MikrotikConnectionError(Exception):
    """Kegagalan sebelum sempat bicara dengan RouterOS API (mis. metadata
    device tidak lengkap) — dibedakan dari error RouterOS API itu sendiri
    supaya pesan errornya jelas menunjuk ke masalah konfigurasi device."""


def _connect(device: Device, password: str | None):
    """
    Factory koneksi RouterOS API — SATU tempat kebenaran untuk parameter
    koneksi seluruh tool mikrotik.* di file ini, dipanggil dari dalam
    *_sync() (thread terpisah lewat asyncio.to_thread), BUKAN langsung
    di executor async (README section 4).

    device.connection_type menentukan API biasa ("api", default) vs
    API-SSL ("api-ssl") — lihat CATATAN KEAMANAN di docstring modul ini
    soal verifikasi sertifikat API-SSL yang sengaja dimatikan untuk lab.

    Username WAJIB ada di device.device_metadata (mis.
    {"username": "admin"}) — diisi user saat POST /devices, bukan
    hardcoded, konsisten dengan contoh ExecutionContext di README
    section 3 (`ctx.device.device_metadata.get("username")`).
    """
    username = (device.device_metadata or {}).get("username")
    if not username:
        raise MikrotikConnectionError(
            "Device metadata tidak berisi 'username' — wajib diisi saat "
            "mendaftarkan device MikroTik lewat POST /devices "
            "(metadata: {'username': '...'})."
        )

    if password is None:
        raise MikrotikConnectionError(
            "Device ini belum memiliki credential (password/API user) "
            "yang bisa dipakai untuk autentikasi RouterOS API."
        )

    ssl_wrapper = None
    if (device.connection_type or "api").lower() == "api-ssl":
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        ssl_wrapper = context.wrap_socket

    return librouteros.connect(
        host=device.host,
        port=device.port,
        username=username,
        password=password,
        timeout=_CONNECT_TIMEOUT_SECONDS,
        ssl_wrapper=ssl_wrapper,
    )


def _to_bool(value) -> bool:
    """RouterOS API mengembalikan boolean sebagai string 'true'/'false'
    tergantung versi library — normalisasi supaya output tool konsisten."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def _safe_int(value) -> int | None:
    """RouterOS sering mengembalikan angka sebagai string (mis. cpu-load
    '3', free-memory '134217728') — parse defensif, None kalau gagal."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _connection_error_message(exc: Exception) -> str:
    """Pesan error seragam untuk seluruh tool di file ini — TIDAK PERNAH
    menyertakan password (exc dari librouteros tidak membawa password,
    tapi tetap dilewatkan lewat sanitasi umum di app/security/sanitization
    sebagai lapisan pertahanan kedua di app/tools/manager.py)."""
    return f"Connection error: {exc}"


# ============================================================
# mikrotik.system_resource
# ============================================================

class SystemResourceInput(BaseModel):
    """Tidak butuh argumen dari LLM — device ditentukan lewat
    ToolRequest.device_id, diresolusi Tool Manager menjadi ctx.device."""


class SystemResourceOutput(BaseModel):
    success: bool
    identity: str | None = None
    board_name: str | None = None
    routeros_version: str | None = None
    architecture: str | None = None
    cpu_load_percent: int | None = None
    free_memory_bytes: int | None = None
    total_memory_bytes: int | None = None
    uptime: str | None = None
    error: str | None = None


def _system_resource_sync(device: Device, password: str | None) -> dict:
    with _connect(device, password) as api:
        resource_rows = list(api.path("system", "resource"))
        identity_rows = list(api.path("system", "identity"))
    return {
        "resource": resource_rows[0] if resource_rows else {},
        "identity": identity_rows[0] if identity_rows else {},
    }


async def execute_system_resource(
    input: SystemResourceInput, ctx: ExecutionContext | None = None
) -> SystemResourceOutput:
    if ctx is None or ctx.device is None:
        return SystemResourceOutput(success=False, error="Device context tidak tersedia.")

    try:
        raw = await asyncio.to_thread(_system_resource_sync, ctx.device, ctx.credential_plaintext)
    except MikrotikConnectionError as exc:
        return SystemResourceOutput(success=False, error=str(exc))
    except librouteros.exceptions.TrapError as exc:
        return SystemResourceOutput(success=False, error=f"RouterOS API error: {exc}")
    except (OSError, librouteros.exceptions.ConnectionClosed, librouteros.exceptions.ProtocolError) as exc:
        return SystemResourceOutput(success=False, error=_connection_error_message(exc))

    resource_row = raw["resource"]
    identity_row = raw["identity"]
    return SystemResourceOutput(
        success=True,
        identity=identity_row.get("name"),
        board_name=resource_row.get("board-name"),
        routeros_version=resource_row.get("version"),
        architecture=resource_row.get("architecture-name"),
        cpu_load_percent=_safe_int(resource_row.get("cpu-load")),
        free_memory_bytes=_safe_int(resource_row.get("free-memory")),
        total_memory_bytes=_safe_int(resource_row.get("total-memory")),
        uptime=resource_row.get("uptime"),
    )


system_resource_tool = ToolDefinition(
    name="mikrotik.system_resource",
    description=(
        "Membaca identity, versi RouterOS, board, CPU/memory, dan uptime "
        "sebuah device MikroTik lewat RouterOS API."
    ),
    input_model=SystemResourceInput,
    output_model=SystemResourceOutput,
    permission_level=PermissionLevel.READ,
    risk_level=RiskLevel.LOW,
    supported_platforms=["mikrotik"],
    requires_device=True,
    timeout_seconds=15.0,
    logging_policy=LoggingPolicy.RESULT_ONLY,
    executor=execute_system_resource,
)


# ============================================================
# mikrotik.interface_status
# ============================================================

class InterfaceStatusInput(BaseModel):
    """Tidak butuh argumen — membaca seluruh interface pada device."""


class InterfaceEntry(BaseModel):
    name: str
    type: str | None = None
    running: bool
    disabled: bool
    comment: str | None = None


class InterfaceStatusOutput(BaseModel):
    success: bool
    interfaces: list[InterfaceEntry] = []
    error: str | None = None


def _interface_status_sync(device: Device, password: str | None) -> list[dict]:
    with _connect(device, password) as api:
        return list(api.path("interface"))


async def execute_interface_status(
    input: InterfaceStatusInput, ctx: ExecutionContext | None = None
) -> InterfaceStatusOutput:
    if ctx is None or ctx.device is None:
        return InterfaceStatusOutput(success=False, error="Device context tidak tersedia.")

    try:
        rows = await asyncio.to_thread(_interface_status_sync, ctx.device, ctx.credential_plaintext)
    except MikrotikConnectionError as exc:
        return InterfaceStatusOutput(success=False, error=str(exc))
    except librouteros.exceptions.TrapError as exc:
        return InterfaceStatusOutput(success=False, error=f"RouterOS API error: {exc}")
    except (OSError, librouteros.exceptions.ConnectionClosed, librouteros.exceptions.ProtocolError) as exc:
        return InterfaceStatusOutput(success=False, error=_connection_error_message(exc))

    interfaces = [
        InterfaceEntry(
            name=row.get("name", ""),
            type=row.get("type"),
            running=_to_bool(row.get("running", False)),
            disabled=_to_bool(row.get("disabled", False)),
            comment=row.get("comment"),
        )
        for row in rows
    ]
    return InterfaceStatusOutput(success=True, interfaces=interfaces)


interface_status_tool = ToolDefinition(
    name="mikrotik.interface_status",
    description="Membaca daftar interface pada device MikroTik beserta status running/disabled.",
    input_model=InterfaceStatusInput,
    output_model=InterfaceStatusOutput,
    permission_level=PermissionLevel.READ,
    risk_level=RiskLevel.LOW,
    supported_platforms=["mikrotik"],
    requires_device=True,
    timeout_seconds=15.0,
    logging_policy=LoggingPolicy.RESULT_ONLY,
    executor=execute_interface_status,
)


# ============================================================
# mikrotik.ip_address
# ============================================================

class IpAddressInput(BaseModel):
    """Tidak butuh argumen — membaca seluruh IP address yang dikonfigurasi."""


class IpAddressEntry(BaseModel):
    address: str
    network: str | None = None
    interface: str | None = None
    disabled: bool


class IpAddressOutput(BaseModel):
    success: bool
    addresses: list[IpAddressEntry] = []
    error: str | None = None


def _ip_address_sync(device: Device, password: str | None) -> list[dict]:
    with _connect(device, password) as api:
        return list(api.path("ip", "address"))


async def execute_ip_address(
    input: IpAddressInput, ctx: ExecutionContext | None = None
) -> IpAddressOutput:
    if ctx is None or ctx.device is None:
        return IpAddressOutput(success=False, error="Device context tidak tersedia.")

    try:
        rows = await asyncio.to_thread(_ip_address_sync, ctx.device, ctx.credential_plaintext)
    except MikrotikConnectionError as exc:
        return IpAddressOutput(success=False, error=str(exc))
    except librouteros.exceptions.TrapError as exc:
        return IpAddressOutput(success=False, error=f"RouterOS API error: {exc}")
    except (OSError, librouteros.exceptions.ConnectionClosed, librouteros.exceptions.ProtocolError) as exc:
        return IpAddressOutput(success=False, error=_connection_error_message(exc))

    addresses = [
        IpAddressEntry(
            address=row.get("address", ""),
            network=row.get("network"),
            interface=row.get("interface"),
            disabled=_to_bool(row.get("disabled", False)),
        )
        for row in rows
    ]
    return IpAddressOutput(success=True, addresses=addresses)


ip_address_tool = ToolDefinition(
    name="mikrotik.ip_address",
    description="Membaca seluruh IP address yang dikonfigurasi pada device MikroTik, per interface.",
    input_model=IpAddressInput,
    output_model=IpAddressOutput,
    permission_level=PermissionLevel.READ,
    risk_level=RiskLevel.LOW,
    supported_platforms=["mikrotik"],
    requires_device=True,
    timeout_seconds=15.0,
    logging_policy=LoggingPolicy.RESULT_ONLY,
    executor=execute_ip_address,
)


# ============================================================
# mikrotik.route_table
# ============================================================

class RouteTableInput(BaseModel):
    active_only: bool = Field(
        default=False, description="Hanya kembalikan route yang berstatus active."
    )


class RouteEntry(BaseModel):
    dst_address: str
    gateway: str | None = None
    distance: int | None = None
    active: bool
    disabled: bool


class RouteTableOutput(BaseModel):
    success: bool
    routes: list[RouteEntry] = []
    error: str | None = None


def _route_table_sync(device: Device, password: str | None) -> list[dict]:
    with _connect(device, password) as api:
        return list(api.path("ip", "route"))


async def execute_route_table(
    input: RouteTableInput, ctx: ExecutionContext | None = None
) -> RouteTableOutput:
    if ctx is None or ctx.device is None:
        return RouteTableOutput(success=False, error="Device context tidak tersedia.")

    try:
        rows = await asyncio.to_thread(_route_table_sync, ctx.device, ctx.credential_plaintext)
    except MikrotikConnectionError as exc:
        return RouteTableOutput(success=False, error=str(exc))
    except librouteros.exceptions.TrapError as exc:
        return RouteTableOutput(success=False, error=f"RouterOS API error: {exc}")
    except (OSError, librouteros.exceptions.ConnectionClosed, librouteros.exceptions.ProtocolError) as exc:
        return RouteTableOutput(success=False, error=_connection_error_message(exc))

    routes: list[RouteEntry] = []
    for row in rows:
        active = _to_bool(row.get("active", False))
        # Filter dilakukan di sisi backend (bukan query RouterOS mentah),
        # konsisten dengan pola linux.process_status.name_filter.
        if input.active_only and not active:
            continue
        routes.append(
            RouteEntry(
                dst_address=row.get("dst-address", ""),
                gateway=row.get("gateway"),
                distance=_safe_int(row.get("distance")),
                active=active,
                disabled=_to_bool(row.get("disabled", False)),
            )
        )

    return RouteTableOutput(success=True, routes=routes)


route_table_tool = ToolDefinition(
    name="mikrotik.route_table",
    description="Membaca tabel routing (ip route) device MikroTik, dengan filter opsional hanya route aktif.",
    input_model=RouteTableInput,
    output_model=RouteTableOutput,
    permission_level=PermissionLevel.READ,
    risk_level=RiskLevel.LOW,
    supported_platforms=["mikrotik"],
    requires_device=True,
    timeout_seconds=15.0,
    logging_policy=LoggingPolicy.RESULT_ONLY,
    executor=execute_route_table,
)


# ============================================================
# mikrotik.arp_table
# ============================================================

class ArpTableInput(BaseModel):
    """Tidak butuh argumen — membaca seluruh entry ARP table."""


class ArpEntry(BaseModel):
    address: str
    mac_address: str | None = None
    interface: str | None = None
    complete: bool


class ArpTableOutput(BaseModel):
    success: bool
    entries: list[ArpEntry] = []
    error: str | None = None


def _arp_table_sync(device: Device, password: str | None) -> list[dict]:
    with _connect(device, password) as api:
        return list(api.path("ip", "arp"))


async def execute_arp_table(
    input: ArpTableInput, ctx: ExecutionContext | None = None
) -> ArpTableOutput:
    if ctx is None or ctx.device is None:
        return ArpTableOutput(success=False, error="Device context tidak tersedia.")

    try:
        rows = await asyncio.to_thread(_arp_table_sync, ctx.device, ctx.credential_plaintext)
    except MikrotikConnectionError as exc:
        return ArpTableOutput(success=False, error=str(exc))
    except librouteros.exceptions.TrapError as exc:
        return ArpTableOutput(success=False, error=f"RouterOS API error: {exc}")
    except (OSError, librouteros.exceptions.ConnectionClosed, librouteros.exceptions.ProtocolError) as exc:
        return ArpTableOutput(success=False, error=_connection_error_message(exc))

    entries = [
        ArpEntry(
            address=row.get("address", ""),
            mac_address=row.get("mac-address"),
            interface=row.get("interface"),
            complete=_to_bool(row.get("complete", False)),
        )
        for row in rows
    ]
    return ArpTableOutput(success=True, entries=entries)


arp_table_tool = ToolDefinition(
    name="mikrotik.arp_table",
    description="Membaca ARP table (ip arp) device MikroTik — pemetaan IP ke MAC address per interface.",
    input_model=ArpTableInput,
    output_model=ArpTableOutput,
    permission_level=PermissionLevel.READ,
    risk_level=RiskLevel.LOW,
    supported_platforms=["mikrotik"],
    requires_device=True,
    timeout_seconds=15.0,
    logging_policy=LoggingPolicy.RESULT_ONLY,
    executor=execute_arp_table,
)


# ============================================================
# mikrotik.dhcp_leases
# ============================================================
#
# Risk MEDIUM (bukan LOW seperti tool di atas) — README section 5:
# "baca data yang lebih sensitif (firewall rules, DHCP lease berisi
# MAC/hostname client)". Tetap permission READ (hanya baca), tapi
# risk classification-nya mengakui bahwa isinya bisa dipakai untuk
# fingerprinting perangkat/pengguna di jaringan target.

class DhcpLeasesInput(BaseModel):
    """Tidak butuh argumen — membaca seluruh DHCP lease pada device."""


class DhcpLeaseEntry(BaseModel):
    address: str
    mac_address: str | None = None
    host_name: str | None = None
    status: str | None = None
    server: str | None = None


class DhcpLeasesOutput(BaseModel):
    success: bool
    leases: list[DhcpLeaseEntry] = []
    error: str | None = None


def _dhcp_leases_sync(device: Device, password: str | None) -> list[dict]:
    with _connect(device, password) as api:
        return list(api.path("ip", "dhcp-server", "lease"))


async def execute_dhcp_leases(
    input: DhcpLeasesInput, ctx: ExecutionContext | None = None
) -> DhcpLeasesOutput:
    if ctx is None or ctx.device is None:
        return DhcpLeasesOutput(success=False, error="Device context tidak tersedia.")

    try:
        rows = await asyncio.to_thread(_dhcp_leases_sync, ctx.device, ctx.credential_plaintext)
    except MikrotikConnectionError as exc:
        return DhcpLeasesOutput(success=False, error=str(exc))
    except librouteros.exceptions.TrapError as exc:
        return DhcpLeasesOutput(success=False, error=f"RouterOS API error: {exc}")
    except (OSError, librouteros.exceptions.ConnectionClosed, librouteros.exceptions.ProtocolError) as exc:
        return DhcpLeasesOutput(success=False, error=_connection_error_message(exc))

    leases = [
        DhcpLeaseEntry(
            address=row.get("address", ""),
            mac_address=row.get("mac-address"),
            host_name=row.get("host-name"),
            status=row.get("status"),
            server=row.get("server"),
        )
        for row in rows
    ]
    return DhcpLeasesOutput(success=True, leases=leases)


dhcp_leases_tool = ToolDefinition(
    name="mikrotik.dhcp_leases",
    description=(
        "Membaca seluruh DHCP lease aktif device MikroTik (IP, MAC "
        "address, hostname client). Risk MEDIUM karena berisi data "
        "yang bisa dipakai fingerprinting perangkat client."
    ),
    input_model=DhcpLeasesInput,
    output_model=DhcpLeasesOutput,
    permission_level=PermissionLevel.READ,
    risk_level=RiskLevel.MEDIUM,
    supported_platforms=["mikrotik"],
    requires_device=True,
    timeout_seconds=15.0,
    logging_policy=LoggingPolicy.RESULT_ONLY,
    executor=execute_dhcp_leases,
)


# ============================================================
# mikrotik.firewall_rules
# ============================================================
#
# Satu-satunya tool di batch ini dengan argumen bebas dari luar
# ('chain'). Sesuai README checklist ("Tool yang menerima argumen
# bebas dari luar WAJIB divalidasi ketat"), 'chain' divalidasi regex
# whitelist di level Pydantic Field(pattern=...) — pola identik dengan
# _SERVICE_NAME_PATTERN di app/tools/linux.py. Filter tetap dilakukan
# di sisi backend (Python, setelah data diambil) — TIDAK pernah
# disisipkan mentah-mentah ke query RouterOS API.

_CHAIN_NAME_PATTERN = r"^[a-zA-Z0-9_-]+$"


class FirewallRulesInput(BaseModel):
    chain: str | None = Field(
        default=None,
        pattern=_CHAIN_NAME_PATTERN,
        max_length=64,
        description="Filter opsional berdasarkan nama chain (mis. 'input', 'forward', 'output').",
    )


class FirewallRuleEntry(BaseModel):
    chain: str
    action: str | None = None
    src_address: str | None = None
    dst_address: str | None = None
    protocol: str | None = None
    disabled: bool
    comment: str | None = None


class FirewallRulesOutput(BaseModel):
    success: bool
    rules: list[FirewallRuleEntry] = []
    error: str | None = None


def _firewall_rules_sync(device: Device, password: str | None) -> list[dict]:
    with _connect(device, password) as api:
        return list(api.path("ip", "firewall", "filter"))


async def execute_firewall_rules(
    input: FirewallRulesInput, ctx: ExecutionContext | None = None
) -> FirewallRulesOutput:
    if ctx is None or ctx.device is None:
        return FirewallRulesOutput(success=False, error="Device context tidak tersedia.")

    try:
        rows = await asyncio.to_thread(_firewall_rules_sync, ctx.device, ctx.credential_plaintext)
    except MikrotikConnectionError as exc:
        return FirewallRulesOutput(success=False, error=str(exc))
    except librouteros.exceptions.TrapError as exc:
        return FirewallRulesOutput(success=False, error=f"RouterOS API error: {exc}")
    except (OSError, librouteros.exceptions.ConnectionClosed, librouteros.exceptions.ProtocolError) as exc:
        return FirewallRulesOutput(success=False, error=_connection_error_message(exc))

    rules: list[FirewallRuleEntry] = []
    for row in rows:
        chain = row.get("chain", "")
        if input.chain and chain != input.chain:
            continue
        rules.append(
            FirewallRuleEntry(
                chain=chain,
                action=row.get("action"),
                src_address=row.get("src-address"),
                dst_address=row.get("dst-address"),
                protocol=row.get("protocol"),
                disabled=_to_bool(row.get("disabled", False)),
                comment=row.get("comment"),
            )
        )

    return FirewallRulesOutput(success=True, rules=rules)


firewall_rules_tool = ToolDefinition(
    name="mikrotik.firewall_rules",
    description=(
        "Membaca rule firewall (ip firewall filter) device MikroTik, "
        "dengan filter opsional per chain. Risk MEDIUM karena firewall "
        "rules adalah informasi keamanan sensitif."
    ),
    input_model=FirewallRulesInput,
    output_model=FirewallRulesOutput,
    permission_level=PermissionLevel.READ,
    risk_level=RiskLevel.MEDIUM,
    supported_platforms=["mikrotik"],
    requires_device=True,
    timeout_seconds=15.0,
    logging_policy=LoggingPolicy.RESULT_ONLY,
    executor=execute_firewall_rules,
)