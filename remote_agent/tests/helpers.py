"""Test doubles: an in-memory WebSocket and a scripted NOVA backend."""

from __future__ import annotations

import asyncio
import json
import uuid

from nova_agent.config import AgentConfig
from nova_agent.transport import ConnectFailed, HandshakeRejected, TransportClosed

AGENT_ID = "3f2b8c1e-5d4a-4e7b-9a10-6c2d8e4f1a77"
TOKEN = "nova_agt_" + "A1b2C3d4E5" * 4 + "xyz"  # 9 + 43 chars
assert len(TOKEN) == 52


def make_config(**overrides) -> AgentConfig:
    kwargs = dict(agent_id=AGENT_ID, token=TOKEN, server_url="https://nova.example.com")
    kwargs.update(overrides)
    return AgentConfig.create(**kwargs)


def registered_msg(**overrides) -> dict:
    msg = {
        "type": "registered", "protocol_version": 1, "agent_id": AGENT_ID,
        "connection_id": str(uuid.uuid4()), "heartbeat_interval_seconds": 0.03,
        "heartbeat_timeout_seconds": 0.2, "server_time": "2026-11-05T07:00:00+00:00",
    }
    msg.update(overrides)
    return msg


class FakeTransport:
    """Behaves like the Transport interface. ``on_send`` plays the backend."""

    def __init__(self, on_send=None):
        self.sent: list[dict | str] = []
        self.raw_sent: list[str] = []
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.closed_with: tuple[int, str] | None = None
        self.on_send = on_send
        self.dead = False

    # -- Transport interface --
    async def send(self, text: str) -> None:
        if self.dead or self.closed_with is not None:
            raise TransportClosed(1006)
        self.raw_sent.append(text)
        msg = json.loads(text)
        self.sent.append(msg)
        if self.on_send:
            self.on_send(self, msg)

    async def recv(self):
        item = await self.inbox.get()
        if isinstance(item, BaseException):
            raise item
        return item

    async def close(self, code: int = 1000, reason: str = "") -> None:
        if self.closed_with is None:
            self.closed_with = (code, reason)
            self.inbox.put_nowait(TransportClosed(code))

    # -- helpers for tests --
    def push(self, msg) -> None:
        self.inbox.put_nowait(json.dumps(msg) if isinstance(msg, dict) else msg)

    def server_close(self, code: int) -> None:
        self.inbox.put_nowait(TransportClosed(code))


def backend(*, reg=None, ack=True, ack_seq_offset=0, close_after_acks=None,
            close_code=1006, ack_extra=None):
    """Factory for an ``on_send`` that mimics the Phase A backend."""
    state = {"acks": 0}

    def on_send(t: FakeTransport, msg: dict) -> None:
        if msg["type"] == "auth":
            t.push(reg if reg is not None else registered_msg())
        elif msg["type"] == "heartbeat" and ack:
            body = {"type": "heartbeat_ack", "seq": msg["seq"] + ack_seq_offset,
                    "server_time": "2026-11-05T07:00:01+00:00"}
            body.update(ack_extra or {})
            t.push(body)
            state["acks"] += 1
            if close_after_acks is not None and state["acks"] >= close_after_acks:
                t.server_close(close_code)

    return on_send


class FakeConnector:
    """Hands out scripted behaviours per connection attempt."""

    def __init__(self, script, on_exhausted=None):
        self.script = list(script)
        self.urls: list[str] = []
        self.on_exhausted = on_exhausted

    async def __call__(self, url: str):
        self.urls.append(url)
        if not self.script:
            if self.on_exhausted:
                self.on_exhausted()
            raise ConnectFailed("script exhausted")
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item() if callable(item) else item


def rejected(status=403):
    return HandshakeRejected(status)


async def wait_until(predicate, timeout=3.0, step=0.005):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(step)
