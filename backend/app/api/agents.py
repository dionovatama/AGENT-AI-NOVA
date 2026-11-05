"""
Manajemen Remote Agent (REST) + endpoint WebSocket agent.

- Semua endpoint REST owner-scoped: agent milik user lain -> 404 (bukan 403),
  konsisten dengan app/api/devices.py.
- Token plaintext hanya muncul di response POST /agents dan
  POST /agents/{id}/rotate-token; yang disimpan hanya hash-nya.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from anyio import from_thread
from fastapi import APIRouter, Depends, HTTPException, Response, WebSocket, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.starlette_adapter import StarletteSocket
from app.agents.states import AgentStatus, effective_status
from app.agents.tokens import generate_agent_token, hash_agent_token
from app.agents.wiring import agent_manager
from app.database.models import Agent, User
from app.database.session import get_db
from app.schemas.agents import AgentCreatedResponse, AgentCreateRequest, AgentResponse
from app.security.audit import record_audit_event
from app.security.dependencies import get_current_user

logger = logging.getLogger("nova.agents.api")

router = APIRouter(tags=["agents"])


def _to_response(agent: Agent) -> AgentResponse:
    effective = effective_status(
        agent.status, agent.last_heartbeat_at,
        datetime.now(timezone.utc), agent_manager.cfg.heartbeat_timeout_seconds,
    )
    return AgentResponse(
        id=agent.id, owner_id=agent.owner_id, name=agent.name, status=effective.value,
        os=agent.os, hostname=agent.hostname, agent_version=agent.agent_version,
        last_heartbeat_at=agent.last_heartbeat_at, last_connected_at=agent.last_connected_at,
        last_disconnected_at=agent.last_disconnected_at, last_error=agent.last_error,
        created_at=agent.created_at,
    )


def _created_response(agent: Agent, token: str) -> AgentCreatedResponse:
    return AgentCreatedResponse(
        **_to_response(agent).model_dump(), token=token, connect_path=f"/ws/agent/{agent.id}",
    )


def _get_owned_agent(db: Session, agent_id: uuid.UUID, owner: User, lock: bool = False) -> Agent:
    """Ambil agent milik `owner`; agent milik user lain diperlakukan tidak ada (404).

    lock=True mengunci baris (FOR UPDATE) sampai commit. WAJIB untuk operasi yang
    mencabut kredensial (rotate/delete): kunci ini diserialkan dengan
    claim_connection di SqlAgentStore sehingga token yang dicabut tidak bisa
    menyelip membuka koneksi baru, dan state ORM yang basi tidak membuat
    `connection_id = None` dianggap 'tidak berubah' lalu tidak ditulis."""
    query = db.query(Agent).filter(Agent.id == agent_id, Agent.owner_id == owner.id)
    if lock:
        query = query.with_for_update().populate_existing()
    agent = query.first()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return agent


def _close_local_connection(agent_id: uuid.UUID) -> None:
    """Endpoint sync berjalan di worker thread; jembatani ke event loop.
    Gagal di sini tidak boleh menggagalkan operasi REST (koneksi di worker
    lain tetap tertutup lewat heartbeat berikutnya)."""
    try:
        from_thread.run(agent_manager.disconnect_local, agent_id)
    except Exception:  # noqa: BLE001
        logger.warning("gagal menutup koneksi lokal agent=%s", agent_id, exc_info=True)


@router.post("/agents", response_model=AgentCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_agent(
    payload: AgentCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentCreatedResponse:
    token = generate_agent_token()
    agent = Agent(
        owner_id=current_user.id, name=payload.name,
        token_hash=hash_agent_token(token), status=AgentStatus.OFFLINE.value,
    )
    db.add(agent)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent name already exists.")
    db.refresh(agent)
    record_audit_event(
        action="agent.created", result_status="SUCCESS", user_id=current_user.id,
        request_metadata={"agent_id": str(agent.id), "name": agent.name},
    )
    return _created_response(agent, token)


@router.get("/agents", response_model=list[AgentResponse])
def list_agents(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> list[AgentResponse]:
    agents = db.query(Agent).filter(Agent.owner_id == current_user.id).order_by(Agent.created_at).all()
    return [_to_response(a) for a in agents]


@router.get("/agents/{agent_id}", response_model=AgentResponse)
def get_agent(
    agent_id: uuid.UUID,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> AgentResponse:
    return _to_response(_get_owned_agent(db, agent_id, current_user))


@router.post("/agents/{agent_id}/rotate-token", response_model=AgentCreatedResponse)
def rotate_agent_token(
    agent_id: uuid.UUID,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> AgentCreatedResponse:
    """Token lama langsung tidak berlaku. Koneksi aktif diputus: seketika bila
    ada di worker ini, selambatnya satu interval heartbeat bila di worker lain
    (kepemilikan koneksi di-reset sehingga heartbeat berikutnya ditolak)."""
    agent = _get_owned_agent(db, agent_id, current_user, lock=True)
    token = generate_agent_token()
    now = datetime.now(timezone.utc)
    agent.token_hash = hash_agent_token(token)
    agent.connection_id = None
    agent.worker_id = None
    agent.status = AgentStatus.OFFLINE.value
    agent.last_disconnected_at = now
    db.commit()
    db.refresh(agent)
    _close_local_connection(agent.id)
    record_audit_event(
        action="agent.token_rotated", result_status="SUCCESS", user_id=current_user.id,
        request_metadata={"agent_id": str(agent.id)},
    )
    return _created_response(agent, token)


@router.post("/agents/{agent_id}/disconnect")
def disconnect_agent(
    agent_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    """Putuskan sesi Agent yang sedang aktif tanpa mencabut token.

    Agent akan mencoba menyambung kembali sesuai kebijakan reconnect miliknya.
    Untuk menghentikan koneksi secara permanen, stop service pada host Agent
    atau rotate token.
    """
    agent = _get_owned_agent(db, agent_id, current_user, lock=True)
    was_connected = agent.connection_id is not None
    now = datetime.now(timezone.utc)
    agent.connection_id = None
    agent.worker_id = None
    agent.status = AgentStatus.DISCONNECTED.value
    agent.last_disconnected_at = now
    db.commit()
    _close_local_connection(agent.id)
    record_audit_event(
        action="agent.disconnected",
        result_status="SUCCESS",
        user_id=current_user.id,
        request_metadata={"agent_id": str(agent.id), "was_connected": was_connected},
    )
    return {"disconnected": was_connected}


@router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent(
    agent_id: uuid.UUID,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> Response:
    agent = _get_owned_agent(db, agent_id, current_user, lock=True)
    deleted_id = agent.id
    db.delete(agent)
    db.commit()
    _close_local_connection(deleted_id)
    record_audit_event(
        action="agent.deleted", result_status="SUCCESS", user_id=current_user.id,
        request_metadata={"agent_id": str(deleted_id)},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.websocket("/ws/agent/{agent_id}")
async def agent_websocket(websocket: WebSocket, agent_id: str) -> None:
    """Endpoint koneksi Remote Agent. Seluruh logika ada di AgentConnectionManager;
    protokol: lihat app/agents/protocol.py."""
    await agent_manager.handle(StarletteSocket(websocket), agent_id)
