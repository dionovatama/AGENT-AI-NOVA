"""
Network Diagnostic Tool — ping.

Tool pertama yang didaftarkan ke Tool Manager, dipakai sebagai bukti
bahwa flow lengkap (Schema Validation -> Authorization -> Risk
Assessment -> Permission -> Executor -> Result) benar-benar berfungsi
end-to-end.

Permission level : READ  (hanya membaca, tidak mengubah apa pun)
Risk level        : LOW

Referensi PRD:
- Section 13 (Tool Schema) — contoh input/output di PRD persis
  memakai tool ping ini.
- Section 25 (Network Diagnostics) — ping adalah tool pertama di
  daftar initial tools.
"""

import asyncio
import platform
import re

from pydantic import BaseModel, Field

from app.tools.schemas import (
    LoggingPolicy,
    PermissionLevel,
    RiskLevel,
    ToolDefinition,
)


class PingInput(BaseModel):
    target: str = Field(..., description="Hostname atau IP address tujuan")
    count: int = Field(default=4, ge=1, le=10, description="Jumlah paket ping")


class PingOutput(BaseModel):
    success: bool
    target: str
    latency_ms: float | None
    packet_loss: float


async def execute_ping(input: PingInput) -> PingOutput:
    """
    Menjalankan ping ke target dan mem-parsing hasilnya.

    Cross-platform: sintaks argumen ping Windows ("-n") dan Linux
    ("-c") berbeda, begitu juga format output yang di-parsing.
    """
    system = platform.system().lower()
    if system == "windows":
        cmd = ["ping", "-n", str(input.count), input.target]
    else:
        cmd = ["ping", "-c", str(input.count), input.target]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await process.communicate()
    output_text = stdout.decode(errors="ignore")

    # Packet loss: cari pola umum "X% loss" (Windows) / "X% packet loss" (Linux).
    loss_match = re.search(r"(\d+(?:\.\d+)?)\s*% (?:packet )?loss", output_text)
    packet_loss = float(loss_match.group(1)) if loss_match else 100.0

    # Rata-rata latency: "Average = Xms" (Windows) atau
    # "min/avg/max/mdev = a/b/c/d ms" (Linux).
    latency_ms: float | None = None
    win_match = re.search(r"Average = (\d+)ms", output_text)
    linux_match = re.search(r"=\s*[\d.]+/([\d.]+)/[\d.]+", output_text)
    if win_match:
        latency_ms = float(win_match.group(1))
    elif linux_match:
        latency_ms = float(linux_match.group(1))

    success = process.returncode == 0 and packet_loss < 100.0

    return PingOutput(
        success=success,
        target=input.target,
        latency_ms=latency_ms,
        packet_loss=packet_loss,
    )


ping_tool = ToolDefinition(
    name="ping",
    description=(
        "Melakukan ICMP ping ke target host/IP untuk memeriksa "
        "konektivitas dasar."
    ),
    input_model=PingInput,
    output_model=PingOutput,
    permission_level=PermissionLevel.READ,
    risk_level=RiskLevel.LOW,
    supported_platforms=["network", "linux", "windows"],
    timeout_seconds=15.0,
    logging_policy=LoggingPolicy.RESULT_ONLY,
    executor=execute_ping,
)