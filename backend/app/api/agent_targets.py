"""CRUD target relay per Agent. Owner-scoped: milik user lain -> 404."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.models import Agent, Device, RelayTarget, User
from app.database.session import get_db
from app.schemas.relay_targets import (
    MAX_TARGETS_PER_AGENT, RelayTargetCreateRequest, RelayTargetPinUpdateRequest, RelayTargetResponse,
)
from app.security.audit import record_audit_event
from app.security.dependencies import get_current_user

router = APIRouter(tags=["agent-targets"])


def _to_response(t: RelayTarget) -> RelayTargetResponse:
    return RelayTargetResponse(
        id=t.id, agent_id=t.agent_id, device_id=t.device_id, name=t.name, host=t.host,
        ports=list(t.ports), tls_fingerprint=t.tls_fingerprint, created_at=t.created_at,
        agent_config={"target_id": str(t.id), "host": t.host, "ports": list(t.ports)},
    )


def _owned_agent(db: Session, agent_id: uuid.UUID, owner: User) -> Agent:
    agent = db.query(Agent).filter(Agent.id == agent_id, Agent.owner_id == owner.id).first()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return agent


@router.post("/agents/{agent_id}/targets", response_model=RelayTargetResponse,
             status_code=status.HTTP_201_CREATED)
def create_target(
    agent_id: uuid.UUID, payload: RelayTargetCreateRequest,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> RelayTargetResponse:
    agent = _owned_agent(db, agent_id, current_user)
    if payload.device_id is not None:
        owned = db.query(Device.id).filter(
            Device.id == payload.device_id, Device.owner_id == current_user.id).first()
        if owned is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found.")
    count = db.query(RelayTarget).filter(RelayTarget.agent_id == agent.id).count()
    if count >= MAX_TARGETS_PER_AGENT:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Too many targets for this agent.")
    target = RelayTarget(
        owner_id=current_user.id, agent_id=agent.id, device_id=payload.device_id,
        name=payload.name, host=payload.host, ports=payload.ports,
        tls_fingerprint=payload.tls_fingerprint,
    )
    db.add(target)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Target name already exists.")
    db.refresh(target)
    record_audit_event(
        action="agent.target.created", result_status="SUCCESS", user_id=current_user.id,
        request_metadata={"agent_id": str(agent.id), "target_id": str(target.id),
                          "host": target.host, "ports": list(target.ports),
                          "tls_pinned": target.tls_fingerprint is not None},
    )
    return _to_response(target)


@router.get("/agents/{agent_id}/targets", response_model=list[RelayTargetResponse])
def list_targets(
    agent_id: uuid.UUID,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> list[RelayTargetResponse]:
    agent = _owned_agent(db, agent_id, current_user)
    rows = (db.query(RelayTarget)
            .filter(RelayTarget.agent_id == agent.id, RelayTarget.owner_id == current_user.id)
            .order_by(RelayTarget.created_at).all())
    return [_to_response(t) for t in rows]


@router.patch("/agents/{agent_id}/targets/{target_id}", response_model=RelayTargetResponse)
def update_target_pin(
    agent_id: uuid.UUID, target_id: uuid.UUID, payload: RelayTargetPinUpdateRequest,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> RelayTargetResponse:
    """Replace or clear a target certificate pin; target remains owner-scoped."""
    agent = _owned_agent(db, agent_id, current_user)
    target = db.query(RelayTarget).filter(
        RelayTarget.id == target_id, RelayTarget.agent_id == agent.id,
        RelayTarget.owner_id == current_user.id).first()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found.")
    target.tls_fingerprint = payload.tls_fingerprint
    db.commit()
    db.refresh(target)
    record_audit_event(
        action="agent.target.pin_updated", result_status="SUCCESS", user_id=current_user.id,
        request_metadata={"agent_id": str(agent.id), "target_id": str(target.id),
                          "tls_pinned": target.tls_fingerprint is not None},
    )
    return _to_response(target)


@router.delete("/agents/{agent_id}/targets/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_target(
    agent_id: uuid.UUID, target_id: uuid.UUID,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> Response:
    agent = _owned_agent(db, agent_id, current_user)
    target = db.query(RelayTarget).filter(
        RelayTarget.id == target_id, RelayTarget.agent_id == agent.id,
        RelayTarget.owner_id == current_user.id).first()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found.")
    db.delete(target)
    db.commit()
    record_audit_event(
        action="agent.target.deleted", result_status="SUCCESS", user_id=current_user.id,
        request_metadata={"agent_id": str(agent.id), "target_id": str(target_id)},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
