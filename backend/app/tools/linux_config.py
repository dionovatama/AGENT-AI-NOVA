"""Internal-only writer for typed Linux network configuration operations."""
from __future__ import annotations
import logging
from typing import Any
from pydantic import BaseModel, Field
from app.config import settings
from app.network.adapters.base import NetworkDeviceAdapter
from app.network.adapters.fake import FakeNetworkAdapter
from app.network.adapters.linux import LinuxNetworkAdapter
from app.network.models import AddIpAddressOperation, OperationType
from app.tools.context import ExecutionContext
from app.tools.schemas import LoggingPolicy, PermissionLevel, RiskLevel, ToolDefinition

logger = logging.getLogger("nova.tools.linux_config")

class LinuxConfigApplyInput(BaseModel):
    operation: dict[str, Any]
    plan_hash: str
    state_fingerprint: str
    action: str = Field(default="apply", pattern=r"^(apply|remove)$")
    object_id: str | None = None

class LinuxConfigApplyOutput(BaseModel):
    success: bool
    object_id: str | None = None
    error: str | None = None

def _get_adapter(ctx: ExecutionContext | None) -> NetworkDeviceAdapter:
    from app.api.configurations import _CUSTOM_ADAPTER
    if _CUSTOM_ADAPTER is not None: return _CUSTOM_ADAPTER
    if ctx and ctx.device and (ctx.device.device_metadata or {}).get("mock") is True: return FakeNetworkAdapter()
    return LinuxNetworkAdapter()

async def execute_linux_config_apply(input: LinuxConfigApplyInput, ctx: ExecutionContext | None = None) -> LinuxConfigApplyOutput:
    if not settings.config_apply_enabled:
        return LinuxConfigApplyOutput(success=False, error="Konfigurasi ditolak: kill-switch CONFIG_APPLY_ENABLED sedang mati.")
    if ctx is None or ctx.device is None or ctx.device.platform != "linux":
        return LinuxConfigApplyOutput(success=False, error="Device context Linux tidak tersedia.")
    try:
        op = AddIpAddressOperation.model_validate(input.operation)
    except Exception:
        return LinuxConfigApplyOutput(success=False, error="Operasi Linux tidak valid atau belum didukung.")
    adapter = _get_adapter(ctx)
    try:
        if input.action == "apply":
            object_id = await adapter.apply_operation(op, ctx.device, ctx)
            return LinuxConfigApplyOutput(success=True, object_id=object_id)
        if not input.object_id:
            return LinuxConfigApplyOutput(success=False, error="object_id wajib untuk rollback.")
        removed = await adapter.remove_operation(op, input.object_id, ctx.device, ctx)
        return LinuxConfigApplyOutput(success=removed, object_id=input.object_id if removed else None, error=None if removed else "Rollback operasi Linux gagal.")
    except Exception as exc:
        logger.error("Linux configuration operation failed: %s", type(exc).__name__)
        return LinuxConfigApplyOutput(success=False, error="Operasi konfigurasi Linux gagal. Periksa log backend yang telah disanitasi.")

linux_config_apply_tool = ToolDefinition(
    name="linux.config_apply",
    description="Tool internal untuk apply/rollback operasi jaringan Linux bertipe dan tervalidasi.",
    input_model=LinuxConfigApplyInput,
    output_model=LinuxConfigApplyOutput,
    permission_level=PermissionLevel.MODIFY,
    risk_level=RiskLevel.MEDIUM,
    supported_platforms=["linux"],
    requires_device=True,
    internal_only=True,
    timeout_seconds=30.0,
    logging_policy=LoggingPolicy.ALWAYS,
    executor=execute_linux_config_apply,
)
