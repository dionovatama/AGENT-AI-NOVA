"""Backend relay channel: open handshake, byte flow both ways, close, disconnect."""
import asyncio
import base64
import json
import uuid

import pytest

from app.agents.manager import AgentConnectionManager, AgentRuntimeConfig, _Session
from app.agents.registry import LiveConnection
from app.agents.relay_channel import RelayChannelClosed, RelayOpenError
from app.agents.relay_sessions import RelayState, RelaySessionError
from tests.agents_fakes import FakeStore


class _Sock:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


def _setup():
    manager = AgentConnectionManager(store=FakeStore(), cfg=AgentRuntimeConfig())
    agent_id, owner_id, conn_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    sock = _Sock()
    manager.registry.register(LiveConnection(agent_id, conn_id, owner_id, sock))
    session = _Session(agent_id, owner_id, conn_id, "Linux", "0.2.0")
    return manager, sock, session


async def _agent_says(manager, session, frame: dict) -> None:
    await manager._handle_relay_message(json.dumps(frame), session)


async def _open(manager, sock, session, answer=True):
    target = uuid.uuid4()
    task = asyncio.create_task(manager.open_relay_channel(
        agent_id=session.agent_id, owner_id=session.owner_id,
        connection_id=session.connection_id, target_id=target, port=8729, open_timeout=1.0))
    while not sock.sent:
        await asyncio.sleep(0)
    req = sock.sent[0]
    assert req["type"] == "OPEN_TUNNEL" and req["target_id"] == str(target) and req["port"] == 8729
    if answer:
        await _agent_says(manager, session, {
            "type": "TUNNEL_OPENED", "request_id": req["request_id"], "session_id": req["session_id"]})
    return task, req


@pytest.mark.asyncio
async def test_open_then_bytes_both_ways_then_close():
    manager, sock, session = _setup()
    task, req = await _open(manager, sock, session)
    ch = await task
    sid = req["session_id"]
    assert manager.relay_sessions.get(
        uuid.UUID(sid), agent_id=session.agent_id, owner_id=session.owner_id,
        connection_id=session.connection_id).state is RelayState.OPEN

    await ch.send(b"x" * 70_000)  # > 32 KiB -> 3 frames, increasing seq
    frames = [f for f in sock.sent if f["type"] == "DATA"]
    assert [f["seq"] for f in frames] == [0, 1, 2]
    assert sum(len(base64.b64decode(f["data"])) for f in frames) == 70_000

    await _agent_says(manager, session, {
        "type": "DATA", "session_id": sid, "seq": 0, "data": base64.b64encode(b"reply").decode()})
    assert await ch.recv() == b"reply"

    await ch.close()
    assert sock.sent[-1] == {"type": "CLOSE_TUNNEL", "session_id": sid, "reason": "requested"}
    assert ch.closed and not manager.relay_channels
    with pytest.raises(RelayChannelClosed):
        await ch.send(b"late")
    assert await ch.recv() is None


@pytest.mark.asyncio
async def test_agent_refusal_raises_open_error_with_code():
    manager, sock, session = _setup()
    task, req = await _open(manager, sock, session, answer=False)
    await _agent_says(manager, session, {
        "type": "TUNNEL_ERROR", "request_id": req["request_id"], "session_id": req["session_id"],
        "code": "TARGET_NOT_ALLOWED", "message": "target not allowed"})
    with pytest.raises(RelayOpenError) as exc:
        await task
    assert exc.value.code == "TARGET_NOT_ALLOWED"
    assert not manager.relay_channels


@pytest.mark.asyncio
async def test_open_timeout_cleans_up_and_tells_agent():
    manager, sock, session = _setup()
    task, req = await _open(manager, sock, session, answer=False)
    with pytest.raises(RelayOpenError) as exc:
        await task
    assert exc.value.code == "TIMEOUT"
    assert not manager.relay_channels
    assert sock.sent[-1]["type"] == "CLOSE_TUNNEL" and sock.sent[-1]["reason"] == "timeout"


@pytest.mark.asyncio
async def test_agent_closes_tunnel_ends_channel_without_echo():
    manager, sock, session = _setup()
    task, req = await _open(manager, sock, session)
    ch = await task
    before = len(sock.sent)
    await _agent_says(manager, session, {
        "type": "CLOSE_TUNNEL", "session_id": req["session_id"], "reason": "peer_closed"})
    assert await ch.recv() is None and ch.closed and ch.close_reason == "peer_closed"
    assert len(sock.sent) == before


@pytest.mark.asyncio
async def test_agent_disconnect_ends_all_channels():
    manager, sock, session = _setup()
    task, _ = await _open(manager, sock, session)
    ch = await task
    manager._end_channels_for_connection(session.agent_id, session.connection_id)
    assert await ch.recv() is None and ch.close_reason == "agent_disconnect"
    assert not manager.relay_channels


@pytest.mark.asyncio
async def test_slow_reader_overflow_closes_session():
    manager, sock, session = _setup()
    task, req = await _open(manager, sock, session)
    ch = await task
    frame = {"type": "DATA", "session_id": req["session_id"], "seq": 0,
             "data": base64.b64encode(b"a").decode()}
    for _ in range(80):  # queue holds 64; caller never reads
        await _agent_says(manager, session, frame)
    assert ch.closed
    assert sock.sent[-1]["type"] == "CLOSE_TUNNEL" and sock.sent[-1]["reason"] == "error"


@pytest.mark.asyncio
async def test_open_requires_live_matching_connection():
    manager, sock, session = _setup()
    with pytest.raises(RelaySessionError):
        await manager.open_relay_channel(
            agent_id=session.agent_id, owner_id=uuid.uuid4(),  # wrong tenant
            connection_id=session.connection_id, target_id=uuid.uuid4(), port=8729)
    with pytest.raises(RelaySessionError):
        await manager.open_relay_channel(
            agent_id=session.agent_id, owner_id=session.owner_id,
            connection_id=uuid.uuid4(), target_id=uuid.uuid4(), port=8729)  # stale connection
    assert sock.sent == []
