"""
Test integrasi (mocked RouterOS API) untuk tool mikrotik.* — batch pertama.

Pola sama persis dengan tests/test_linux_ssh.py (mocked asyncssh): tidak
perlu device MikroTik sungguhan, `librouteros.connect()` di-mock
sepenuhnya lewat FakeApi + FakeConnectionContextManager, deterministik
dan cepat.

Yang diuji per tool:
1. Jalur sukses — parsing baris RouterOS API (termasuk boolean
   'true'/'false' string dan angka string) jadi output terstruktur.
2. Jalur gagal koneksi (TrapError / OSError) -> success=False + error,
   TIDAK PERNAH exception mentah bocor (README checklist section 6).
3. ctx=None / ctx.device=None -> defensive fallback, bukan crash.
4. Device metadata tanpa 'username' -> error jelas, bukan raw exception
   library.

Plus, khusus mikrotik.firewall_rules:
5. Injection defense untuk argumen bebas 'chain' — reuse semangat
   INJECTION_PAYLOADS dari test_linux_injection.py (whitelist regex di
   level Pydantic, sebelum sempat menyentuh koneksi RouterOS API).
"""

import uuid
from unittest.mock import patch

import librouteros.exceptions
import pytest

from app.database.models import Device
from app.tools.context import ExecutionContext
from app.tools.mikrotik import (
    ArpTableInput,
    DhcpLeasesInput,
    FirewallRulesInput,
    InterfaceStatusInput,
    IpAddressInput,
    RouteTableInput,
    SystemResourceInput,
    execute_arp_table,
    execute_dhcp_leases,
    execute_firewall_rules,
    execute_interface_status,
    execute_ip_address,
    execute_route_table,
    execute_system_resource,
)
from app.tools.manager import ToolValidationError, tool_manager
from app.tools.schemas import RiskLevel, ToolRequest


# ============================================================
# Fakes — meniru librouteros.connect() sebagai context manager
# ============================================================

class FakeApi:
    """Tiruan objek Api dari librouteros.connect().

    `responses` memetakan tuple path (mis. ('ip', 'address')) ke list
    of dict baris — supaya urutan pemanggilan api.path() di dalam satu
    executor tidak perlu dihafal, sama seperti FakeConnection di
    test_linux_ssh.py yang mencocokkan berdasarkan isi command.
    """

    def __init__(self, responses: dict[tuple, list[dict]]):
        self._responses = responses

    def path(self, *parts):
        key = tuple(parts)
        if key not in self._responses:
            raise AssertionError(
                f"Path tak terduga dipanggil dalam test: {key!r}. "
                f"Path yang di-mock: {list(self._responses.keys())}"
            )
        return self._responses[key]


class FakeConnectionContextManager:
    """Tiruan objek yang dikembalikan librouteros.connect() — dipakai
    lewat `with _connect(...) as api`, jadi harus mendukung context
    manager protocol (sama seperti FakeConnectionContextManager di
    test_linux_ssh.py untuk asyncssh)."""

    def __init__(self, api: FakeApi | None = None, connect_error: Exception | None = None):
        self._api = api
        self._connect_error = connect_error

    def __enter__(self) -> FakeApi:
        if self._connect_error is not None:
            raise self._connect_error
        return self._api

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _mock_connect_success(responses: dict[tuple, list[dict]]):
    api = FakeApi(responses)
    return patch(
        "app.tools.mikrotik.librouteros.connect",
        return_value=FakeConnectionContextManager(api=api),
    )


def _mock_connect_failure(exc: Exception):
    return patch(
        "app.tools.mikrotik.librouteros.connect",
        return_value=FakeConnectionContextManager(connect_error=exc),
    )


def _make_device(
    *,
    connection_type: str = "api",
    metadata: dict | None = None,
    platform: str = "mikrotik",
) -> Device:
    """Device MikroTik in-memory murni (tidak disentuh DB sama sekali) —
    cukup untuk executor karena executor hanya membaca atribut Python
    biasa dari objek ini, tidak melakukan query."""
    return Device(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        name="lab-mikrotik-01",
        platform=platform,
        host="192.168.88.1",
        port=8728,
        connection_type=connection_type,
        status="active",
        device_metadata=metadata if metadata is not None else {"username": "admin"},
    )


def _make_ctx(device: Device | None, password: str | None = "hunter2") -> ExecutionContext:
    return ExecutionContext(user=None, db=None, device=device, credential_plaintext=password)


# ============================================================
# mikrotik.system_resource
# ============================================================

class TestSystemResource:
    @pytest.mark.asyncio
    async def test_success_parses_all_fields(self):
        responses = {
            ("system", "resource"): [
                {
                    "board-name": "CHR",
                    "version": "7.15 (stable)",
                    "architecture-name": "x86_64",
                    "cpu-load": "3",
                    "free-memory": "134217728",
                    "total-memory": "268435456",
                    "uptime": "1w2d3h4m5s",
                }
            ],
            ("system", "identity"): [{"name": "lab-router"}],
        }
        with _mock_connect_success(responses):
            result = await execute_system_resource(
                SystemResourceInput(), _make_ctx(_make_device())
            )

        assert result.success is True
        assert result.identity == "lab-router"
        assert result.board_name == "CHR"
        assert result.routeros_version == "7.15 (stable)"
        assert result.cpu_load_percent == 3
        assert result.free_memory_bytes == 134217728
        assert result.total_memory_bytes == 268435456
        assert result.uptime == "1w2d3h4m5s"

    @pytest.mark.asyncio
    async def test_no_ctx_returns_success_false_not_exception(self):
        result = await execute_system_resource(SystemResourceInput(), None)
        assert result.success is False
        assert "Device context" in result.error

    @pytest.mark.asyncio
    async def test_ctx_without_device_returns_success_false(self):
        result = await execute_system_resource(SystemResourceInput(), _make_ctx(None))
        assert result.success is False

    @pytest.mark.asyncio
    async def test_missing_username_in_metadata_returns_clear_error(self):
        device = _make_device(metadata={})
        result = await execute_system_resource(SystemResourceInput(), _make_ctx(device))
        assert result.success is False
        assert "username" in result.error


# ============================================================
# mikrotik.interface_status
# ============================================================

class TestInterfaceStatus:
    @pytest.mark.asyncio
    async def test_success_parses_running_and_disabled_string_booleans(self):
        responses = {
            ("interface",): [
                {"name": "ether1", "type": "ether", "running": "true", "disabled": "false", "comment": "WAN"},
                {"name": "ether2", "type": "ether", "running": "false", "disabled": "true"},
            ]
        }
        with _mock_connect_success(responses):
            result = await execute_interface_status(
                InterfaceStatusInput(), _make_ctx(_make_device())
            )

        assert result.success is True
        assert len(result.interfaces) == 2
        assert result.interfaces[0].name == "ether1"
        assert result.interfaces[0].running is True
        assert result.interfaces[0].disabled is False
        assert result.interfaces[0].comment == "WAN"
        assert result.interfaces[1].running is False
        assert result.interfaces[1].disabled is True

    @pytest.mark.asyncio
    async def test_trap_error_returns_success_false_not_exception(self):
        with _mock_connect_failure(librouteros.exceptions.TrapError("bad command")):
            result = await execute_interface_status(
                InterfaceStatusInput(), _make_ctx(_make_device())
            )
        assert result.success is False
        assert "RouterOS API error" in result.error

    @pytest.mark.asyncio
    async def test_os_error_returns_success_false_not_exception(self):
        with _mock_connect_failure(OSError("Network is unreachable")):
            result = await execute_interface_status(
                InterfaceStatusInput(), _make_ctx(_make_device())
            )
        assert result.success is False
        assert "Connection error" in result.error


# ============================================================
# mikrotik.ip_address
# ============================================================

class TestIpAddress:
    @pytest.mark.asyncio
    async def test_success_parses_addresses(self):
        responses = {
            ("ip", "address"): [
                {"address": "192.168.88.1/24", "network": "192.168.88.0", "interface": "ether1", "disabled": "false"},
            ]
        }
        with _mock_connect_success(responses):
            result = await execute_ip_address(IpAddressInput(), _make_ctx(_make_device()))

        assert result.success is True
        assert len(result.addresses) == 1
        assert result.addresses[0].address == "192.168.88.1/24"
        assert result.addresses[0].interface == "ether1"
        assert result.addresses[0].disabled is False


# ============================================================
# mikrotik.route_table
# ============================================================

class TestRouteTable:
    @pytest.mark.asyncio
    async def test_active_only_filters_backend_side(self):
        responses = {
            ("ip", "route"): [
                {"dst-address": "0.0.0.0/0", "gateway": "192.168.88.1", "distance": "1", "active": "true", "disabled": "false"},
                {"dst-address": "10.0.0.0/8", "gateway": "192.168.88.2", "distance": "5", "active": "false", "disabled": "false"},
            ]
        }
        with _mock_connect_success(responses):
            result = await execute_route_table(
                RouteTableInput(active_only=True), _make_ctx(_make_device())
            )

        assert result.success is True
        assert len(result.routes) == 1
        assert result.routes[0].dst_address == "0.0.0.0/0"
        assert result.routes[0].distance == 1

    @pytest.mark.asyncio
    async def test_active_only_false_returns_all(self):
        responses = {
            ("ip", "route"): [
                {"dst-address": "0.0.0.0/0", "active": "true", "disabled": "false"},
                {"dst-address": "10.0.0.0/8", "active": "false", "disabled": "false"},
            ]
        }
        with _mock_connect_success(responses):
            result = await execute_route_table(
                RouteTableInput(active_only=False), _make_ctx(_make_device())
            )
        assert len(result.routes) == 2


# ============================================================
# mikrotik.arp_table
# ============================================================

class TestArpTable:
    @pytest.mark.asyncio
    async def test_success_parses_entries(self):
        responses = {
            ("ip", "arp"): [
                {"address": "192.168.88.10", "mac-address": "AA:BB:CC:DD:EE:FF", "interface": "ether1", "complete": "true"},
            ]
        }
        with _mock_connect_success(responses):
            result = await execute_arp_table(ArpTableInput(), _make_ctx(_make_device()))

        assert result.success is True
        assert result.entries[0].mac_address == "AA:BB:CC:DD:EE:FF"
        assert result.entries[0].complete is True


# ============================================================
# mikrotik.dhcp_leases (risk MEDIUM)
# ============================================================

class TestDhcpLeases:
    @pytest.mark.asyncio
    async def test_success_parses_leases(self):
        responses = {
            ("ip", "dhcp-server", "lease"): [
                {"address": "192.168.88.50", "mac-address": "11:22:33:44:55:66", "host-name": "laptop-budi", "status": "bound", "server": "dhcp1"},
            ]
        }
        with _mock_connect_success(responses):
            result = await execute_dhcp_leases(DhcpLeasesInput(), _make_ctx(_make_device()))

        assert result.success is True
        assert result.leases[0].host_name == "laptop-budi"

    def test_tool_definition_risk_level_is_medium(self):
        from app.tools.mikrotik import dhcp_leases_tool
        assert dhcp_leases_tool.risk_level == RiskLevel.MEDIUM


# ============================================================
# mikrotik.firewall_rules (risk MEDIUM + injection defense)
# ============================================================

class TestFirewallRules:
    @pytest.mark.asyncio
    async def test_success_filters_by_chain(self):
        responses = {
            ("ip", "firewall", "filter"): [
                {"chain": "input", "action": "accept", "src-address": "192.168.88.0/24", "disabled": "false"},
                {"chain": "forward", "action": "drop", "disabled": "false"},
            ]
        }
        with _mock_connect_success(responses):
            result = await execute_firewall_rules(
                FirewallRulesInput(chain="input"), _make_ctx(_make_device())
            )

        assert result.success is True
        assert len(result.rules) == 1
        assert result.rules[0].chain == "input"

    def test_tool_definition_risk_level_is_medium(self):
        from app.tools.mikrotik import firewall_rules_tool
        assert firewall_rules_tool.risk_level == RiskLevel.MEDIUM

    @pytest.mark.parametrize(
        "payload",
        [
            "input; rm -rf /",
            "input && whoami",
            "input || whoami",
            "input | whoami",
            "input `whoami`",
            "input $(whoami)",
            "input\nwhoami",
            "../../../etc/passwd",
            "input -x",
            "input > /tmp/pwned",
            "a" * 65,
        ],
    )
    def test_malicious_chain_rejected_by_schema(self, payload):
        """Reuse semangat INJECTION_PAYLOADS (test_linux_injection.py):
        'chain' WAJIB ditolak Pydantic Field(pattern=...) sebelum sempat
        dipakai untuk apa pun, apalagi menyentuh koneksi RouterOS API."""
        with pytest.raises(Exception):
            FirewallRulesInput(chain=payload)


# ============================================================
# SSH/connection failure — regresi untuk SELURUH tool mikrotik.*
# (pola sama dengan TestSSHFailureNeverLeaksRawException di
# test_linux_ssh.py)
# ============================================================

class TestMikrotikFailureNeverLeaksRawException:
    @pytest.mark.parametrize(
        "executor,input_instance",
        [
            (execute_system_resource, SystemResourceInput()),
            (execute_interface_status, InterfaceStatusInput()),
            (execute_ip_address, IpAddressInput()),
            (execute_route_table, RouteTableInput()),
            (execute_arp_table, ArpTableInput()),
            (execute_dhcp_leases, DhcpLeasesInput()),
            (execute_firewall_rules, FirewallRulesInput()),
        ],
    )
    @pytest.mark.asyncio
    async def test_trap_error_handled_gracefully(self, executor, input_instance):
        with _mock_connect_failure(librouteros.exceptions.TrapError("invalid user name or password")):
            result = await executor(input_instance, _make_ctx(_make_device()))
        assert result.success is False
        assert result.error is not None

    @pytest.mark.parametrize(
        "executor,input_instance",
        [
            (execute_system_resource, SystemResourceInput()),
            (execute_interface_status, InterfaceStatusInput()),
            (execute_ip_address, IpAddressInput()),
            (execute_route_table, RouteTableInput()),
            (execute_arp_table, ArpTableInput()),
            (execute_dhcp_leases, DhcpLeasesInput()),
            (execute_firewall_rules, FirewallRulesInput()),
        ],
    )
    @pytest.mark.asyncio
    async def test_os_error_handled_gracefully(self, executor, input_instance):
        with _mock_connect_failure(OSError("Connection timed out")):
            result = await executor(input_instance, _make_ctx(_make_device()))
        assert result.success is False
        assert result.error is not None


# ============================================================
# Tool registration / ToolManager wiring sanity checks
# ============================================================

class TestMikrotikToolRegistration:
    def test_all_mikrotik_tools_registered_at_startup(self):
        from app.main import app  # noqa: F401 — memicu registrasi tool

        expected = {
            "mikrotik.system_resource",
            "mikrotik.interface_status",
            "mikrotik.ip_address",
            "mikrotik.route_table",
            "mikrotik.arp_table",
            "mikrotik.dhcp_leases",
            "mikrotik.firewall_rules",
        }
        assert expected.issubset(set(tool_manager.list_tools()))

    def test_all_mikrotik_tools_require_device(self):
        from app.main import app  # noqa: F401

        for name in [
            "mikrotik.system_resource",
            "mikrotik.interface_status",
            "mikrotik.ip_address",
            "mikrotik.route_table",
            "mikrotik.arp_table",
            "mikrotik.dhcp_leases",
            "mikrotik.firewall_rules",
        ]:
            tool = tool_manager.get_tool(name)
            assert tool is not None
            assert tool.requires_device is True

    @pytest.mark.asyncio
    async def test_execute_without_device_id_rejected_before_executor(self):
        """README section 3: 'Kalau requires_device=True tapi request
        tidak menyertakan device_id, Tool Manager menolak SEBELUM
        executor dipanggil (pesan jelas: tool ini butuh device_id).'"""
        from app.main import app  # noqa: F401
        from app.database.models import User

        fake_user = User(id=uuid.uuid4(), email="mikrotik-test@example.com", hashed_password="x", is_active=True)
        request = ToolRequest(
            tool_name="mikrotik.system_resource",
            arguments={},
            confirmed=False,
            device_id=None,
        )
        with pytest.raises(ToolValidationError, match="device_id"):
            await tool_manager.execute(request, user=fake_user)