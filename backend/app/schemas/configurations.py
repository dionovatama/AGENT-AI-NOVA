"""
Pydantic API schemas for Configuration Engine endpoints (PRD section 19-21, 33).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.network.models import ChangeSet
from app.tools.schemas import RiskLevel


class ConfigurationCreateRequest(BaseModel):
    """Payload untuk membuat proposal konfigurasi baru."""
    device_id: uuid.UUID
    change_set: ChangeSet
    proposed_risk_level: RiskLevel | None = None


class ConfigurationResponse(BaseModel):
    """Representasi detail satu proposal/rencana konfigurasi."""
    id: uuid.UUID
    owner_id: uuid.UUID
    device_id: uuid.UUID
    status: str
    risk_level: str
    change_set: dict[str, Any]
    plan_hash: str
    state_fingerprint: str
    approved_by: uuid.UUID | None = None
    approved_at: datetime | None = None
    expires_at: datetime | None = None
    applied_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    # Preview data (hanya disertakan saat generate / detail view)
    structured_diff: list[dict[str, Any]] | None = None
    cli_preview: str | None = None

    model_config = {"from_attributes": True}
