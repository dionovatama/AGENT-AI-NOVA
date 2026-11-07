"""Network Management (Phase 6): topology nyata + refresh status device. Owner-scoped."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status\nfrom pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.states import effective_status
from app.agents.wiring import agent_manager
from app.database.models import Agent, Device, RelayTarget, TopologyLink, TopologyNode, User
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


class ManualNodeCreate(BaseModel):
    device_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=100)
    kind: str = Field(default="other", min_length=1, max_length=30)
    x: float = Field(default=80, ge=0, le=100000)
    y: float = Field(default=80, ge=0, le=100000)


class ManualNodeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    kind: str | None = Field(default=None, min_length=1, max_length=30)
    x: float | None = Field(default=None, ge=0, le=100000)
    y: float | None = Field(default=None, ge=0, le=100000)


class ManualLinkCreate(BaseModel):
    source_node_id: uuid.UUID
    target_node_id: uuid.UUID
    label: str | None = Field(default=None, max_length=100)
    connection_type: str = Field(default="ethernet", min_length=1, max_length=30)


def _manual_node_payload(node: TopologyNode, device: Device | None = None) -> dict:
    return {
        "id": str(node.id), "device_id": str(node.device_id) if node.device_id else None,
        "name": node.name, "kind": node.kind, "x": node.x, "y": node.y,
        "device": ({
            "id": str(device.id), "platform": device.platform, "host": device.host,
            "port": device.port, "reachability": device.reachability,
            "last_checked_at": device.last_checked_at.isoformat() if device.last_checked_at else None,
            "last_check_detail": device.last_check_detail,
        } if device else None),
        "created_at": node.created_at.isoformat(), "updated_at": node.updated_at.isoformat(),
    }


@router.get("/manual-topology")
def get_manual_topology(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> dict:
    nodes = db.query(TopologyNode).filter(TopologyNode.owner_id == current_user.id).order_by(TopologyNode.created_at).all()
    links = db.query(TopologyLink).filter(TopologyLink.owner_id == current_user.id).order_by(TopologyLink.created_at).all()
    device_ids = [n.device_id for n in nodes if n.device_id]
    devices = {d.id: d for d in db.query(Device).filter(
        Device.owner_id == current_user.id, Device.id.in_(device_ids)
    ).all()} if device_ids else {}
    monitored_devices = db.query(Device).join(
        RelayTarget, RelayTarget.device_id == Device.id
    ).filter(
        Device.owner_id == current_user.id, RelayTarget.owner_id == current_user.id
    ).distinct().order_by(Device.created_at).all()
    placed_ids = {n.device_id for n in nodes if n.device_id}
    return {
        "nodes": [_manual_node_payload(n, devices.get(n.device_id)) for n in nodes],
        "available_devices": [{
            "id": str(d.id), "name": d.name, "platform": d.platform, "host": d.host,
            "port": d.port, "connection_type": d.connection_type,
        } for d in monitored_devices if d.id not in placed_ids],
        "links": [{
            "id": str(link.id), "source_node_id": str(link.source_node_id),
            "target_node_id": str(link.target_node_id), "label": link.label,
            "connection_type": link.connection_type,
        } for link in links],
    }


@router.post("/manual-topology/nodes", status_code=status.HTTP_201_CREATED)
def create_manual_node(
    payload: ManualNodeCreate,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> dict:
    device = None
    if payload.device_id:
        device = db.query(Device).filter(
            Device.id == payload.device_id, Device.owner_id == current_user.id
        ).first()
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found.")
        target = db.query(RelayTarget).filter(
            RelayTarget.owner_id == current_user.id, RelayTarget.device_id == device.id
        ).first()
        if target is None:
            raise HTTPException(
                status_code=400,
                detail="Device must be assigned to a Remote Agent relay target before it can be monitored on topology.",
            )
        existing = db.query(TopologyNode).filter(
            TopologyNode.owner_id == current_user.id, TopologyNode.device_id == device.id
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Device already has a topology node.")
    node = TopologyNode(owner_id=current_user.id, device_id=payload.device_id,
                        name=payload.name.strip(), kind=payload.kind, x=payload.x, y=payload.y)
    db.add(node)
    db.commit()
    db.refresh(node)
    return _manual_node_payload(node, device)


@router.patch("/manual-topology/nodes/{node_id}")
def update_manual_node(
    node_id: uuid.UUID, payload: ManualNodeUpdate,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> dict:
    node = db.query(TopologyNode).filter(
        TopologyNode.id == node_id, TopologyNode.owner_id == current_user.id
    ).first()
    if node is None:
        raise HTTPException(status_code=404, detail="Topology node not found.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(node, key, value)
    db.commit()
    db.refresh(node)
    device = db.query(Device).filter(
        Device.id == node.device_id, Device.owner_id == current_user.id
    ).first() if node.device_id else None
    return _manual_node_payload(node, device)


@router.delete("/manual-topology/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_manual_node(
    node_id: uuid.UUID, current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    node = db.query(TopologyNode).filter(
        TopologyNode.id == node_id, TopologyNode.owner_id == current_user.id
    ).first()
    if node is None:
        raise HTTPException(status_code=404, detail="Topology node not found.")
    db.delete(node)
    db.commit()


@router.post("/manual-topology/links", status_code=status.HTTP_201_CREATED)
def create_manual_link(
    payload: ManualLinkCreate,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> dict:
    if payload.source_node_id == payload.target_node_id:
        raise HTTPException(status_code=422, detail="A node cannot link to itself.")
    ids = {row[0] for row in db.query(TopologyNode.id).filter(
        TopologyNode.owner_id == current_user.id,
        TopologyNode.id.in_([payload.source_node_id, payload.target_node_id]),
    ).all()}
    if ids != {payload.source_node_id, payload.target_node_id}:
        raise HTTPException(status_code=404, detail="Topology node not found.")
    existing = db.query(TopologyLink).filter(
        TopologyLink.owner_id == current_user.id,
        TopologyLink.source_node_id == payload.source_node_id,
        TopologyLink.target_node_id == payload.target_node_id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Link already exists.")
    link = TopologyLink(owner_id=current_user.id, source_node_id=payload.source_node_id,
                        target_node_id=payload.target_node_id, label=payload.label,
                        connection_type=payload.connection_type)
    db.add(link)
    db.commit()
    db.refresh(link)
    return {"id": str(link.id), "source_node_id": str(link.source_node_id),
            "target_node_id": str(link.target_node_id), "label": link.label,
            "connection_type": link.connection_type}


@router.delete("/manual-topology/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_manual_link(
    link_id: uuid.UUID, current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    link = db.query(TopologyLink).filter(
        TopologyLink.id == link_id, TopologyLink.owner_id == current_user.id
    ).first()
    if link is None:
        raise HTTPException(status_code=404, detail="Topology link not found.")
    db.delete(link)
    db.commit()
