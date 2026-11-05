"""Protocol compatibility: the new client against the REAL Phase A backend
connection manager (backend/app/agents/manager.py), in-process.

Only the network hop is faked (an in-memory pair of sockets) and the store is
the backend's own FakeStore from backend/tests/agents_fakes.py. Needs no
FastAPI/SQLAlchemy/PostgreSQL. Skipped when the backend tree is not present.
The real WebSocket stack (websockets + Starlette) is NOT exercised here.
"""

import asyncio
import importlib.util
import json
import sys
import unittest
from pathlib import Path

from nova_agent import __version__
from nova_agent.client import SLOW_BASE, AgentClient, ExitReason
from nova_agent.config import AgentConfig
from nova_agent.transport import TransportClosed
from tests.helpers import wait_until

BACKEND = Path(__file__).resolve().parents[2] / "backend"
AVAILABLE = (BACKEND / "app" / "agents" / "manager.py").exists() and \
            (BACKEND / "tests" / "agents_fakes.py").exists()

if AVAILABLE:
    sys.path.insert(0, str(BACKEND))
    from app.agents.manager import AgentConnectionManager, AgentRuntimeConfig  # noqa: E402
    from app.agents.protocol import SocketClosed  # noqa: E402

    _spec = importlib.util.spec_from_file_location(
        "backend_agents_fakes", BACKEND / "tests" / "agents_fakes.py")
    _fakes = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_fakes)
    FakeStore = _fakes.FakeStore


class _ClientEnd:
    """Client-side Transport bound to a backend-side socket."""

    def __init__(self, backend_sock):
        self._b = backend_sock
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.closed = False

    async def send(self, text):
        if self.closed or self._b.closed is not None:
            raise TransportClosed(1006)
        self._b._inbox.put_nowait(text)

    async def recv(self):
        item = await self.inbox.get()
        if isinstance(item, BaseException):
            raise item
        return item

    async def close(self, code=1000, reason=""):
        if not self.closed:
            self.closed = True
            self._b._inbox.put_nowait(SocketClosed(code, reason))
            self.inbox.put_nowait(TransportClosed(code))


def _make_backend_socket(client_end_holder):
    base = _fakes.FakeSocket

    class BridgedSocket(base):
        async def send_json(self, payload):
            await base.send_json(self, payload)
            client_end_holder["end"].inbox.put_nowait(json.dumps(payload))

        async def close(self, code, reason=""):
            first = self.closed is None
            await base.close(self, code, reason)
            if first:
                client_end_holder["end"].inbox.put_nowait(TransportClosed(code, reason))

    return BridgedSocket()


@unittest.skipUnless(AVAILABLE, "backend tree not available")
class RealBackendCompatTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = FakeStore()
        self.manager = AgentConnectionManager(
            store=self.store,
            cfg=AgentRuntimeConfig(
                heartbeat_interval_seconds=0.2, heartbeat_timeout_seconds=2.0,
                heartbeat_min_db_interval_seconds=0.0, max_messages_per_window=1000,
                require_tls=True),
            worker_id="test-worker",
        )
        self.handler_tasks: list[asyncio.Task] = []
        self.sockets = []
        self.agent_id, self.token = self.store.add_agent()

    async def asyncTearDown(self):
        for task in self.handler_tasks:
            task.cancel()
        await asyncio.gather(*self.handler_tasks, return_exceptions=True)

    def connector_for(self, agent_id):
        async def connect(url):
            self.assertEqual(url, f"wss://nova.example.com/ws/agent/{agent_id}")
            holder = {}
            sock = _make_backend_socket(holder)  # is_secure=True by default
            end = _ClientEnd(sock)
            holder["end"] = end
            self.sockets.append(sock)
            self.handler_tasks.append(asyncio.create_task(self.manager.handle(sock, str(agent_id))))
            return end
        return connect

    def client(self, agent_id=None, token=None, delays=None, **kw):
        agent_id = agent_id or self.agent_id
        cfg = AgentConfig.create(str(agent_id), token or self.token, "https://nova.example.com")
        delays = [] if delays is None else delays

        async def sleeper(delay):
            delays.append(delay)
            return True  # do not actually wait; ends the run loop

        return AgentClient(cfg, connector=self.connector_for(agent_id), sleeper=sleeper,
                           rng=lambda: 0.0, os_name="Windows 11 x64",
                           min_heartbeat_interval=0.01, min_ack_timeout=0.05, **kw)

    async def test_full_lifecycle_register_heartbeat_bye(self):
        client = self.client()
        task = asyncio.create_task(client.run())
        row = self.store.row(self.agent_id)
        await wait_until(lambda: row["status"] == "online")
        self.assertEqual(row["os"], "Windows 11 x64")
        self.assertEqual(row["agent_version"], __version__)
        # several validated heartbeat/ACK round trips against the real manager
        await wait_until(lambda: self.store.calls.count("record_heartbeat") >= 3, timeout=5)
        client.request_stop()
        self.assertEqual(await asyncio.wait_for(task, 5), ExitReason.STOPPED)
        await wait_until(lambda: row["status"] != "online")
        self.assertEqual(row["status"], "offline")  # 'bye' -> offline, not 'disconnected'
        self.assertEqual(self.sockets[0].closed[0], 1000)

    async def test_wrong_token_gets_4401_and_agent_stops_retrying(self):
        from app.agents.tokens import generate_agent_token
        client = self.client(token=generate_agent_token())
        self.assertEqual(await asyncio.wait_for(client.run(), 5), ExitReason.AUTH_FAILED)
        self.assertEqual(self.sockets[0].closed[0], 4401)
        self.assertEqual(len(self.sockets), 1)
        self.assertIsNone(self.store.row(self.agent_id)["connection_id"])

    async def test_unknown_agent_gets_4401(self):
        import uuid
        client = self.client(agent_id=uuid.uuid4())
        self.assertEqual(await asyncio.wait_for(client.run(), 5), ExitReason.AUTH_FAILED)
        self.assertEqual(self.sockets[0].closed[0], 4401)

    async def test_token_rotation_revokes_connection_with_4009_then_slow_retry(self):
        delays = []
        client = self.client(delays=delays)
        task = asyncio.create_task(client.run())
        row = self.store.row(self.agent_id)
        await wait_until(lambda: row["status"] == "online")
        self.store.rotate_token(self.agent_id)  # REST rotate-token
        # next heartbeat -> record_heartbeat False -> backend closes 4009
        self.assertEqual(await asyncio.wait_for(task, 5), ExitReason.STOPPED)  # fake sleeper stops loop
        self.assertEqual(self.sockets[0].closed[0], 4009)
        self.assertEqual(len(delays), 1)
        self.assertGreaterEqual(delays[0], SLOW_BASE)

    async def test_second_instance_with_same_credentials_replaces_first(self):
        first_delays = []
        first = self.client(delays=first_delays)
        first_task = asyncio.create_task(first.run())
        row = self.store.row(self.agent_id)
        await wait_until(lambda: row["status"] == "online")

        second = self.client()
        second_task = asyncio.create_task(second.run())
        # first instance is evicted with 4009 and must back off slowly
        await asyncio.wait_for(first_task, 5)
        self.assertEqual(self.sockets[0].closed[0], 4009)
        self.assertGreaterEqual(first_delays[0], SLOW_BASE)
        # second instance stays connected
        await wait_until(lambda: self.store.row(self.agent_id)["status"] == "online")
        self.assertFalse(second_task.done())
        second.request_stop()
        self.assertEqual(await asyncio.wait_for(second_task, 5), ExitReason.STOPPED)


if __name__ == "__main__":
    unittest.main()
