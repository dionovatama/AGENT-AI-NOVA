"""
MikroTik Configuration Writer Tool (Internal Only).

Tool eksekusi perubahan konfigurasi ke perangkat MikroTik (PRD section 17, 19, 39).
ATURAN KERAS:
- Tool ini ber-flag `internal_only=True`:
  * Disembunyikan dari GET /tools/list
  * Ditolak di POST /tools/execute dengan pesan & status 404 identik dengan tool tidak dikenal
  * Tidak pernah masuk ke daftar skema LLM di tool_calling.py
- Hanya boleh dipanggil oleh Orchestrator konfigurasi via ToolManager.execute(..., is_internal=True).
- Memeriksa kill-switch CONFIG_APPLY_ENABLED pada saat runtime eksekusi (Defense in Depth).
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from app.config import settings
from app.network.adapters.base import NetworkDeviceAdapter
from app.network.adapters.fake import FakeNetworkAdapter
from app.network.adapters.mikrotik import MikrotikNetworkAdapter
from app.network.models import (
    AddIpAddressOperation,
    AddStaticRouteOperation,
    AddVlanInterfaceOperation,
    OperationType,
)
from app.tools.context import ExecutionContext
from app.tools.schemas import (
    LoggingPolicy,
    PermissionLevel,
    RiskLevel,
    ToolDefinition,
)

logger = logging.getLogger("nova.tools.mikrotik_config")


class MikrotikConfigApplyInput(BaseModel):
    """
    Input terstruktur untuk tool penulis konfigurasi MikroTik.
    """
    operation: dict[str, Any]
    plan_hash: str
    state_fingerprint: str
    action: str = Field(default="apply", pattern=r"^(apply|remove)$")
    object_id: str | None = None


class MikrotikConfigApplyOutput(BaseModel):
    success: bool
    object_id: str | None = None
    error: str | None = None


def _get_adapter(ctx: ExecutionContext | None) -> NetworkDeviceAdapter:
    """Mengembalikan adapter yang sesuai (Fake jika mock mode, atau MikrotikNetworkAdapter)."""
    from app.api.configurations import _CUSTOM_ADAPTER
    if _CUSTOM_ADAPTER is not None:
        return _CUSTOM_ADAPTER
    if ctx and ctx.device and (ctx.device.device_metadata or {}).get("mock") is True:
        return FakeNetworkAdapter()
    return MikrotikNetworkAdapter()


async def execute_mikrotik_config_apply(
    input: MikrotikConfigApplyInput, ctx: ExecutionContext | None = None
) -> MikrotikConfigApplyOutput:
    """
    Executor untuk menerapkan atau membatalkan operasi pada perangkat MikroTik.
    """
    # 1. Defense in Depth: Kill-switch check
    if not settings.config_apply_enabled:
        return MikrotikConfigApplyOutput(
            success=False,
            error="Konfigurasi ditolak: Kill-switch CONFIG_APPLY_ENABLED sedang mati.",
        )

    if ctx is None or ctx.device is None:
        return MikrotikConfigApplyOutput(
            success=False, error="Device context tidak tersedia untuk tool ini."
        )

    # 2. Parse operasi terstruktur
    op_data = input.operation
    op_type = op_data.get("type")

    try:
        if op_type == OperationType.ADD_IP_ADDRESS.value:
            op = AddIpAddressOperation.model_validate(op_data)
        elif op_type == OperationType.ADD_VLAN_INTERFACE.value:
            op = AddVlanInterfaceOperation.model_validate(op_data)
        elif op_type == OperationType.ADD_STATIC_ROUTE.value:
            op = AddStaticRouteOperation.model_validate(op_data)
        else:
            return MikrotikConfigApplyOutput(
                success=False, error=f"Tipe operasi tidak dikenal: {op_type}"
            )
    except Exception as exc:
        return MikrotikConfigApplyOutput(
            success=False, error=f"Validasi operasi gagal: {exc}"
        )

    adapter = _get_adapter(ctx)

    # 3. Eksekusi tindakan apply atau remove
    try:
        if input.action == "apply":
            obj_id = await adapter.apply_operation(op, ctx.device, ctx)
            return MikrotikConfigApplyOutput(success=True, object_id=obj_id)

        elif input.action == "remove":
            if not input.object_id:
                return MikrotikConfigApplyOutput(
                    success=False, error="object_id wajib disertakan untuk tindakan remove."
                )
            removed = await adapter.remove_operation(op, input.object_id, ctx.device, ctx)
            if not removed:
                return MikrotikConfigApplyOutput(
                    success=False, error=f"Gagal menghapus objek {input.object_id} dari perangkat."
                )
            return MikrotikConfigApplyOutput(success=True, object_id=input.object_id)

    except Exception as exc:
        logger.error("Gagal mengeksekusi operasi konfigurasi MikroTik: %s", exc)
        return MikrotikConfigApplyOutput(success=False, error=str(exc))

    return MikrotikConfigApplyOutput(success=False, error="Aksi tidak dikenal.")


mikrotik_config_apply_tool = ToolDefinition(
    name="mikrotik.config_apply",
    description="Tool internal untuk menerapkan atau membatalkan operasi konfigurasi MikroTik.",
    input_model=MikrotikConfigApplyInput,
    output_model=MikrotikConfigApplyOutput,
    permission_level=PermissionLevel.MODIFY,
    risk_level=RiskLevel.MEDIUM,
    supported_platforms=["mikrotik"],
    requires_device=True,
    internal_only=True,
    timeout_seconds=30.0,
    logging_policy=LoggingPolicy.ALWAYS,
    executor=execute_mikrotik_config_apply,
)
