import asyncio
import base64
import json
import unittest
import uuid

from nova_agent.config import AgentConfig, ConfigError, save_config
from nova_agent.relay_policy import (
    AllowList, RelayTarget, TargetConfigError, address_allowed, parse_relay_targets,
)
from nova_agent.relay_protocol import RelayCommand
from nova_agent.tcp_relay import RelayLimits, TcpRelayManager

TOKEN = "nova_agt_" + ("A" * 43)


def uid() -> str:
    return str(uuid.uuid4())


class Collector:
    def __init__(self):
        self.frames: list[dict] = []
        self._event = asyncio.Event()

    async def __call__(self, frame: dict) -> None:
        self.frames.append(frame)
        self._event.set()

    async def wait_for(self, pred, timeout=3.0):
        async def _w():
            while True:
                for f in self.frames:
                    if pred(f):
                        return f
                self._event.clear()
                await self._event.wait()
        return await asyncio.wait_for(_w(), timeout)


def open_cmd(target_id, port, session_id=None):
    return RelayCommand("OPEN_TUNNEL", request_id=uid(), session_id=session_id or uid(),
                        target_id=target_id, port=port)


class PolicyTests(unittest.TestCase):
    def test_parse_valid(self):
        t = parse_relay_targets([{"target_id": uid(), "host": "192.168.88.1", "ports": [8729]},
                                 {"target_id": uid(), "host": "router.lan", "ports": [8728, 8729]}])
        self.assertEqual(len(t), 2)
        self.assertEqual(t[1].ports, frozenset({8728, 8729}))

    def test_parse_rejects_bad(self):
        good = {"target_id": uid(), "host": "10.0.0.1", "ports": [22]}
        bad = [
            "x", [1], [{**good, "target_id": "nope"}], [{**good, "host": "bad host!"}],
            [{**good, "host": "http://x"}], [{**good, "ports": []}], [{**good, "ports": [0]}],
            [{**good, "ports": [70000]}], [{**good, "ports": [True]}], [{**good, "ports": "22"}],
            [{**good, "allow_loopback": "yes"}], [good, good],
        ]
        for case in bad:
            with self.assertRaises(TargetConfigError, msg=repr(case)):
                parse_relay_targets(case)

    def test_address_policy(self):
        for bad in ("0.0.0.0", "::", "224.0.0.1", "169.254.169.254", "fe80::1", "240.0.0.1",
                    "127.0.0.1", "::1", "::ffff:127.0.0.1", "::ffff:169.254.169.254", "garbage"):
            self.assertFalse(address_allowed(bad, allow_loopback=False), bad)
        for ok in ("192.168.88.1", "10.1.2.3", "172.16.0.5", "8.8.8.8"):
            self.assertTrue(address_allowed(ok, allow_loopback=False), ok)
        self.assertTrue(address_allowed("127.0.0.1", allow_loopback=True))
        self.assertFalse(address_allowed("169.254.169.254", allow_loopback=True))

    def test_config_roundtrip(self):
        import tempfile, pathlib
        tid = uid()
        cfg = AgentConfig.create(uid(), TOKEN, "https://nova.example.com",
                                 relay_targets=[{"target_id": tid, "host": "10.0.0.1", "ports": [8729]}])
        with tempfile.TemporaryDirectory() as d:
            path = save_config(cfg, pathlib.Path(d) / "config.json")
            loaded = AgentConfig.load(path)
        self.assertEqual(loaded.relay_targets, cfg.relay_targets)

    def test_config_rejects_bad_targets(self):
        with self.assertRaises(ConfigError):
            AgentConfig.create(uid(), TOKEN, "https://nova.example.com",
                               relay_targets=[{"target_id": "x", "host": "a", "ports": [1]}])


class TcpRelayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.received: list[bytes] = []
        self.server_writers: list[asyncio.StreamWriter] = []

        async def handler(reader, writer):
            self.server_writers.append(writer)
            try:
                while data := await reader.read(65536):
                    self.received.append(data)
                    writer.write(data.upper())
                    await writer.drain()
            finally:
                writer.close()

        self.server = await asyncio.start_server(handler, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        self.target_id = uid()
        self.out = Collector()
        self.managers: list[TcpRelayManager] = []

    async def asyncTearDown(self):
        for m in self.managers:
            await m.close_all()
        self.server.close()
        await self.server.wait_closed()

    def make(self, *, loopback=True, ports=None, resolver=None, limits=None, host="127.0.0.1"):
        target = RelayTarget(self.target_id, host, frozenset(ports or [self.port]), loopback)
        mgr = TcpRelayManager(AllowList((target,), resolver), self.out, limits)
        self.managers.append(mgr)
        return mgr

    async def test_roundtrip_and_backend_close(self):
        mgr = self.make()
        cmd = open_cmd(self.target_id, self.port)
        await mgr.open(cmd)
        opened = await self.out.wait_for(lambda f: f["type"] == "TUNNEL_OPENED")
        self.assertEqual(opened["session_id"], cmd.session_id)
        mgr.feed(cmd.session_id, 1, b"hello")
        data = await self.out.wait_for(lambda f: f["type"] == "DATA")
        self.assertEqual(base64.b64decode(data["data"]), b"HELLO")
        self.assertEqual(self.received, [b"hello"])
        mgr.close(cmd.session_id)
        for _ in range(50):
            if mgr.active_sessions == 0:
                break
            await asyncio.sleep(0.02)
        self.assertEqual(mgr.active_sessions, 0)
        self.assertFalse(any(f["type"] == "CLOSE_TUNNEL" for f in self.out.frames))  # no echo

    async def test_unknown_target_denied(self):
        mgr = self.make()
        await mgr.open(open_cmd(uid(), self.port))
        err = await self.out.wait_for(lambda f: f["type"] == "TUNNEL_ERROR")
        self.assertEqual(err["code"], "TARGET_NOT_ALLOWED")

    async def test_port_not_in_list_denied(self):
        mgr = self.make()
        await mgr.open(open_cmd(self.target_id, self.port + 1))
        err = await self.out.wait_for(lambda f: f["type"] == "TUNNEL_ERROR")
        self.assertEqual(err["code"], "TARGET_NOT_ALLOWED")
        self.assertEqual(self.received, [])

    async def test_loopback_denied_without_flag(self):
        mgr = self.make(loopback=False)
        await mgr.open(open_cmd(self.target_id, self.port))
        err = await self.out.wait_for(lambda f: f["type"] == "TUNNEL_ERROR")
        self.assertEqual(err["code"], "TARGET_NOT_ALLOWED")
        self.assertEqual(self.server_writers, [])

    async def test_dns_to_forbidden_address_denied(self):
        async def evil(host, port):
            return ["192.168.1.1", "169.254.169.254"]  # one bad address poisons the target
        mgr = self.make(host="router.lan", resolver=evil, loopback=False)
        await mgr.open(open_cmd(self.target_id, self.port))
        err = await self.out.wait_for(lambda f: f["type"] == "TUNNEL_ERROR")
        self.assertEqual(err["code"], "TARGET_NOT_ALLOWED")

    async def test_dns_failure_is_unavailable(self):
        async def broken(host, port):
            raise OSError("nxdomain secret-detail")
        mgr = self.make(host="router.lan", resolver=broken)
        await mgr.open(open_cmd(self.target_id, self.port))
        err = await self.out.wait_for(lambda f: f["type"] == "TUNNEL_ERROR")
        self.assertEqual(err["code"], "TARGET_UNAVAILABLE")
        self.assertNotIn("secret", json.dumps(err))

    async def test_connect_refused(self):
        s = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
        dead_port = s.sockets[0].getsockname()[1]
        s.close(); await s.wait_closed()
        mgr = self.make(ports=[dead_port])
        await mgr.open(open_cmd(self.target_id, dead_port))
        err = await self.out.wait_for(lambda f: f["type"] == "TUNNEL_ERROR")
        self.assertEqual(err["code"], "CONNECT_FAILED")
        self.assertEqual(mgr.active_sessions, 0)

    async def test_connect_timeout(self):
        async def slow(host, port):
            await asyncio.sleep(10)
        mgr = self.make(host="router.lan", resolver=slow, limits=RelayLimits(resolve_timeout=0.1))
        await mgr.open(open_cmd(self.target_id, self.port))
        err = await self.out.wait_for(lambda f: f["type"] == "TUNNEL_ERROR")
        self.assertEqual(err["code"], "TIMEOUT")

    async def test_session_limit(self):
        mgr = self.make(limits=RelayLimits(max_sessions=1))
        first = open_cmd(self.target_id, self.port)
        await mgr.open(first)
        await self.out.wait_for(lambda f: f["type"] == "TUNNEL_OPENED")
        second = open_cmd(self.target_id, self.port)
        await mgr.open(second)
        err = await self.out.wait_for(lambda f: f["type"] == "TUNNEL_ERROR")
        self.assertEqual(err["code"], "RESOURCE_LIMIT")
        self.assertEqual(err["session_id"], second.session_id)

    async def test_duplicate_session_id_rejected(self):
        mgr = self.make()
        first = open_cmd(self.target_id, self.port)
        await mgr.open(first)
        await self.out.wait_for(lambda f: f["type"] == "TUNNEL_OPENED")
        await mgr.open(open_cmd(self.target_id, self.port, session_id=first.session_id))
        err = await self.out.wait_for(lambda f: f["type"] == "TUNNEL_ERROR")
        self.assertEqual(err["code"], "PROTOCOL_ERROR")
        self.assertEqual(mgr.active_sessions, 1)

    async def test_device_closes_sends_close_tunnel(self):
        mgr = self.make()
        cmd = open_cmd(self.target_id, self.port)
        await mgr.open(cmd)
        await self.out.wait_for(lambda f: f["type"] == "TUNNEL_OPENED")
        self.server_writers[0].close()
        close = await self.out.wait_for(lambda f: f["type"] == "CLOSE_TUNNEL")
        self.assertEqual(close["reason"], "peer_closed")
        self.assertEqual(close["session_id"], cmd.session_id)
        await asyncio.sleep(0.05)
        self.assertEqual(mgr.active_sessions, 0)

    async def test_idle_timeout(self):
        mgr = self.make(limits=RelayLimits(idle_timeout=0.2))
        await mgr.open(open_cmd(self.target_id, self.port))
        close = await self.out.wait_for(lambda f: f["type"] == "CLOSE_TUNNEL")
        self.assertEqual(close["reason"], "timeout")

    async def test_non_monotonic_seq_closes(self):
        mgr = self.make()
        cmd = open_cmd(self.target_id, self.port)
        await mgr.open(cmd)
        await self.out.wait_for(lambda f: f["type"] == "TUNNEL_OPENED")
        mgr.feed(cmd.session_id, 5, b"a")
        mgr.feed(cmd.session_id, 5, b"b")
        close = await self.out.wait_for(lambda f: f["type"] == "CLOSE_TUNNEL")
        self.assertEqual(close["reason"], "error")

    async def test_stale_frames_ignored(self):
        mgr = self.make()
        mgr.feed(uid(), 1, b"x")
        mgr.close(uid())
        self.assertEqual(self.out.frames, [])

    async def test_close_all_drops_sockets_silently(self):
        mgr = self.make()
        for _ in range(3):
            await mgr.open(open_cmd(self.target_id, self.port))
        for _ in range(3):
            await self.out.wait_for(lambda f: f["type"] == "TUNNEL_OPENED")
        await mgr.close_all()
        self.assertEqual(mgr.active_sessions, 0)
        self.assertFalse(any(f["type"] == "CLOSE_TUNNEL" for f in self.out.frames))

    async def test_large_stream_chunked_within_frame_limit(self):
        mgr = self.make()
        cmd = open_cmd(self.target_id, self.port)
        await mgr.open(cmd)
        await self.out.wait_for(lambda f: f["type"] == "TUNNEL_OPENED")
        payload = b"a" * 100_000
        for i in range(0, len(payload), 30_000):
            mgr.feed(cmd.session_id, i + 1, payload[i:i + 30_000])
        async def total():
            while sum(len(base64.b64decode(f["data"])) for f in self.out.frames
                      if f["type"] == "DATA") < len(payload):
                await asyncio.sleep(0.02)
        await asyncio.wait_for(total(), 3)
        for f in self.out.frames:
            if f["type"] == "DATA":
                self.assertLessEqual(len(base64.b64decode(f["data"])), 32 * 1024)


class ClientDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatch_uses_relay_manager_end_to_end(self):
        from unittest.mock import AsyncMock
        from nova_agent.client import AgentClient, _SessionState

        async def echo(reader, writer):
            writer.write(await reader.read(100)); await writer.drain(); writer.close()
        server = await asyncio.start_server(echo, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        tid = uid()
        cfg = AgentConfig.create(uid(), TOKEN, "https://nova.example.com", relay_targets=[
            {"target_id": tid, "host": "127.0.0.1", "ports": [port], "allow_loopback": True}])
        client = AgentClient(cfg)
        out = Collector()
        st = _SessionState()
        st.relay = TcpRelayManager(AllowList(cfg.relay_targets), out)
        transport = AsyncMock()
        sid = uid()
        try:
            await client._dispatch_relay_message(transport, json.dumps({
                "type": "OPEN_TUNNEL", "request_id": uid(), "session_id": sid,
                "target_id": tid, "port": port}), st)
            await out.wait_for(lambda f: f["type"] == "TUNNEL_OPENED")
            await client._dispatch_relay_message(transport, json.dumps({
                "type": "DATA", "session_id": sid, "seq": 1, "data": "aGk="}), st)
            data = await out.wait_for(lambda f: f["type"] == "DATA")
            self.assertEqual(base64.b64decode(data["data"]), b"hi")
            transport.send.assert_not_awaited()
        finally:
            await st.relay.close_all()
            server.close(); await server.wait_closed()


if __name__ == "__main__":
    unittest.main()
