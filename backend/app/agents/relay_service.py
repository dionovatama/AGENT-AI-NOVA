"""Entry point backend untuk membuka relay TCP lewat Remote Agent.

Dipakai Phase 5 (transport relay untuk adapter MikroTik):

    channel = await open_relay(db, owner_id=user.id, target_id=t, port=8729)
    await channel.send(b"..."); data = await channel.recv(); await channel.close()

Otorisasi: target harus milik owner, port harus terdaftar, Agent harus online
dengan koneksi hidup di worker INI. Relay saat ini process-local; deployment
multi-worker butuh worker affinity atau broker bersama.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.agents.manager import AgentConnectionManager
from app.agents.relay_channel import RelayChannel, RelayOpenError
from app.agents.relay_sessions import RelaySessionError
from app.agents.states import AgentStatus, effective_status
from app.database.models import Agent, RelayTarget
from app.security.audit import record_audit_event

logger = logging.getLogger("nova.agents.relay")


class RelayUnavailable(Exception):
    """Relay tidak bisa dibuka. ``reason`` aman ditampilkan ke pemanggil."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class RelayTargetNotFound(RelayUnavailable):
    """Target tidak ada ATAU milik user lain (sengaja tidak dibedakan)."""


class RelayPortNotAllowed(RelayUnavailable):
    pass


class AgentOffline(RelayUnavailable):
    pass


def _audit(action: str, status: str, owner_id: uuid.UUID, meta: dict, error: str | None = None) -> None:
    try:
        record_audit_event(action=action, result_status=status, user_id=owner_id,
                           request_metadata=meta, error_message=error)
    except Exception:  # noqa: BLE001 -- audit tidak boleh menjatuhkan relay
        logger.warning("relay audit gagal action=%s", action, exc_info=True)


async def open_relay(
    db: Session, *, owner_id: uuid.UUID, target_id: uuid.UUID, port: int,
    manager: AgentConnectionManager | None = None, open_timeout: float = 15.0,
) -> RelayChannel:
    if manager is None:
        from app.agents.wiring import agent_manager as manager  # noqa: PLC0415

    target = (
        db.query(RelayTarget)
        .filter(RelayTarget.id == target_id, RelayTarget.owner_id == owner_id)
        .first()
    )
    if target is None:
        raise RelayTargetNotFound("relay target not found")
    meta = {"target_id": str(target.id), "agent_id": str(target.agent_id), "port": port,
            "device_id": str(target.device_id) if target.device_id else None}

    if isinstance(port, bool) or port not in (target.ports or []):
        _audit("relay.open", "FAILED", owner_id, meta, "port not allowed")
        raise RelayPortNotAllowed("port is not allowed for this target")

    agent = db.query(Agent).filter(Agent.id == target.agent_id, Agent.owner_id == owner_id).first()
    if agent is None or agent.connection_id is None:
        _audit("relay.open", "FAILED", owner_id, meta, "agent offline")
        raise AgentOffline("agent is offline")
    state = effective_status(agent.status, agent.last_heartbeat_at, datetime.now(timezone.utc),
                             manager.cfg.heartbeat_timeout_seconds)
    if state is not AgentStatus.ONLINE:
        _audit("relay.open", "FAILED", owner_id, meta, "agent offline")
        raise AgentOffline("agent is offline")

    try:
        channel = await manager.open_relay_channel(
            agent_id=agent.id, owner_id=owner_id, connection_id=agent.connection_id,
            target_id=target.id, port=port, open_timeout=open_timeout,
        )
    except RelaySessionError as exc:
        _audit("relay.open", "FAILED", owner_id, meta, str(exc)[:160])
        raise AgentOffline("agent connection is not available on this worker") from None
    except RelayOpenError as exc:
        _audit("relay.open", "FAILED", owner_id, meta, exc.code)
        raise RelayUnavailable(f"agent could not open the tunnel ({exc.code})") from None
    await asyncio.to_thread(_audit, "relay.open", "SUCCESS", owner_id, meta)
    return channel
