from __future__ import annotations

import enum
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

    model_config = {"arbitrary_types_allowed": True}

class ToolRequest(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = {}
    confirmed: bool = False

class ToolResult(BaseModel):
    success: bool
    tool_name: str
    permission_level: PermissionLevel
    risk_level: RiskLevel
    output: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: float 

    

