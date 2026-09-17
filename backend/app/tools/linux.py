"""
Linux Executor — SSH-based diagnostic tools (PRD section 15).

Koneksi SSH memakai asyncssh (async native, konsisten dengan arsitektur
FastAPI NOVA yang non-blocking). Autentikasi HANYA lewat private key —
password login sudah dimatikan di sshd_config VM target sesuai
keputusan lab.

CATATAN SKELETON:
- known_hosts=None dipakai untuk sementara (TIDAK memverifikasi host
  key server). Ini cukup untuk lab dengan satu VM test yang berubah-
  ubah selama development, TAPI TIDAK BOLEH dibawa ke production tanpa
  host key pinning per-device. Ini akan masuk scope Device Management
  (Phase 5+), bukan skeleton ini.
- Satu koneksi SSH dipakai untuk semua command dalam satu tool call
  (bukan buka-tutup koneksi per command) agar tidak boros overhead
  handshake SSH.
"""

import asyncssh
from pydantic import BaseModel, Field

from app.config import settings
from app.tools.schemas import (
    LoggingPolicy,
    PermissionLevel,
    RiskLevel,
    ToolDefinition,
)


def _open_connection() -> asyncssh.connect:
    """Factory koneksi SSH — satu tempat kebenaran untuk parameter
    koneksi, dipakai oleh semua tool linux.* di file ini.

    Host Key Verification (AUDIT FIX-01 Phase 9):
    - Jika settings.linux_ssh_host_key_checking=False (default),
      known_hosts=None digunakan untuk kompatibilitas lab development.
    - Jika settings.linux_ssh_host_key_checking=True, strict host verification
      diaktifkan menggunakan settings.linux_ssh_known_hosts_path (atau default system).
    - Host key atau private key tidak pernah dibocorkan ke caller/LLM.
    """
    known_hosts = None
    if settings.linux_ssh_host_key_checking:
        known_hosts = settings.linux_ssh_known_hosts_path or ()

    return asyncssh.connect(
        host=settings.linux_ssh_host,
        port=settings.linux_ssh_port,
        username=settings.linux_ssh_username,
        client_keys=[settings.linux_ssh_private_key_path],
        known_hosts=known_hosts,
        connect_timeout=settings.linux_ssh_connect_timeout_seconds,
    )


# ============================================================
# linux.system_info
# ============================================================

class SystemInfoInput(BaseModel):
    """Tidak butuh argumen dari LLM — target ditentukan lewat config,
    akan berubah jadi device_id reference saat Device Management masuk."""


class SystemInfoOutput(BaseModel):
    success: bool
    hostname: str | None = None
    kernel: str | None = None
    uptime: str | None = None
    load_average: str | None = None
    memory_total_kb: int | None = None
    memory_available_kb: int | None = None
    error: str | None = None


def _parse_meminfo(raw: str) -> tuple[int | None, int | None]:
    total_kb = available_kb = None
    for line in raw.splitlines():
        if line.startswith("MemTotal:"):
            total_kb = int(line.split()[1])
        elif line.startswith("MemAvailable:"):
            available_kb = int(line.split()[1])
    return total_kb, available_kb


async def execute_system_info(input: SystemInfoInput) -> SystemInfoOutput:
    try:
        async with _open_connection() as conn:
            hostname = (await conn.run("hostname", check=False)).stdout.strip()
            kernel = (await conn.run("uname -r", check=False)).stdout.strip()
            uptime = (await conn.run("uptime -p", check=False)).stdout.strip()
            load_average = (
                await conn.run("cat /proc/loadavg", check=False)
            ).stdout.strip()
            meminfo_raw = (
                await conn.run("cat /proc/meminfo", check=False)
            ).stdout

        memory_total_kb, memory_available_kb = _parse_meminfo(meminfo_raw)

        return SystemInfoOutput(
            success=True,
            hostname=hostname,
            kernel=kernel,
            uptime=uptime,
            load_average=load_average,
            memory_total_kb=memory_total_kb,
            memory_available_kb=memory_available_kb,
        )
    except (asyncssh.Error, OSError) as exc:
        return SystemInfoOutput(success=False, error=f"SSH error: {exc}")


system_info_tool = ToolDefinition(
    name="linux.system_info",
    description=(
        "Mengambil informasi dasar sistem Linux target lewat SSH: "
        "hostname, kernel version, uptime, load average, dan memory."
    ),
    input_model=SystemInfoInput,
    output_model=SystemInfoOutput,
    permission_level=PermissionLevel.READ,
    risk_level=RiskLevel.LOW,
    supported_platforms=["linux"],
    timeout_seconds=20.0,
    logging_policy=LoggingPolicy.RESULT_ONLY,
    executor=execute_system_info,
)


# ============================================================
# linux.network_info
# ============================================================

import re

class NetworkInfoInput(BaseModel):
    """Tidak butuh argumen — membaca seluruh interface pada target."""


class NetworkInterfaceEntry(BaseModel):
    name: str
    ip: str | None = None
    state: str


class NetworkInfoOutput(BaseModel):
    success: bool
    interfaces: list[NetworkInterfaceEntry] = []
    default_route: str | None = None
    dns_servers: list[str] = []
    error: str | None = None


# Header interface: "2: enp0s3: <BROADCAST,...,UP,...> mtu 1500 ... state UP ..."
# Menangkap nama interface (grup 1) dan nilai setelah kata "state" (grup 2).
# Nama bisa mengandung "@ifN" (mis. veth pair) — tetap disimpan apa adanya
# karena itu informasi valid, bukan noise.
_IFACE_HEADER_RE = re.compile(r"^\d+:\s+(\S+):\s+<[^>]*>.*\bstate\s+(\S+)")
# Baris "inet 10.0.2.15/24 brd ... scope global ..." — ambil token setelah "inet".
_INET_RE = re.compile(r"^\s*inet\s+(\S+)")


def _parse_interfaces(raw: str) -> list[NetworkInterfaceEntry]:
    """
    Parse output `ip -4 addr show` menjadi list terstruktur per interface.

    Murni fungsi string -> data (tidak menyentuh SSH), sehingga bisa
    diuji langsung dengan data contoh tanpa perlu VM aktif.
    """
    interfaces: list[NetworkInterfaceEntry] = []
    current_name: str | None = None
    current_state: str | None = None
    current_ip: str | None = None

    def _flush() -> None:
        if current_name is not None:
            interfaces.append(NetworkInterfaceEntry(
                name=current_name, ip=current_ip, state=current_state or "UNKNOWN",
            ))

    for line in raw.splitlines():
        header_match = _IFACE_HEADER_RE.match(line)
        if header_match:
            _flush()
            current_name = header_match.group(1)
            current_state = header_match.group(2)
            current_ip = None
            continue

        if current_name is not None and current_ip is None:
            inet_match = _INET_RE.match(line)
            if inet_match:
                current_ip = inet_match.group(1)

    _flush()
    return interfaces


async def execute_network_info(input: NetworkInfoInput) -> NetworkInfoOutput:
    try:
        async with _open_connection() as conn:
            interfaces_raw = (
                await conn.run("ip -4 addr show", check=False)
            ).stdout.strip()
            default_route = (
                await conn.run("ip route show default", check=False)
            ).stdout.strip()
            resolv_conf = (
                await conn.run("cat /etc/resolv.conf", check=False)
            ).stdout

        dns_servers = [
            line.split()[1]
            for line in resolv_conf.splitlines()
            if line.startswith("nameserver")
        ]

        return NetworkInfoOutput(
            success=True,
            interfaces=_parse_interfaces(interfaces_raw),
            default_route=default_route or None,
            dns_servers=dns_servers,
        )
    except (asyncssh.Error, OSError) as exc:
        return NetworkInfoOutput(success=False, error=f"SSH error: {exc}")


network_info_tool = ToolDefinition(
    name="linux.network_info",
    description=(
        "Membaca konfigurasi network dasar target Linux: IP address "
        "per interface, default route, dan DNS server."
    ),
    input_model=NetworkInfoInput,
    output_model=NetworkInfoOutput,
    permission_level=PermissionLevel.READ,
    risk_level=RiskLevel.LOW,
    supported_platforms=["linux"],
    timeout_seconds=20.0,
    logging_policy=LoggingPolicy.RESULT_ONLY,
    executor=execute_network_info,
)


# ============================================================
# linux.disk_info
# ============================================================

class DiskInfoInput(BaseModel):
    """Tidak butuh argumen — membaca seluruh mounted filesystem."""


class DiskEntry(BaseModel):
    filesystem: str
    size: str
    used: str
    available: str
    use_percent: str
    mounted_on: str


class DiskInfoOutput(BaseModel):
    success: bool
    disks: list[DiskEntry] = []
    error: str | None = None


async def execute_disk_info(input: DiskInfoInput) -> DiskInfoOutput:
    try:
        async with _open_connection() as conn:
            raw = (await conn.run("df -h -x tmpfs -x devtmpfs", check=False)).stdout

        disks: list[DiskEntry] = []
        for line in raw.strip().splitlines()[1:]:
            parts = line.split(maxsplit=5)
            if len(parts) == 6:
                disks.append(DiskEntry(
                    filesystem=parts[0],
                    size=parts[1],
                    used=parts[2],
                    available=parts[3],
                    use_percent=parts[4],
                    mounted_on=parts[5],
                ))

        return DiskInfoOutput(success=True, disks=disks)
    except (asyncssh.Error, OSError) as exc:
        return DiskInfoOutput(success=False, error=f"SSH error: {exc}")


disk_info_tool = ToolDefinition(
    name="linux.disk_info",
    description="Membaca penggunaan disk (df -h) pada seluruh mounted filesystem target.",
    input_model=DiskInfoInput,
    output_model=DiskInfoOutput,
    permission_level=PermissionLevel.READ,
    risk_level=RiskLevel.LOW,
    supported_platforms=["linux"],
    timeout_seconds=15.0,
    logging_policy=LoggingPolicy.RESULT_ONLY,
    executor=execute_disk_info,
)


# ============================================================
# linux.memory_info
# ============================================================

class MemoryInfoInput(BaseModel):
    """Tidak butuh argumen."""


class MemoryInfoOutput(BaseModel):
    success: bool
    total_kb: int | None = None
    free_kb: int | None = None
    available_kb: int | None = None
    buffers_kb: int | None = None
    cached_kb: int | None = None
    swap_total_kb: int | None = None
    swap_free_kb: int | None = None
    used_percent: float | None = None
    error: str | None = None


async def execute_memory_info(input: MemoryInfoInput) -> MemoryInfoOutput:
    try:
        async with _open_connection() as conn:
            raw = (await conn.run("cat /proc/meminfo", check=False)).stdout

        values: dict[str, int] = {}
        for line in raw.splitlines():
            key, _, rest = line.partition(":")
            digits = "".join(ch for ch in rest if ch.isdigit())
            if digits:
                values[key.strip()] = int(digits)

        total = values.get("MemTotal")
        available = values.get("MemAvailable")
        used_percent = None
        if total and available is not None and total > 0:
            used_percent = round((total - available) / total * 100, 1)

        return MemoryInfoOutput(
            success=True,
            total_kb=total,
            free_kb=values.get("MemFree"),
            available_kb=available,
            buffers_kb=values.get("Buffers"),
            cached_kb=values.get("Cached"),
            swap_total_kb=values.get("SwapTotal"),
            swap_free_kb=values.get("SwapFree"),
            used_percent=used_percent,
        )
    except (asyncssh.Error, OSError) as exc:
        return MemoryInfoOutput(success=False, error=f"SSH error: {exc}")


memory_info_tool = ToolDefinition(
    name="linux.memory_info",
    description="Membaca detail penggunaan memory (/proc/meminfo) target Linux.",
    input_model=MemoryInfoInput,
    output_model=MemoryInfoOutput,
    permission_level=PermissionLevel.READ,
    risk_level=RiskLevel.LOW,
    supported_platforms=["linux"],
    timeout_seconds=15.0,
    logging_policy=LoggingPolicy.RESULT_ONLY,
    executor=execute_memory_info,
)


# ============================================================
# linux.service_status
# ============================================================

_SERVICE_NAME_PATTERN = r"^[a-zA-Z0-9_.@-]+$"


class ServiceStatusInput(BaseModel):
    service_name: str = Field(
        ...,
        pattern=_SERVICE_NAME_PATTERN,
        max_length=128,
        description="Nama systemd unit, mis. 'sshd' atau 'docker'.",
    )


class ServiceStatusOutput(BaseModel):
    success: bool
    service_name: str
    active: bool | None = None
    active_state: str | None = None
    enabled: bool | None = None
    error: str | None = None


async def execute_service_status(input: ServiceStatusInput) -> ServiceStatusOutput:
    try:
        async with _open_connection() as conn:
            active_result = await conn.run(
                f"systemctl is-active {input.service_name}", check=False
            )
            enabled_result = await conn.run(
                f"systemctl is-enabled {input.service_name}", check=False
            )

        active_state = active_result.stdout.strip()
        enabled_state = enabled_result.stdout.strip()

        return ServiceStatusOutput(
            success=True,
            service_name=input.service_name,
            active=(active_state == "active"),
            active_state=active_state,
            enabled=(enabled_state == "enabled"),
        )
    except (asyncssh.Error, OSError) as exc:
        return ServiceStatusOutput(
            success=False, service_name=input.service_name, error=f"SSH error: {exc}"
        )


service_status_tool = ToolDefinition(
    name="linux.service_status",
    description="Memeriksa status sebuah systemd service (active/inactive, enabled/disabled).",
    input_model=ServiceStatusInput,
    output_model=ServiceStatusOutput,
    permission_level=PermissionLevel.READ,
    risk_level=RiskLevel.LOW,
    supported_platforms=["linux"],
    timeout_seconds=15.0,
    logging_policy=LoggingPolicy.RESULT_ONLY,
    executor=execute_service_status,
)

# ============================================================
# linux.log_check
# ============================================================
#
# Sengaja DIBATASI ke systemd journal per-service (journalctl -u),
# BUKAN pembacaan file log bebas (mis. `cat /var/log/whatever`).
# Alasan (PRD section 30 — Least Privilege, section 40 — Non-Goals MVP
# "unrestricted shell"):
#   - Kalau tool ini menerima path file bebas, dia jadi arbitrary file
#     read primitive (bisa dipakai baca /etc/shadow, private key, dst),
#     bukan sekadar "log check".
#   - journalctl -u membatasi bacaan HANYA ke unit systemd yang memang
#     ada, dan service_name divalidasi whitelist yang SAMA dengan
#     linux.service_status (sudah teruji aman dari command injection —
#     lihat test_linux_injection.py).
#   - `lines` di-cap keras (maks 200) supaya tidak jadi vector DoS lewat
#     dump log raksasa ke response API / LLM context.

class LogCheckInput(BaseModel):
    service_name: str = Field(
        ...,
        pattern=_SERVICE_NAME_PATTERN,
        max_length=128,
        description="Nama systemd unit yang log-nya ingin dibaca, mis. 'ssh' atau 'docker'.",
    )
    lines: int = Field(
        default=50,
        ge=1,
        le=200,
        description="Jumlah baris log terakhir yang diambil (maks 200 — cap keras anti-DoS).",
    )


class LogCheckOutput(BaseModel):
    success: bool
    service_name: str
    lines_requested: int
    log_lines: list[str] = []
    unit_found: bool | None = None
    error: str | None = None


# journalctl mencetak baris ini ke stdout (bukan stderr) kalau unit
# tidak dikenal SAMA SEKALI oleh systemd — beda dengan unit yang
# dikenal tapi belum pernah punya log entry apa pun.
_NO_ENTRIES_MARKER = "-- No entries --"


async def execute_log_check(input: LogCheckInput) -> LogCheckOutput:
    try:
        async with _open_connection() as conn:
            result = await conn.run(
                f"journalctl -u {input.service_name} -n {input.lines} --no-pager --output=short-iso",
                check=False,
            )

        if result.exit_status != 0:
            stderr_lower = (result.stderr or "").lower()
            unit_not_found = "no such" in stderr_lower or (
                "unit" in stderr_lower and "not" in stderr_lower
            )
            if unit_not_found:
                # Unit memang tidak ada — kondisi valid, bukan kegagalan tool.
                return LogCheckOutput(
                    success=True,
                    service_name=input.service_name,
                    lines_requested=input.lines,
                    log_lines=[],
                    unit_found=False,
                )
            return LogCheckOutput(
                success=False,
                service_name=input.service_name,
                lines_requested=input.lines,
                error=f"journalctl gagal: {result.stderr.strip()}",
            )

        raw_lines = result.stdout.strip().splitlines()
        # Unit valid tapi belum pernah ada log entry.
        if raw_lines == [_NO_ENTRIES_MARKER]:
            return LogCheckOutput(
                success=True,
                service_name=input.service_name,
                lines_requested=input.lines,
                log_lines=[],
                unit_found=True,
            )

        return LogCheckOutput(
            success=True,
            service_name=input.service_name,
            lines_requested=input.lines,
            log_lines=raw_lines,
            unit_found=True,
        )
    except (asyncssh.Error, OSError) as exc:
        return LogCheckOutput(
            success=False,
            service_name=input.service_name,
            lines_requested=input.lines,
            error=f"SSH error: {exc}",
        )


log_check_tool = ToolDefinition(
    name="linux.log_check",
    description=(
        "Membaca N baris terakhir dari systemd journal untuk sebuah "
        "service tertentu (bukan file log bebas — dibatasi ke journalctl -u)."
    ),
    input_model=LogCheckInput,
    output_model=LogCheckOutput,
    permission_level=PermissionLevel.READ,
    risk_level=RiskLevel.LOW,
    supported_platforms=["linux"],
    timeout_seconds=15.0,
    logging_policy=LoggingPolicy.RESULT_ONLY,
    executor=execute_log_check,
)


# ============================================================
# linux.process_status
# ============================================================

class ProcessStatusInput(BaseModel):
    name_filter: str | None = Field(
        default=None,
        max_length=128,
        description="Filter substring nama proses (opsional, case-insensitive).",
    )
    limit: int = Field(default=10, ge=1, le=50)


class ProcessEntry(BaseModel):
    user: str
    pid: str
    cpu_percent: str
    mem_percent: str
    command: str


class ProcessStatusOutput(BaseModel):
    success: bool
    processes: list[ProcessEntry] = []
    error: str | None = None


def _is_self_measurement(command: str) -> bool:
    """
    True jika command adalah pemanggilan 'ps aux' itu sendiri.

    %CPU dari `ps` dihitung sebagai rata-rata sejak proses itu start —
    proses yang baru saja dijalankan (perintah pengukurnya sendiri) bisa
    muncul dengan angka tinggi yang menyesatkan, padahal bukan representasi
    beban sistem nyata. Tanpa filter ini, LLM yang membaca hasil tool ini
    untuk diagnosis "kenapa server lambat" bisa salah menyimpulkan bahwa
    'ps aux' adalah penyebab beban tinggi.
    """
    return "ps aux" in command.lower()


async def execute_process_status(input: ProcessStatusInput) -> ProcessStatusOutput:
    try:
        async with _open_connection() as conn:
            raw = (
                await conn.run("ps aux --sort=-%cpu", check=False)
            ).stdout

        entries: list[ProcessEntry] = []
        for line in raw.strip().splitlines()[1:]:
            parts = line.split(maxsplit=10)
            if len(parts) < 11:
                continue
            user, pid, cpu, mem = parts[0], parts[1], parts[2], parts[3]
            command = parts[10]

            if _is_self_measurement(command):
                continue

            if input.name_filter and input.name_filter.lower() not in command.lower():
                continue

            entries.append(ProcessEntry(
                user=user, pid=pid, cpu_percent=cpu, mem_percent=mem, command=command,
            ))
            if len(entries) >= input.limit:
                break

        return ProcessStatusOutput(success=True, processes=entries)
    except (asyncssh.Error, OSError) as exc:
        return ProcessStatusOutput(success=False, error=f"SSH error: {exc}")


process_status_tool = ToolDefinition(
    name="linux.process_status",
    description=(
        "Menampilkan proses dengan CPU usage tertinggi, dengan filter "
        "nama opsional (dilakukan di sisi backend, bukan shell remote)."
    ),
    input_model=ProcessStatusInput,
    output_model=ProcessStatusOutput,
    permission_level=PermissionLevel.READ,
    risk_level=RiskLevel.LOW,
    supported_platforms=["linux"],
    timeout_seconds=15.0,
    logging_policy=LoggingPolicy.RESULT_ONLY,
    executor=execute_process_status,
)


# ============================================================
# linux.docker_status
# ============================================================

class DockerStatusInput(BaseModel):
    """Tidak butuh argumen — membaca seluruh container aktif."""


class ContainerEntry(BaseModel):
    container_id: str
    image: str
    status: str
    names: str


class DockerStatusOutput(BaseModel):
    success: bool
    docker_installed: bool = True
    containers: list[ContainerEntry] = []
    error: str | None = None


async def execute_docker_status(input: DockerStatusInput) -> DockerStatusOutput:
    try:
        async with _open_connection() as conn:
            result = await conn.run(
                'docker ps --format "{{.ID}}|{{.Image}}|{{.Status}}|{{.Names}}"',
                check=False,
            )

        if result.exit_status != 0:
            stderr_lower = (result.stderr or "").lower()
            if "not found" in stderr_lower or "command not found" in stderr_lower:
                return DockerStatusOutput(success=True, docker_installed=False)
            return DockerStatusOutput(
                success=False, error=f"docker ps gagal: {result.stderr.strip()}"
            )

        containers: list[ContainerEntry] = []
        for line in result.stdout.strip().splitlines():
            fields = line.split("|")
            if len(fields) == 4:
                containers.append(ContainerEntry(
                    container_id=fields[0], image=fields[1],
                    status=fields[2], names=fields[3],
                ))

        return DockerStatusOutput(success=True, docker_installed=True, containers=containers)
    except (asyncssh.Error, OSError) as exc:
        return DockerStatusOutput(success=False, error=f"SSH error: {exc}")


docker_status_tool = ToolDefinition(
    name="linux.docker_status",
    description="Membaca status container Docker yang sedang berjalan di target (jika Docker terpasang).",
    input_model=DockerStatusInput,
    output_model=DockerStatusOutput,
    permission_level=PermissionLevel.READ,
    risk_level=RiskLevel.LOW,
    supported_platforms=["linux"],
    timeout_seconds=15.0,
    logging_policy=LoggingPolicy.RESULT_ONLY,
    executor=execute_docker_status,
)