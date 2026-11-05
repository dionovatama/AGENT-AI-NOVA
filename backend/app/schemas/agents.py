"""Schema REST untuk manajemen Remote Agent. token_hash TIDAK pernah ada di response."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class AgentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v or not all(ch.isprintable() for ch in v):
            raise ValueError("name must be non-empty printable text")
        return v


class AgentResponse(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    status: str  # status EFEKTIF (berdasar kesegaran heartbeat), bukan kolom mentah
    os: str | None = None
    hostname: str | None = None
    agent_version: str | None = None
    last_heartbeat_at: datetime | None = None
    last_connected_at: datetime | None = None
    last_disconnected_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime


class AgentCreatedResponse(AgentResponse):
    """Hanya dikembalikan saat create / rotate-token. Token tidak bisa diambil lagi."""
    token: str
    connect_path: str
