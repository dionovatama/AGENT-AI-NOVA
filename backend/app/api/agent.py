"""Authenticated WebSocket gateway for NOVA Remote Agents.

Phase 1 deliberately supports connection lifecycle and heartbeat only.
No remote command execution is exposed by this endpoint.
"""
import asyncio
import hmac
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import settings

router = APIRouter(prefix="/agent", tags=["remote-agent"])
_active_agents: dict[str, WebSocket] = {}
_active_agents_lock = asyncio.Lock()


def _agent_token_map() -> dict[str, str]:
    try:
        value = json.loads(settings.nova_agent_tokens_json or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("NOVA_AGENT_TOKENS_JSON must contain a valid JSON object.") from exc
    if not isinstance(value, dict):
        raise RuntimeError("NOVA_AGENT_TOKENS_JSON must be a JSON object.")
    return {
        str(agent_id): token
        for agent_id, token in value.items()
        if isinstance(token, str) and token
    }


@router.websocket("/ws")
async def agent_websocket(websocket: WebSocket) -> None:
    """Accept a pre-provisioned Agent identity and maintain its heartbeat session."""
    await websocket.accept()
    agent_id: str | None = None

    try:
        try:
            auth_message = await asyncio.wait_for(websocket.receive_json(), timeout=10)
        except asyncio.TimeoutError:
            await websocket.close(code=4408, reason="Authentication timeout")
            return

        if not isinstance(auth_message, dict) or auth_message.get("type") != "authenticate":
            await websocket.close(code=4400, reason="Authentication message required")
            return

        raw_agent_id = auth_message.get("agent_id")
        supplied_token = auth_message.get("token")
        try:
            agent_id = str(uuid.UUID(str(raw_agent_id)))
        except (ValueError, TypeError, AttributeError):
            await websocket.close(code=4401, reason="Invalid agent identity")
            return

        if not isinstance(supplied_token, str) or not supplied_token:
            await websocket.close(code=4401, reason="Invalid agent credentials")
            return

        try:
            expected_token = _agent_token_map().get(agent_id)
        except RuntimeError:
            await websocket.close(code=1011, reason="Agent authentication is misconfigured")
            return

        if expected_token is None or not hmac.compare_digest(expected_token, supplied_token):
            await websocket.close(code=4401, reason="Invalid agent credentials")
            return

        async with _active_agents_lock:
            previous = _active_agents.get(agent_id)
            _active_agents[agent_id] = websocket

        if previous is not None and previous is not websocket:
            try:
                await previous.close(code=4001, reason="Agent reconnected")
            except Exception:
                pass

        await websocket.send_json({
            "type": "authenticated",
            "agent_id": agent_id,
            "heartbeat_interval_seconds": settings.nova_agent_heartbeat_interval_seconds,
        })

        while True:
            message = await websocket.receive_json()
            if not isinstance(message, dict) or message.get("type") != "heartbeat":
                await websocket.close(code=4400, reason="Unsupported message type")
                return
            if str(message.get("agent_id", "")) != agent_id:
                await websocket.close(code=4401, reason="Agent identity mismatch")
                return

            await websocket.send_json({
                "type": "heartbeat_ack",
                "server_time": datetime.now(timezone.utc).isoformat(),
            })

    except WebSocketDisconnect:
        pass
    except Exception:
        # Do not log authentication payloads or secrets. The ASGI server handles
        # unexpected exceptions; the connection is removed in the finally block.
        try:
            await websocket.close(code=1011, reason="Agent connection error")
        except Exception:
            pass
    finally:
        if agent_id is not None:
            async with _active_agents_lock:
                if _active_agents.get(agent_id) is websocket:
                    _active_agents.pop(agent_id, None)
