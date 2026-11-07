"""Network Management (Phase 6): topology nyata + refresh status device. Owner-scoped."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.agents.states import effective_status
from app.agents.wiring import agent_manager
from app.database.models import Agent, Device, RelayTarget, User
from app.database.session import get_db
from app.network.probe import probe_device
from app.network.topology import AgentIn, DeviceIn, TargetIn, build_topology
from app.security.audit import record_audit_event
from app.security.dependencies import get_current_user

router = APIRouter(prefix="/network", tags=["network"])


@router.get("/topology")
def get_topology(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> dict:
    now = datetime.now(timezone.utc)
    timeout = agent_manager.cfg.heartbeat_timeout_seconds
    agents = [
        AgentIn(
            id=str(a.id), name=a.name, hostname=a.hostname, last_heartbeat_at=a.last_heartbeat_at,
            status=effective_status(a.status, a.last_heartbeat_at, now, timeout).value,
        )
        for a in db.query(Agent).filter(Agent.owner_id == current_user.id).order_by(Agent.created_at).all()
    ]
    devices = [
        DeviceIn(
            id=str(d.id), name=d.name, platform=d.platform, host=d.host, port=d.port,
            connection_type=d.connection_type, reachability=d.reachability or "unknown",
            last_checked_at=d.last_checked_at, last_check_detail=d.last_check_detail,
        )
        for d in db.query(Device).filter(Device.owner_id == current_user.id).order_by(Device.created_at).all()
    ]
    targets = [
        TargetIn(
            id=str(t.id), agent_id=str(t.agent_id),
            device_id=str(t.device_id) if t.device_id else None,
            host=t.host, ports=tuple(t.ports or ()), pinned=bool(t.tls_fingerprint),
        )
        for t in db.query(RelayTarget).filter(RelayTarget.owner_id == current_user.id)
        .order_by(RelayTarget.created_at).all()
    ]
    return build_topology(agents, devices, targets, now)


@router.post("/devices/{device_id}/refresh")
async def refresh_device(
    device_id: uuid.UUID,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> dict:
    device = db.query(Device).filter(Device.id == device_id, Device.owner_id == current_user.id).first()
    if device is None:  # milik user lain diperlakukan tidak ada
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found.")
    result = await probe_device(db, device)
    if not result.cached:
        record_audit_event(
            action="network.device.refresh", result_status="SUCCESS", user_id=current_user.id,
            device_id=device.id, request_metadata={"reachability": result.reachability},
        )
    return {
        "device_id": str(device.id), "reachability": result.reachability, "detail": result.detail,
        "checked_at": result.checked_at.isoformat(), "cached": result.cached,
    }
