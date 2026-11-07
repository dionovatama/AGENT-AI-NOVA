"""Schema REST untuk target relay Agent. Host/port divalidasi di sini DAN di Agent."""

from __future__ import annotations

import ipaddress
import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, StrictInt, field_validator

from app.network.relay_tls import normalize_fingerprint

MAX_PORTS_PER_TARGET = 16
MAX_TARGETS_PER_AGENT = 256

_HOST_RE = re.compile(
    r"^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$"
)


def validate_target_host(value: str) -> str:
    """IP literal atau hostname. IP yang tidak pernah boleh dituju (loopback,
    link-local/metadata, multicast, unspecified, reserved) ditolak sejak
    pendaftaran; Agent menegakkan aturan yang sama saat connect."""
    host = value.strip()
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if not _HOST_RE.fullmatch(host):
            raise ValueError("host must be an IP address or a valid hostname") from None
        return host
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if (ip.is_unspecified or ip.is_multicast or ip.is_link_local
            or ip.is_reserved or ip.is_loopback):
        raise ValueError("host address is not allowed")
    return host


class RelayTargetCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    host: str = Field(min_length=1, max_length=255)
    ports: list[StrictInt] = Field(min_length=1, max_length=MAX_PORTS_PER_TARGET)
    device_id: uuid.UUID | None = None
    # SHA-256 sertifikat API-SSL router: 64 hex, boleh "AA:BB:.." atau "sha256:..".
    tls_fingerprint: str | None = Field(default=None, max_length=128)

    @field_validator("tls_fingerprint")
    @classmethod
    def _fp(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        return normalize_fingerprint(v)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v or not all(ch.isprintable() for ch in v):
            raise ValueError("name must be non-empty printable text")
        return v

    @field_validator("host")
    @classmethod
    def _host(cls, v: str) -> str:
        return validate_target_host(v)

    @field_validator("ports")
    @classmethod
    def _ports(cls, v: list[int]) -> list[int]:
        if any(isinstance(p, bool) or not 1 <= p <= 65535 for p in v):
            raise ValueError("ports must be integers between 1 and 65535")
        return sorted(set(v))


class RelayTargetResponse(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    device_id: uuid.UUID | None = None
    name: str
    host: str
    ports: list[int]
    tls_fingerprint: str | None = None
    created_at: datetime
    # Salin ke "relay_targets" di config.json Agent. Tanpa entri ini Agent
    # menolak target (allow-list lokal adalah batas keamanan sebenarnya).
    agent_config: dict


class RelayTargetPinUpdateRequest(BaseModel):
    """Replace or clear the pinned SHA-256 certificate fingerprint."""
    tls_fingerprint: str | None = Field(..., max_length=128)

    @field_validator("tls_fingerprint")
    @classmethod
    def _fp(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        return normalize_fingerprint(v)
