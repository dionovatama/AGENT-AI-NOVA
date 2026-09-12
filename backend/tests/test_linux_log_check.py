"""
Test untuk linux.log_check.

Tiga kategori, konsisten dengan pola test Milestone 4 lain:
1. Parsing/behavior sukses (mocked SSH) — TestLogCheckBehavior
2. Kondisi "valid tapi kosong" (unit tidak ada / belum ada entry) — juga
   di TestLogCheckBehavior, karena ini bukan skenario gagal
3. Keamanan input (service_name pakai whitelist yang SAMA dengan
   service_status, jadi kita reuse payload dari test_linux_injection.py
   alih-alih menduplikasi daftarnya) — TestLogCheckInjectionDefense
"""

from unittest.mock import patch

import asyncssh
import pytest

from app.tools.linux import LogCheckInput, execute_log_check
from app.tools.manager import ToolValidationError, tool_manager
from app.tools.schemas import ToolRequest
from tests.test_linux_injection import INJECTION_PAYLOADS
from tests.test_linux_ssh import FakeConnection, FakeConnectionContextManager, FakeRunResult


def _mock_connect(responses: dict[str, FakeRunResult]):
    connection = FakeConnection(responses)
    return patch(
        "app.tools.linux.asyncssh.connect",
        return_value=FakeConnectionContextManager(connection=connection),
    )


class TestLogCheckBehavior:
    @pytest.mark.asyncio
    async def test_returns_log_lines_for_existing_unit(self):
        raw = (
            "2026-09-12T10:00:01+0700 vm-test sshd[123]: Accepted publickey for nova\n"
            "2026-09-12T10:05:12+0700 vm-test sshd[456]: Accepted publickey for nova\n"
        )
        cmd = "journalctl -u ssh -n 50 --no-pager --output=short-iso"
        with _mock_connect({cmd: FakeRunResult(stdout=raw, exit_status=0)}):
            result = await execute_log_check(LogCheckInput(service_name="ssh"))

        assert result.success is True
        assert result.unit_found is True
        assert len(result.log_lines) == 2
        assert "Accepted publickey" in result.log_lines[0]

    @pytest.mark.asyncio
    async def test_respects_custom_lines_argument(self):
        cmd = "journalctl -u ssh -n 5 --no-pager --output=short-iso"
        with _mock_connect({cmd: FakeRunResult(stdout="log line\n", exit_status=0)}):
            result = await execute_log_check(LogCheckInput(service_name="ssh", lines=5))

        assert result.lines_requested == 5

    @pytest.mark.asyncio
    async def test_lines_argument_rejected_above_cap(self):
        """lines > 200 harus ditolak Pydantic sebelum sempat jadi command —
        ini cap anti-DoS, bukan cuma preferensi."""
        with pytest.raises(Exception):
            LogCheckInput(service_name="ssh", lines=201)

    @pytest.mark.asyncio
    async def test_unit_with_no_log_entries_is_success_with_empty_list(self):
        """Service valid tapi belum pernah punya entry (baru diinstall,
        misal) BUKAN kegagalan — success tetap true, unit_found true,
        log_lines kosong."""
        cmd = "journalctl -u freshly-installed -n 50 --no-pager --output=short-iso"
        with _mock_connect(
            {cmd: FakeRunResult(stdout="-- No entries --\n", exit_status=0)}
        ):
            result = await execute_log_check(LogCheckInput(service_name="freshly-installed"))

        assert result.success is True
        assert result.unit_found is True
        assert result.log_lines == []

    @pytest.mark.asyncio
    async def test_nonexistent_unit_is_success_not_failure(self):
        """Unit yang benar-benar tidak dikenal systemd — kondisi valid
        (nama service salah ketik oleh user), bukan tool error."""
        cmd = "journalctl -u tidak-ada-service -n 50 --no-pager --output=short-iso"
        with _mock_connect(
            {
                cmd: FakeRunResult(
                    stdout="",
                    stderr="No such unit: tidak-ada-service.service\n",
                    exit_status=1,
                )
            }
        ):
            result = await execute_log_check(LogCheckInput(service_name="tidak-ada-service"))

        assert result.success is True
        assert result.unit_found is False

    @pytest.mark.asyncio
    async def test_real_journalctl_failure_is_reported_as_error(self):
        """Kegagalan journalctl yang BUKAN 'unit tidak ada' (mis. journal
        corrupt/permission) harus success=False, bukan disamakan dengan
        'unit tidak ada'."""
        cmd = "journalctl -u ssh -n 50 --no-pager --output=short-iso"
        with _mock_connect(
            {
                cmd: FakeRunResult(
                    stdout="", stderr="Failed to open journal: Permission denied\n", exit_status=1
                )
            }
        ):
            result = await execute_log_check(LogCheckInput(service_name="ssh"))

        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_connection_failure_returns_success_false_not_exception(self):
        with patch(
            "app.tools.linux.asyncssh.connect",
            return_value=FakeConnectionContextManager(
                connect_error=asyncssh.Error(1, "Connection refused")
            ),
        ):
            result = await execute_log_check(LogCheckInput(service_name="ssh"))

        assert result.success is False
        assert "SSH error" in result.error


class TestLogCheckInjectionDefense:
    """
    service_name di log_check pakai _SERVICE_NAME_PATTERN yang SAMA
    dengan service_status — jadi kita reuse payload yang sudah terbukti
    (INJECTION_PAYLOADS) alih-alih menulis ulang daftarnya dan berisiko
    daftar ini menyimpang / lupa disinkronkan di kemudian hari.
    """

    @pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
    @pytest.mark.asyncio
    async def test_malicious_service_name_rejected_before_ssh(self, payload):
        request = ToolRequest(
            tool_name="linux.log_check",
            arguments={"service_name": payload},
            confirmed=False,
        )
        with pytest.raises(ToolValidationError):
            await tool_manager.execute(request)
