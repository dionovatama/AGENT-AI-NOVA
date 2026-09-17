"""
Pydantic schemas for Devices, Credentials, and Audit Logs.

Prinsip:
- Zero Secret Exposure: CredentialResponse tidak membocorkan konten atau referensi sensitif.
- Isolasi kepemilikan (owner_id) ditentukan oleh JWT backend, bukan input client.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DeviceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    platform: str = Field(min_length=1, max_length=50)  # linux, windows, mikrotik, cisco
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=22, ge=1, le=65535)
    connection_type: str = Field(default="ssh", max_length=50)
    status: str = Field(default="active", max_length=50)
    credential_id: uuid.UUID | None = None
    metadata: dict[str, Any] | None = None


class DeviceResponse(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    credential_id: uuid.UUID | None = None
    name: str
    platform: str
    host: str
    port: int
    connection_type: str
    status: str
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="device_metadata")
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CredentialCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: str = Field(min_length=1, max_length=50)  # ssh_key, password, api_token
    secret_reference: str = Field(min_length=1, max_length=255)


class CredentialResponse(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    type: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AuditLogResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None = None
    device_id: uuid.UUID | None = None
    tool_name: str | None = None
    permission: str | None = None
    risk_level: str | None = None
    action: str
    request_metadata: dict[str, Any] | None = None
    result_status: str
    verification_status: str | None = None
    error_message: str | None = None
    duration_ms: float | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
