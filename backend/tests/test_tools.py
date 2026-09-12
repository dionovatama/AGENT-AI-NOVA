"""
Test untuk Tool Manager (Milestone 3).

Mencakup (sesuai PRD section 43 - Testing > Unit Testing):
- Tool validation (schema)
- Permission system
- Risk classification tidak mengubah keputusan permission
- Allowlist (tool tak terdaftar harus ditolak)

Ping benar-benar dieksekusi ke 127.0.0.1 (loopback) — bukan mock —
karena tool ini murni menjalankan binary sistem, bukan memanggil API
eksternal. Tidak menimbulkan biaya atau side effect berbahaya.
"""

import pytest

from app.main import app  # memicu registrasi tool ke tool_manager saat import
from app.tools.manager import (
    ToolExecutionError,
    ToolNotFoundError,
    ToolValidationError,
    tool_manager,
)
from app.tools.schemas import PermissionLevel, RiskLevel, ToolRequest
from app.security.permissions import PermissionDeniedError, check_permission


class TestPermissionSystem:
    def test_read_permission_always_allowed(self):
        # READ tidak boleh butuh confirmed=True.
        check_permission(PermissionLevel.READ, confirmed=False)  # tidak raise = lulus

    def test_modify_requires_confirmation(self):
        with pytest.raises(PermissionDeniedError):
            check_permission(PermissionLevel.MODIFY, confirmed=False)
        check_permission(PermissionLevel.MODIFY, confirmed=True)  # tidak raise = lulus

    def test_high_risk_requires_confirmation(self):
        with pytest.raises(PermissionDeniedError):
            check_permission(PermissionLevel.HIGH_RISK, confirmed=False)
        check_permission(PermissionLevel.HIGH_RISK, confirmed=True)  # tidak raise = lulus


class TestToolManagerAllowlist:
    def test_ping_is_registered_at_startup(self):
        # main.py mendaftarkan ping_tool saat app di-import.
        assert "ping" in tool_manager.list_tools()

    @pytest.mark.asyncio
    async def test_unregistered_tool_is_rejected(self):
        request = ToolRequest(tool_name="shell_exec", arguments={}, confirmed=True)
        with pytest.raises(ToolNotFoundError):
            await tool_manager.execute(request)


class TestPingToolExecution:
    @pytest.mark.asyncio
    async def test_ping_localhost_succeeds(self):
        """
        Tool READ (ping) harus jalan tanpa confirmed=True.

        Catatan lingkungan: beberapa mesin (terutama Windows dengan
        Windows Firewall default) memblokir ICMPv4 Echo Request bahkan
        ke loopback (127.0.0.1). Ini adalah masalah konfigurasi jaringan
        di mesin tersebut, bukan bug NOVA — tool tetap WAJIB mengembalikan
        struktur ToolResult yang valid (bukan exception) baik ping
        berhasil maupun gagal karena diblokir firewall.
        """
        request = ToolRequest(
            tool_name="ping",
            arguments={"target": "127.0.0.1", "count": 1},
            confirmed=False,
        )
        result = await tool_manager.execute(request)

        # Struktur output harus selalu valid, terlepas dari firewall.
        assert result.permission_level == PermissionLevel.READ
        assert result.risk_level == RiskLevel.LOW
        assert result.output["target"] == "127.0.0.1"
        assert isinstance(result.output["packet_loss"], float)
        assert result.duration_ms > 0

        if result.output["packet_loss"] >= 100.0:
            pytest.skip(
                "ICMP ke loopback diblokir di lingkungan ini (kemungkinan "
                "Windows Firewall) — bukan kegagalan tool NOVA. Aktifkan "
                "rule 'File and Printer Sharing (Echo Request - ICMPv4-In)' "
                "untuk menguji reachability sesungguhnya."
            )

        assert result.success is True

    @pytest.mark.asyncio
    async def test_ping_invalid_input_rejected_by_schema(self):
        """count di luar rentang (1-10) harus ditolak sebelum tool dieksekusi."""
        request = ToolRequest(
            tool_name="ping",
            arguments={"target": "127.0.0.1", "count": 999},
            confirmed=False,
        )
        with pytest.raises(ToolValidationError):
            await tool_manager.execute(request)

    @pytest.mark.asyncio
    async def test_ping_missing_required_field_rejected(self):
        """target wajib ada — request tanpa target harus gagal di schema validation."""
        request = ToolRequest(tool_name="ping", arguments={}, confirmed=False)
        with pytest.raises(ToolValidationError):
            await tool_manager.execute(request)
