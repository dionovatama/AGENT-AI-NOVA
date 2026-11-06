import json
import unittest
import uuid
from unittest.mock import AsyncMock

from nova_agent.client import AgentClient, _SessionState
from nova_agent.config import AgentConfig
from nova_agent.protocol import ServerError, ProtocolViolation


TOKEN = "nova_agt_" + ("A" * 43)


def make_client():
    agent_id = str(uuid.uuid4())
    cfg = AgentConfig.create(agent_id, TOKEN, "https://nova.example.com")
    return AgentClient(cfg)


class RelayDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_standard_server_error_still_uses_reconnect_error_path(self):
        client = make_client()
        transport = AsyncMock()
        st = _SessionState()

        with self.assertRaises(ServerError) as ctx:
            await client._dispatch_relay_message(
                transport,
                json.dumps({"type": "error", "code": "RATE_LIMITED", "message": "slow down"}),
                st,
            )

        self.assertEqual(ctx.exception.code, "RATE_LIMITED")
        transport.send.assert_not_awaited()

    async def test_stale_close_and_data_are_ignored(self):
        client = make_client()
        transport = AsyncMock()
        st = _SessionState()
        stale = str(uuid.uuid4())

        await client._dispatch_relay_message(
            transport,
            json.dumps({"type": "CLOSE_TUNNEL", "session_id": stale, "reason": "requested"}),
            st,
        )
        await client._dispatch_relay_message(
            transport,
            json.dumps({
                "type": "DATA",
                "session_id": stale,
                "seq": 1,
                "data": "eA==",
            }),
            st,
        )

        self.assertEqual(st.relay_sessions, set())
        transport.send.assert_not_awaited()

    async def test_unknown_non_relay_message_is_ignored(self):
        client = make_client()
        transport = AsyncMock()
        st = _SessionState()

        await client._dispatch_relay_message(
            transport,
            json.dumps({"type": "future_message", "value": "ignored"}),
            st,
        )

        transport.send.assert_not_awaited()

    async def test_open_tunnel_still_returns_phase4_unavailable_error(self):
        client = make_client()
        transport = AsyncMock()
        st = _SessionState()
        request_id, session_id, target_id = map(str, (uuid.uuid4(), uuid.uuid4(), uuid.uuid4()))

        await client._dispatch_relay_message(
            transport,
            json.dumps({
                "type": "OPEN_TUNNEL",
                "request_id": request_id,
                "session_id": session_id,
                "target_id": target_id,
                "port": 8728,
            }),
            st,
        )

        payload = json.loads(transport.send.await_args.args[0])
        self.assertEqual(payload["type"], "TUNNEL_ERROR")
        self.assertEqual(payload["request_id"], request_id)
        self.assertEqual(payload["session_id"], session_id)
        self.assertNotIn(session_id, st.relay_sessions)


if __name__ == "__main__":
    unittest.main()
