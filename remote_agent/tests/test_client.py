import asyncio
import logging
import unittest

from nova_agent import __version__
from nova_agent.client import (
    AgentClient, Backoff, ExitReason, REPEAT_LIMITS, SLOW_BASE, decide_close,
)
from nova_agent.transport import ConnectFailed, TransportClosed
from tests.helpers import (
    AGENT_ID, TOKEN, FakeConnector, FakeTransport, backend, make_config, registered_msg,
    rejected, wait_until,
)


def make_client(connector, *, delays=None, stop_after=None, **kw):
    """Client with tiny timings. The fake sleeper records delays and returns
    immediately; after ``stop_after`` sleeps it reports 'stop requested'."""
    delays = [] if delays is None else delays
    holder = {}

    async def sleeper(delay):
        delays.append(delay)
        return stop_after is not None and len(delays) >= stop_after

    params = dict(connector=connector, sleeper=sleeper, rng=lambda: 0.0, os_name="Windows 11 x64",
                  register_timeout=0.3, min_heartbeat_interval=0.01, min_ack_timeout=0.05,
                  bye_timeout=0.5, close_timeout=0.5)
    params.update(kw)
    client = AgentClient(make_config(), **params)
    holder["client"] = client
    return client


async def run(client, timeout=5.0):
    return await asyncio.wait_for(client.run(), timeout)


class NoStrayTasks:
    def assert_clean(self):
        leftover = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        assert not leftover, f"stray tasks: {leftover}"


class SessionTests(unittest.IsolatedAsyncioTestCase, NoStrayTasks):
    async def test_auth_frame_url_and_heartbeat_sequence_then_graceful_stop(self):
        t = FakeTransport(on_send=backend())
        conn = FakeConnector([t])
        client = make_client(conn)
        task = asyncio.create_task(client.run())
        await wait_until(lambda: len([m for m in t.sent if m["type"] == "heartbeat"]) >= 4)
        client.request_stop()
        self.assertEqual(await asyncio.wait_for(task, 5), ExitReason.STOPPED)

        # URL: Phase A endpoint, no token anywhere in it
        self.assertEqual(conn.urls, [f"wss://nova.example.com/ws/agent/{AGENT_ID}"])
        self.assertNotIn(TOKEN, conn.urls[0])
        # first frame is auth with the right fields
        self.assertEqual(t.sent[0], {"type": "auth", "protocol_version": 1, "token": TOKEN,
                                     "os": "Windows 11 x64", "agent_version": __version__})
        # heartbeats are 1, 2, 3 ...
        seqs = [m["seq"] for m in t.sent if m["type"] == "heartbeat"]
        self.assertEqual(seqs, list(range(1, len(seqs) + 1)))
        # graceful shutdown: bye is the last frame, close is normal (1000)
        self.assertEqual(t.sent[-1], {"type": "bye"})
        self.assertEqual(t.closed_with[0], 1000)
        self.assert_clean()

    async def test_stop_before_registration_closes_without_bye(self):
        t = FakeTransport()  # never answers auth
        client = make_client(FakeConnector([t]), register_timeout=5)
        task = asyncio.create_task(client.run())
        await wait_until(lambda: t.sent)
        client.request_stop()
        self.assertEqual(await asyncio.wait_for(task, 5), ExitReason.STOPPED)
        self.assertEqual([m["type"] for m in t.sent], ["auth"])
        self.assertEqual(t.closed_with[0], 1000)
        self.assert_clean()

    async def test_stop_while_connecting_is_prompt(self):
        gate = asyncio.Event()

        async def hanging_connector(url):
            await gate.wait()

        client = make_client(hanging_connector)
        task = asyncio.create_task(client.run())
        await asyncio.sleep(0.02)
        client.request_stop()
        self.assertEqual(await asyncio.wait_for(task, 2), ExitReason.STOPPED)
        self.assert_clean()

    async def test_stop_during_backoff_wakes_immediately(self):
        client = AgentClient(make_config(), connector=FakeConnector([ConnectFailed("x")]),
                             rng=lambda: 0.0)  # real interruptible sleeper, 2s backoff
        task = asyncio.create_task(client.run())
        await asyncio.sleep(0.05)
        client.request_stop()
        loop = asyncio.get_running_loop()
        started = loop.time()
        self.assertEqual(await asyncio.wait_for(task, 1), ExitReason.STOPPED)
        self.assertLess(loop.time() - started, 0.5)
        self.assert_clean()

    async def test_stop_after_peer_already_closed_does_not_send_bye(self):
        t = FakeTransport(on_send=backend(close_after_acks=1, close_code=1006))
        client = make_client(FakeConnector([t]), stop_after=1)
        self.assertEqual(await run(client), ExitReason.STOPPED)
        self.assertNotIn({"type": "bye"}, t.sent)


class HeartbeatTests(unittest.IsolatedAsyncioTestCase, NoStrayTasks):
    async def test_ack_seq_mismatch_drops_session_and_reconnects(self):
        t = FakeTransport(on_send=backend(ack_seq_offset=1))
        delays = []
        client = make_client(FakeConnector([t]), delays=delays, stop_after=1)
        self.assertEqual(await run(client), ExitReason.STOPPED)
        self.assertEqual(t.closed_with[0], 1002)  # protocol error close
        self.assertEqual(delays, [2.0])           # normal backoff, not slow
        self.assert_clean()

    async def test_ack_timeout_uses_server_timeout_and_closes_4408(self):
        # interval .03, timeout .2  ->  ack deadline = max(.17, min_ack .05)
        t = FakeTransport(on_send=backend(ack=False))
        delays = []
        client = make_client(FakeConnector([t]), delays=delays, stop_after=1)
        loop = asyncio.get_running_loop()
        started = loop.time()
        await run(client)
        elapsed = loop.time() - started
        self.assertEqual(t.closed_with[0], 4408)
        self.assertGreaterEqual(elapsed, 0.15)
        self.assertLess(elapsed, 1.0)
        self.assertEqual(delays, [2.0])

    async def test_missing_seq_in_ack_is_mismatch(self):
        def on_send(tr, msg):
            if msg["type"] == "auth":
                tr.push(registered_msg())
            else:
                tr.push({"type": "heartbeat_ack", "seq": None, "server_time": "x"})
        t = FakeTransport(on_send=on_send)
        client = make_client(FakeConnector([t]), stop_after=1)
        await run(client)
        self.assertEqual(t.closed_with[0], 1002)

    async def test_unknown_server_message_is_ignored(self):
        def on_send(tr, msg):
            if msg["type"] == "auth":
                tr.push(registered_msg())
            elif msg["type"] == "heartbeat":
                tr.push({"type": "something_new", "x": 1})
                tr.push({"type": "heartbeat_ack", "seq": msg["seq"], "server_time": "t"})
        t = FakeTransport(on_send=on_send)
        client = make_client(FakeConnector([t]))
        task = asyncio.create_task(client.run())
        await wait_until(lambda: len(t.sent) >= 4)
        client.request_stop()
        await asyncio.wait_for(task, 5)
        self.assertEqual(t.sent[-1], {"type": "bye"})


class MalformedTrafficTests(unittest.IsolatedAsyncioTestCase, NoStrayTasks):
    async def _expect_failure(self, on_send):
        t = FakeTransport(on_send=on_send)
        delays = []
        client = make_client(FakeConnector([t]), delays=delays, stop_after=1)
        self.assertEqual(await run(client), ExitReason.STOPPED)
        self.assertEqual(t.closed_with[0], 1002)
        self.assertEqual(delays, [2.0])
        self.assert_clean()
        return t

    async def test_invalid_json_instead_of_registered(self):
        await self._expect_failure(lambda tr, m: tr.push("{{{ not json"))

    async def test_binary_frame_instead_of_registered(self):
        await self._expect_failure(lambda tr, m: tr.push(b"\x00\x01"))

    async def test_registered_for_another_agent(self):
        await self._expect_failure(lambda tr, m: tr.push(
            registered_msg(agent_id="11111111-2222-4333-8444-555555555555")))

    async def test_registered_with_wrong_protocol_version(self):
        await self._expect_failure(lambda tr, m: tr.push(registered_msg(protocol_version=9)))

    async def test_garbage_after_registration(self):
        def on_send(tr, msg):
            tr.push(registered_msg() if msg["type"] == "auth" else "][")
        await self._expect_failure(on_send)

    async def test_registration_timeout(self):
        t = FakeTransport()
        delays = []
        client = make_client(FakeConnector([t]), delays=delays, stop_after=1, register_timeout=0.05)
        await run(client)
        self.assertEqual(t.closed_with[0], 4408)
        self.assertEqual(delays, [2.0])

    async def test_server_error_then_close_4400_is_slow_not_fast(self):
        def on_send(tr, msg):
            tr.push({"type": "error", "code": "protocol_error", "message": "bad"})
            tr.server_close(4400)
        t = FakeTransport(on_send=on_send)
        delays = []
        client = make_client(FakeConnector([t]), delays=delays, stop_after=1)
        await run(client)
        self.assertGreaterEqual(delays[0], SLOW_BASE)


class ReconnectTests(unittest.IsolatedAsyncioTestCase, NoStrayTasks):
    async def test_exponential_backoff_with_cap(self):
        conn = FakeConnector([ConnectFailed("dns")] * 8)
        delays = []
        client = make_client(conn, delays=delays, stop_after=8)
        await run(client)
        self.assertEqual(delays, [2, 4, 8, 16, 32, 60, 60, 60])

    async def test_jitter_is_added_and_bounded(self):
        conn = FakeConnector([ConnectFailed("dns")] * 3)
        delays = []
        client = make_client(conn, delays=delays, stop_after=3, rng=lambda: 1.0)
        await run(client)
        self.assertEqual(delays, [2.5, 5.0, 10.0])  # +25% max
        b = Backoff(rng=lambda: 0.5)
        self.assertAlmostEqual(b.next(), 2 * 1.125)

    async def test_backoff_resets_after_healthy_session(self):
        healthy = lambda: FakeTransport(on_send=backend(close_after_acks=1))
        conn = FakeConnector([ConnectFailed("x"), ConnectFailed("x"), healthy,
                              ConnectFailed("x"), ConnectFailed("x")])
        delays = []
        client = make_client(conn, delays=delays, stop_after=5)
        await run(client)
        # 2, 4 (failures) -> healthy session drops -> back to 2 -> then 4
        self.assertEqual(delays, [2, 4, 2, 4, 8])

    async def test_session_that_never_got_an_ack_does_not_reset_backoff(self):
        flap = lambda: FakeTransport(on_send=lambda tr, m: (
            tr.push(registered_msg()), tr.server_close(1011)) if m["type"] == "auth" else None)
        conn = FakeConnector([flap, flap, flap])
        delays = []
        client = make_client(conn, delays=delays, stop_after=3)
        await run(client)
        self.assertEqual(delays, [2, 4, 8])

    async def test_keeps_retrying_forever_when_network_is_down(self):
        conn = FakeConnector([ConnectFailed("network down")] * 50)
        delays = []
        client = make_client(conn, delays=delays, stop_after=50)
        self.assertEqual(await run(client), ExitReason.STOPPED)
        self.assertEqual(len(delays), 50)

    async def test_http_rejection_of_handshake_is_slow(self):
        conn = FakeConnector([rejected(403), rejected(403)])
        delays = []
        client = make_client(conn, delays=delays, stop_after=2)
        await run(client)
        self.assertEqual(delays, [SLOW_BASE, SLOW_BASE * 2])

    async def test_unexpected_exception_in_connector_does_not_kill_loop(self):
        conn = FakeConnector([RuntimeError("boom"), ValueError("boom")])
        delays = []
        client = make_client(conn, delays=delays, stop_after=2)
        self.assertEqual(await run(client), ExitReason.STOPPED)
        self.assertEqual(delays, [2, 4])


def closing_after_register(code):
    """Backend that registers the agent then closes with ``code`` (no ack)."""
    def on_send(tr, msg):
        if msg["type"] == "auth":
            tr.push(registered_msg())
            tr.server_close(code)
    return lambda: FakeTransport(on_send=on_send)


class CloseCodeTests(unittest.IsolatedAsyncioTestCase, NoStrayTasks):
    async def test_4401_stops_without_reconnecting(self):
        conn = FakeConnector([closing_after_register(4401)] * 5)
        delays = []
        client = make_client(conn, delays=delays)
        self.assertEqual(await run(client), ExitReason.AUTH_FAILED)
        self.assertEqual(len(conn.urls), 1)
        self.assertEqual(delays, [])

    async def test_4401_during_auth_before_registered(self):
        def on_send(tr, msg):
            tr.server_close(4401)
        conn = FakeConnector([lambda: FakeTransport(on_send=on_send)] * 3)
        client = make_client(conn)
        self.assertEqual(await run(client), ExitReason.AUTH_FAILED)
        self.assertEqual(len(conn.urls), 1)

    async def test_4009_slow_then_gives_up_after_three(self):
        conn = FakeConnector([closing_after_register(4009)] * 6)
        delays = []
        client = make_client(conn, delays=delays)
        self.assertEqual(await run(client), ExitReason.CREDENTIAL_CONFLICT)
        self.assertEqual(len(conn.urls), 3)
        self.assertEqual(len(delays), 2)
        self.assertTrue(all(d >= SLOW_BASE for d in delays), delays)

    async def test_4429_is_slow_and_keeps_trying(self):
        conn = FakeConnector([closing_after_register(4429)] * 3)
        delays = []
        client = make_client(conn, delays=delays, stop_after=3)
        self.assertEqual(await run(client), ExitReason.STOPPED)
        self.assertEqual(delays, [SLOW_BASE, SLOW_BASE * 2, SLOW_BASE * 4])

    async def test_4400_slow_then_gives_up_after_five(self):
        conn = FakeConnector([closing_after_register(4400)] * 9)
        delays = []
        client = make_client(conn, delays=delays)
        self.assertEqual(await run(client), ExitReason.PROTOCOL_REJECTED)
        self.assertEqual(len(conn.urls), 5)
        self.assertTrue(all(d >= SLOW_BASE for d in delays))

    async def test_4408_and_1011_use_normal_backoff(self):
        for code in (4408, 1011, 1001, 1006):
            with self.subTest(code=code):
                conn = FakeConnector([closing_after_register(code)] * 2)
                delays = []
                client = make_client(conn, delays=delays, stop_after=2)
                await run(client)
                self.assertEqual(delays, [2, 4])

    async def test_policy_table(self):
        self.assertIsNotNone(decide_close(4401).fatal)
        for code in (4009, 4429, 4400, 1008, 1003, 1009):
            self.assertTrue(decide_close(code).slow, code)
        for code in (4408, 1011, 1001, 1000, 1006, 4999):
            d = decide_close(code)
            self.assertFalse(d.slow or d.fatal, code)
        self.assertIn(4009, REPEAT_LIMITS)

    async def test_repeat_counter_resets_after_stable_session(self):
        from nova_agent import client as client_mod
        old = client_mod.STABLE_SESSION_SECONDS
        client_mod.STABLE_SESSION_SECONDS = 0.0  # every session counts as stable
        self.addCleanup(setattr, client_mod, "STABLE_SESSION_SECONDS", old)
        conn = FakeConnector([closing_after_register(4009)] * 6)
        delays = []
        client = make_client(conn, delays=delays, stop_after=6)
        self.assertEqual(await run(client), ExitReason.STOPPED)  # never reaches the limit
        self.assertEqual(len(conn.urls), 6)


class SecurityTests(unittest.IsolatedAsyncioTestCase):
    async def test_token_never_logged_even_on_failures(self):
        records = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        handler = Capture(level=logging.DEBUG)
        logger = logging.getLogger("nova_agent")
        old_level = logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        try:
            script = [closing_after_register(4009), ConnectFailed("x"),
                      lambda: FakeTransport(on_send=lambda tr, m: tr.push(f"garbage {TOKEN}")),
                      closing_after_register(4401)]
            client = make_client(FakeConnector(script))
            await run(client)
        finally:
            logger.removeHandler(handler)
            logger.setLevel(old_level)
        self.assertTrue(records)
        for line in records:
            self.assertNotIn(TOKEN, line)


if __name__ == "__main__":
    unittest.main()
