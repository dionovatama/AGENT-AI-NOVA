from __future__ import annotations

import enum
import uuid
from typing import Any, Awaitable, Callable, Type

from pydantic import BaseModel

class PermissionLevel(str, enum.Enum):
  
    READ = "read"
    MODIFY = "modify"
    HIGH_RISK = "high_risk"

class RiskLevel(str, enum.Enum):

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class LoggingPolicy(str, enum.Enum):

    ALWAYS = "always"
    RESULT_ONLY = "result_only"
    MINIMAL = "minimal"


ToolExecutor = Callable[[BaseModel], Awaitable[BaseModel]]

class ToolDefinition(BaseModel):

    name : str
    description : str
    input_model: Type[BaseModel]
    output_model: Type[BaseModel]
    permission_level: PermissionLevel
    risk_level: RiskLevel
    supported_platforms: list[str]
    timeout_seconds: float= 15.0
    logging_policy: LoggingPolicy = LoggingPolicy.ALWAYS
    executor: ToolExecutor

    # Tool README (README (1).md) section 3 — "ExecutionContext & device_id".
    # True untuk tool yang menyasar satu device nyata milik user (mis.
    # mikrotik.*, nanti cisco.*). Kalau True, ToolManager WAJIB menolak
    # request tanpa device_id SEBELUM executor dipanggil, dan executor
    # dipanggil dengan parameter kedua (ctx: ExecutionContext). Default
    # False supaya tool lama (ping, linux.*, web.*) tidak berubah perilaku.
    requires_device: bool = False

    model_config = {"arbitrary_types_allowed": True}

class ToolRequest(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = {}
    confirmed: bool = False
    # Wajib diisi kalau tool yang diminta punya requires_device=True
    # (README (1).md section 3). Diabaikan untuk tool lain.
    device_id: uuid.UUID | None = None

class ToolResult(BaseModel):
    success: bool
    tool_name: str
    permission_level: PermissionLevel
    risk_level: RiskLevel
    output: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: float