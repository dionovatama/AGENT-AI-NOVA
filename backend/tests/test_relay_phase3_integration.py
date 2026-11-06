import asyncio
import json
import uuid

import pytest

from app.agents.manager import AgentConnectionManager, AgentRuntimeConfig, _Session
from app.agents.relay_sessions import RelayState
from tests.agents_fakes import FakeSocket, FakeStore


def _relay_data(session_id: uuid.UUID, seq: int) -> str:
    return json.dumps({
        "type": "DATA",
        "session_id": str(session_id),
        "seq": seq,
        "data": "eA==",
    })


@pytest.mark.asyncio
async def test_relay_frames_use_separate_rate_budget():
    store = FakeStore()
    agent_id, _ = store.add_agent()
    owner_id = store.row(agent_id)["owner_id"]
    connection_id = uuid.uuid4()
    store.row(agent_id)["connection_id"] = connection_id

    manager = AgentConnectionManager(
        store=store,
        cfg=AgentRuntimeConfig(
            heartbeat_interval_seconds=0.1,
            heartbeat_timeout_seconds=1.0,
            heartbeat_min_db_interval_seconds=0.0,
            max_messages_per_window=2,
            message_window_seconds=10.0,
            relay_messages_per_window=2,
            relay_message_window_seconds=10.0,
        ),
    )
    target_id = uuid.uuid4()
    relay = manager.relay_sessions.create(
        agent_id=agent_id,
        owner_id=owner_id,
        connection_id=connection_id,
        target_id=target_id,
        port=8728,
    )
    manager.relay_sessions.mark_open(
        relay.session_id,
        agent_id=agent_id,
        owner_id=owner_id,
        connection_id=connection_id,
    )

    sock = FakeSocket()
    session = _Session(
        agent_id=agent_id,
        owner_id=owner_id,
        connection_id=connection_id,
        os="Windows 11 x64",
        agent_version="0.1.0",
    )
    sock.client_send_raw(_relay_data(relay.session_id, 1))
    sock.client_send_raw(_relay_data(relay.session_id, 2))
    sock.client_close(1000)

    await manager._run_session(sock, session)

    assert relay.state is RelayState.CLOSED
    assert sock.closed is None
    assert "release_connection" in store.calls


@pytest.mark.asyncio
async def test_stale_relay_close_and_data_do_not_kill_agent_connection():
    store = FakeStore()
    agent_id, _ = store.add_agent()
    owner_id = store.row(agent_id)["owner_id"]
    connection_id = uuid.uuid4()
    store.row(agent_id)["connection_id"] = connection_id

    manager = AgentConnectionManager(
        store=store,
        cfg=AgentRuntimeConfig(
            heartbeat_interval_seconds=0.1,
            heartbeat_timeout_seconds=1.0,
            heartbeat_min_db_interval_seconds=0.0,
            max_messages_per_window=10,
            relay_messages_per_window=10,
        ),
    )
    session = _Session(agent_id, owner_id, connection_id, "Windows 11 x64", "0.1.0")
    stale = uuid.uuid4()

    sock = FakeSocket()
    sock.client_send_raw(_relay_data(stale, 1))
    sock.client_send_raw(json.dumps({
        "type": "CLOSE_TUNNEL",
        "session_id": str(stale),
        "reason": "requested",
    }))
    sock.client_close(1000)

    await manager._run_session(sock, session)

    assert sock.closed is None
    assert "release_connection" in store.calls


@pytest.mark.asyncio
async def test_relay_lifecycle_keeps_heartbeat_alive_and_closes_cleanly():
    store = FakeStore()
    agent_id, _ = store.add_agent()
    owner_id = store.row(agent_id)["owner_id"]
    connection_id = uuid.uuid4()
    store.row(agent_id)["connection_id"] = connection_id

    manager = AgentConnectionManager(
        store=store,
        cfg=AgentRuntimeConfig(
            heartbeat_interval_seconds=0.1,
            heartbeat_timeout_seconds=1.0,
            heartbeat_min_db_interval_seconds=0.0,
            max_messages_per_window=1,
            message_window_seconds=10.0,
            relay_messages_per_window=10,
            relay_message_window_seconds=10.0,
        ),
    )
    session = _Session(agent_id, owner_id, connection_id, "Windows 11 x64", "0.1.0")
    relay = manager.relay_sessions.create(
        agent_id=agent_id,
        owner_id=owner_id,
        connection_id=connection_id,
        target_id=uuid.uuid4(),
        port=8729,
    )

    sock = FakeSocket()
    sock.client_send_raw(json.dumps({
        "type": "TUNNEL_OPENED",
        "request_id": str(relay.request_id),
        "session_id": str(relay.session_id),
    }))
    sock.client_send_raw(_relay_data(relay.session_id, 1))
    sock.client_send_raw(json.dumps({"type": "heartbeat", "seq": 1}))
    sock.client_send_raw(json.dumps({
        "type": "CLOSE_TUNNEL",
        "session_id": str(relay.session_id),
        "reason": "requested",
    }))
    sock.client_send_raw(json.dumps({"type": "heartbeat", "seq": 2}))
    sock.client_send_raw(json.dumps({"type": "bye"}))

    await manager._run_session(sock, session)

    assert relay.state is RelayState.CLOSED
    assert any(item.get("type") == "heartbeat_ack" and item.get("seq") == 1 for item in sock.sent)
    assert any(item.get("type") == "heartbeat_ack" and item.get("seq") == 2 for item in sock.sent)
    assert "release_connection" in store.calls
