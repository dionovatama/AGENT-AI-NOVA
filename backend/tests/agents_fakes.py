"""
Test double untuk logika koneksi Agent (bukan test itu sendiri).

FakeStore meniru semantik KONDISIONAL implementasi SQL (hanya pemilik
connection_id yang boleh menulis) dan sengaja 'yield' (asyncio.sleep(0))
di tiap operasi supaya interleaving antar-task -- penyebab race nyata --
benar-benar terjadi dalam test.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

from app.agents.protocol import SocketClosed
from app.agents.store import AuthRecord, ClaimResult
from app.agents.tokens import generate_agent_token, hash_agent_token

LIVE = ("connecting", "online")


class FakeStore:
    def __init__(self) -> None:
        self.agents: dict[uuid.UUID, dict] = {}
        self.fail_on: set[str] = set()
        self.calls: list[str] = []

    # ---- helper test ----
    def add_agent(self, owner_active: bool = True) -> tuple[uuid.UUID, str]:
        agent_id = uuid.uuid4()
        token = generate_agent_token()
        self.agents[agent_id] = {
            "owner_id": uuid.uuid4(), "owner_active": owner_active,
            "token_hash": hash_agent_token(token), "status": "offline",
            "connection_id": None, "worker_id": None, "os": None,
            "agent_version": None, "last_heartbeat_at": None,
            "last_connected_at": None, "last_disconnected_at": None,
            "last_error": None,
        }
        return agent_id, token

    def row(self, agent_id: uuid.UUID) -> dict:
        return self.agents[agent_id]

    async def _enter(self, name: str) -> None:
        self.calls.append(name)
        await asyncio.sleep(0)
        if name in self.fail_on:
            raise RuntimeError(f"simulated store failure in {name}")

    # ---- AgentStore ----
    async def get_auth_record(self, agent_id):
        await self._enter("get_auth_record")
        r = self.agents.get(agent_id)
        if r is None:
            return None
        return AuthRecord(agent_id, r["owner_id"], r["token_hash"], r["owner_active"])

    async def claim_connection(self, agent_id, connection_id, worker_id, os, agent_version, now):
        await self._enter("claim_connection")
        r = self.agents.get(agent_id)
        if r is None:
            return ClaimResult(False)
        was_live = r["status"] in LIVE
        replaced = (r["connection_id"], r["worker_id"]) if was_live else (None, None)
        r.update(status="connecting", connection_id=connection_id, worker_id=worker_id,
                 os=os, agent_version=agent_version, last_heartbeat_at=now,
                 last_connected_at=now, last_error=None)
        return ClaimResult(True, replaced[0], replaced[1])

    def _owned(self, agent_id, connection_id):
        r = self.agents.get(agent_id)
        return r if r is not None and r["connection_id"] == connection_id else None

    async def mark_online(self, agent_id, connection_id, now):
        await self._enter("mark_online")
        r = self._owned(agent_id, connection_id)
        if r is None:
            return False
        r["status"] = "online"
        return True

    async def record_heartbeat(self, agent_id, connection_id, now):
        await self._enter("record_heartbeat")
        r = self._owned(agent_id, connection_id)
        if r is None:
            return False
        r["last_heartbeat_at"] = now
        r["status"] = "online"
        return True

    async def release_connection(self, agent_id, connection_id, status, now, error=None):
        await self._enter("release_connection")
        r = self._owned(agent_id, connection_id)
        if r is None:
            return False
        r.update(status=status, last_disconnected_at=now, connection_id=None,
                 worker_id=None, last_error=error)
        return True

    async def mark_stale(self, cutoff, now):
        await self._enter("mark_stale")
        n = 0
        for r in self.agents.values():
            hb = r["last_heartbeat_at"]
            if r["status"] in LIVE and (hb is None or hb < cutoff):
                r.update(status="disconnected", last_disconnected_at=now)
                n += 1
        return n


class FakeSocket:
    def __init__(self, secure: bool = True, ip: str = "203.0.113.7") -> None:
        self.is_secure = secure
        self.client_ip = ip
        self.accepted = False
        self.closed: tuple[int, str] | None = None
        self.sent: list[dict] = []
        self._inbox: asyncio.Queue = asyncio.Queue()

    async def accept(self) -> None:
        self.accepted = True

    async def receive_text(self, timeout: float) -> str:
        item = await asyncio.wait_for(self._inbox.get(), timeout)
        if isinstance(item, BaseException):
            raise item
        return item

    async def send_json(self, payload: dict) -> None:
        if self.closed is not None:
            raise SocketClosed(1006)
        self.sent.append(payload)

    async def close(self, code: int, reason: str = "") -> None:
        if self.closed is None:
            self.closed = (code, reason)
            self._inbox.put_nowait(SocketClosed(code, reason))

    # ---- sisi "agent" ----
    def client_send(self, obj: dict) -> None:
        self._inbox.put_nowait(json.dumps(obj))

    def client_send_raw(self, item) -> None:
        self._inbox.put_nowait(item)

    def client_close(self, code: int = 1000) -> None:
        self._inbox.put_nowait(SocketClosed(code))


def auth_frame(token: str, **over) -> dict:
    frame = {"type": "auth", "protocol_version": 1, "token": token,
             "os": "Windows 11 x64", "agent_version": "0.1.0"}
    frame.update(over)
    return frame


async def until(predicate, timeout: float = 2.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while not predicate():
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError("kondisi tidak tercapai dalam batas waktu")
        await asyncio.sleep(0.005)


def utc(offset_seconds: float = 0) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
