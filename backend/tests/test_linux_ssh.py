"""
Test integrasi (mocked SSH) untuk tool linux.* Milestone 4.

Melengkapi test_linux_parsers.py (fungsi parser murni) dan
test_linux_injection.py (keamanan service_status) dengan:

1. Verifikasi end-to-end tiap executor: koneksi SSH -> command -> parsing
   -> output terstruktur, untuk tool yang BELUM ditest otomatis
   (system_info, disk_info, memory_info, docker_status).
2. Verifikasi prinsip PRD "tidak boleh mengklaim sukses tanpa
   verifikasi" / "kegagalan SSH tidak boleh bocor jadi exception
   mentah" — untuk SEMUA tool linux.*, bukan cuma sebagian.

Tidak memerlukan VM lab aktif: asyncssh.connect() di-mock sepenuhnya,
sehingga test cepat, deterministik, dan tidak tergantung jaringan
(pola sama seperti test_ai.py untuk OpenRouter fallback).
"""

from unittest.mock import patch

import asyncssh
import pytest

from app.tools.linux import (
    DiskInfoInput,
    DockerStatusInput,
    MemoryInfoInput,
    NetworkInfoInput,
    ProcessStatusInput,
    ServiceStatusInput,
    SystemInfoInput,
    execute_disk_info,
    execute_docker_status,
    execute_memory_info,
    execute_network_info,
    execute_process_status,
    execute_service_status,
    execute_system_info,
)


class FakeRunResult:
    """Tiruan hasil asyncssh SSHCompletedProcess yang relevan untuk kode kita."""

    def __init__(self, stdout: str = "", stderr: str = "", exit_status: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.exit_status = exit_status


class FakeConnection:
    """
    Tiruan SSHClientConnection.

    `responses` memetakan command persis -> FakeRunResult, supaya urutan
    pemanggilan conn.run() di dalam satu executor tidak perlu dihafal —
    cukup cocokkan berdasarkan isi command-nya, sama seperti server SSH
    sungguhan yang tidak peduli urutan tanya-jawab per command.
    """

    def __init__(self, responses: dict[str, FakeRunResult]):
        self._responses = responses

    async def run(self, command: str, check: bool = False) -> FakeRunResult:
        if command not in self._responses:
            raise AssertionError(
                f"Command tak terduga dipanggil dalam test: {command!r}. "
                f"Command yang di-mock: {list(self._responses.keys())}"
            )
        return self._responses[command]


class FakeConnectionContextManager:
    """Tiruan objek yang dikembalikan asyncssh.connect() — dipakai lewat
    `async with _open_connection() as conn`, jadi harus mendukung
    async context manager protocol, bukan cuma awaitable biasa."""

    def __init__(self, connection: FakeConnection | None = None, connect_error: Exception | None = None):
        self._connection = connection
        self._connect_error = connect_error

    async def __aenter__(self) -> FakeConnection:
        if self._connect_error is not None:
            raise self._connect_error
        return self._connection

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


def _mock_connect_success(responses: dict[str, FakeRunResult]):
    """Patch target: app.tools.linux.asyncssh.connect -> sukses dengan
    command/response yang ditentukan test."""
    connection = FakeConnection(responses)
    return patch(
        "app.tools.linux.asyncssh.connect",
        return_value=FakeConnectionContextManager(connection=connection),
    )


def _mock_connect_failure(exc: Exception):
    """Patch target: asyncssh.connect -> gagal connect (exc dilempar saat
    __aenter__, meniru kegagalan TCP/handshake/auth sungguhan)."""
    return patch(
        "app.tools.linux.asyncssh.connect",
        return_value=FakeConnectionContextManager(connect_error=exc),
    )


# ============================================================
# linux.system_info
# ============================================================

class TestSystemInfo:
    @pytest.mark.asyncio
    async def test_success_parses_all_fields(self):
        responses = {
            "hostname": FakeRunResult(stdout="vm-test\n"),
            "uname -r": FakeRunResult(stdout="6.1.0-9-amd64\n"),
            "uptime -p": FakeRunResult(stdout="up 48 minutes\n"),
            "cat /proc/loadavg": FakeRunResult(stdout="0.00 0.00 0.00 1/88 984\n"),
            "cat /proc/meminfo": FakeRunResult(
                stdout="MemTotal:        984164 kB\nMemAvailable:    721264 kB\n"
            ),
        }
        with _mock_connect_success(responses):
            result = await execute_system_info(SystemInfoInput())

        assert result.success is True
        assert result.hostname == "vm-test"
        assert result.kernel == "6.1.0-9-amd64"
        assert result.uptime == "up 48 minutes"
        assert result.memory_total_kb == 984164
        assert result.memory_available_kb == 721264

    @pytest.mark.asyncio
    async def test_connection_failure_returns_success_false_not_exception(self):
        with _mock_connect_failure(asyncssh.Error(1, "Connection refused")):
            result = await execute_system_info(SystemInfoInput())

        assert result.success is False
        assert result.error is not None
        assert "SSH error" in result.error


# ============================================================
# linux.disk_info
# ============================================================

class TestDiskInfo:
    @pytest.mark.asyncio
    async def test_success_parses_disk_entries(self):
        raw = (
            "Filesystem      Size  Used Avail Use% Mounted on\n"
            "/dev/sda1       8.9G  951M  7.5G  12% /\n"
        )
        responses = {"df -h -x tmpfs -x devtmpfs": FakeRunResult(stdout=raw)}
        with _mock_connect_success(responses):
            result = await execute_disk_info(DiskInfoInput())

        assert result.success is True
        assert len(result.disks) == 1
        disk = result.disks[0]
        assert disk.filesystem == "/dev/sda1"
        assert disk.size == "8.9G"
        assert disk.use_percent == "12%"
        assert disk.mounted_on == "/"

    @pytest.mark.asyncio
    async def test_multiple_filesystems_all_parsed(self):
        raw = (
            "Filesystem      Size  Used Avail Use% Mounted on\n"
            "/dev/sda1       8.9G  951M  7.5G  12% /\n"
            "/dev/sda2       50G   10G   38G   21% /home\n"
        )
        responses = {"df -h -x tmpfs -x devtmpfs": FakeRunResult(stdout=raw)}
        with _mock_connect_success(responses):
            result = await execute_disk_info(DiskInfoInput())

        assert len(result.disks) == 2
        assert result.disks[1].mounted_on == "/home"

    @pytest.mark.asyncio
    async def test_connection_failure_returns_success_false_not_exception(self):
        with _mock_connect_failure(OSError("Network unreachable")):
            result = await execute_disk_info(DiskInfoInput())

        assert result.success is False
        assert "SSH error" in result.error


# ============================================================
# linux.memory_info
# ============================================================

class TestMemoryInfo:
    @pytest.mark.asyncio
    async def test_success_parses_and_computes_used_percent(self):
        raw = (
            "MemTotal:        984164 kB\n"
            "MemFree:         733352 kB\n"
            "MemAvailable:    721428 kB\n"
            "Buffers:          12004 kB\n"
            "Cached:           88312 kB\n"
            "SwapTotal:       998396 kB\n"
            "SwapFree:        998396 kB\n"
        )
        responses = {"cat /proc/meminfo": FakeRunResult(stdout=raw)}
        with _mock_connect_success(responses):
            result = await execute_memory_info(MemoryInfoInput())

        assert result.success is True
        assert result.total_kb == 984164
        assert result.available_kb == 721428
        assert result.swap_total_kb == 998396
        # (984164 - 721428) / 984164 * 100, dibulatkan 1 desimal
        assert result.used_percent == round((984164 - 721428) / 984164 * 100, 1)

    @pytest.mark.asyncio
    async def test_missing_fields_do_not_crash(self):
        """Kalau MemAvailable tidak ada (kernel lama), used_percent harus
        None, bukan ZeroDivisionError atau exception lain."""
        raw = "MemTotal:        984164 kB\n"
        responses = {"cat /proc/meminfo": FakeRunResult(stdout=raw)}
        with _mock_connect_success(responses):
            result = await execute_memory_info(MemoryInfoInput())

        assert result.success is True
        assert result.total_kb == 984164
        assert result.available_kb is None
        assert result.used_percent is None

    @pytest.mark.asyncio
    async def test_connection_failure_returns_success_false_not_exception(self):
        with _mock_connect_failure(asyncssh.Error(1, "Auth failed")):
            result = await execute_memory_info(MemoryInfoInput())

        assert result.success is False
        assert "SSH error" in result.error


# ============================================================
# linux.docker_status
# ============================================================

class TestDockerStatus:
    @pytest.mark.asyncio
    async def test_docker_installed_with_running_containers(self):
        raw = (
            "abc123|nginx:latest|Up 2 hours|web-server\n"
            "def456|postgres:15|Up 2 hours|db\n"
        )
        cmd = 'docker ps --format "{{.ID}}|{{.Image}}|{{.Status}}|{{.Names}}"'
        responses = {cmd: FakeRunResult(stdout=raw, exit_status=0)}
        with _mock_connect_success(responses):
            result = await execute_docker_status(DockerStatusInput())

        assert result.success is True
        assert result.docker_installed is True
        assert len(result.containers) == 2
        assert result.containers[0].names == "web-server"

    @pytest.mark.asyncio
    async def test_docker_not_installed_reports_success_true(self):
        """Docker tidak ada di VM = kondisi valid, BUKAN kegagalan tool.
        success harus tetap true, docker_installed=False."""
        cmd = 'docker ps --format "{{.ID}}|{{.Image}}|{{.Status}}|{{.Names}}"'
        responses = {
            cmd: FakeRunResult(
                stdout="", stderr="bash: docker: command not found\n", exit_status=127
            )
        }
        with _mock_connect_success(responses):
            result = await execute_docker_status(DockerStatusInput())

        assert result.success is True
        assert result.docker_installed is False
        assert result.containers == []

    @pytest.mark.asyncio
    async def test_docker_installed_but_daemon_error_is_real_failure(self):
        """Docker terinstall tapi 'docker ps' gagal karena alasan lain
        (mis. daemon tidak jalan) HARUS dibedakan dari 'tidak terinstall'
        — ini kegagalan nyata, success harus false."""
        cmd = 'docker ps --format "{{.ID}}|{{.Image}}|{{.Status}}|{{.Names}}"'
        responses = {
            cmd: FakeRunResult(
                stdout="",
                stderr="Cannot connect to the Docker daemon at unix:///var/run/docker.sock\n",
                exit_status=1,
            )
        }
        with _mock_connect_success(responses):
            result = await execute_docker_status(DockerStatusInput())

        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_connection_failure_returns_success_false_not_exception(self):
        with _mock_connect_failure(asyncssh.Error(1, "Connection reset")):
            result = await execute_docker_status(DockerStatusInput())

        assert result.success is False
        assert "SSH error" in result.error


# ============================================================
# SSH connection failure — regresi untuk SEMUA tool linux.*
# ============================================================

class TestSSHFailureNeverLeaksRawException:
    """
    Prinsip PRD: 'kegagalan SSH ditangkap dan dikembalikan sebagai
    output eksplisit (success=False, error=...), BUKAN exception mentah
    yang bocor ke API layer'. Test ini membuktikan itu berlaku untuk
    KESELURUHAN tool linux.*, bukan cuma yang kebetulan sempat ditest
    manual satu-satu.
    """

    @pytest.mark.parametrize(
        "executor,input_instance",
        [
            (execute_system_info, SystemInfoInput()),
            (execute_disk_info, DiskInfoInput()),
            (execute_memory_info, MemoryInfoInput()),
            (execute_network_info, NetworkInfoInput()),
            (execute_process_status, ProcessStatusInput()),
            (execute_docker_status, DockerStatusInput()),
            (execute_service_status, ServiceStatusInput(service_name="ssh")),
        ],
    )
    @pytest.mark.asyncio
    async def test_asyncssh_error_handled_gracefully(self, executor, input_instance):
        with _mock_connect_failure(asyncssh.Error(1, "Connection refused")):
            result = await executor(input_instance)

        assert result.success is False
        assert result.error is not None
        assert "SSH error" in result.error

    @pytest.mark.parametrize(
        "executor,input_instance",
        [
            (execute_system_info, SystemInfoInput()),
            (execute_disk_info, DiskInfoInput()),
            (execute_memory_info, MemoryInfoInput()),
            (execute_network_info, NetworkInfoInput()),
            (execute_process_status, ProcessStatusInput()),
            (execute_docker_status, DockerStatusInput()),
            (execute_service_status, ServiceStatusInput(service_name="ssh")),
        ],
    )
    @pytest.mark.asyncio
    async def test_os_error_handled_gracefully(self, executor, input_instance):
        """OSError (mis. host unreachable/timeout di level TCP) harus
        ditangani sama seperti asyncssh.Error — keduanya di-catch
        bersamaan di setiap executor."""
        with _mock_connect_failure(OSError("Network is unreachable")):
            result = await executor(input_instance)

        assert result.success is False
        assert result.error is not None
        assert "SSH error" in result.error