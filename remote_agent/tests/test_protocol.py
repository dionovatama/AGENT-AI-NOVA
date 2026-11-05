import json
import unittest

from nova_agent.protocol import (
    BYE_MESSAGE, HeartbeatMismatch, MAX_MESSAGE_BYTES, ProtocolViolation, ServerError,
    build_auth_message, build_heartbeat_message, decode_message, normalize_os_name,
    parse_heartbeat_ack, parse_registered,
)
from tests.helpers import AGENT_ID, TOKEN, registered_msg


class AuthMessageTests(unittest.TestCase):
    def test_exact_format(self):
        msg = json.loads(build_auth_message(TOKEN, "Windows 11 x64", "0.2.0"))
        self.assertEqual(msg, {"type": "auth", "protocol_version": 1, "token": TOKEN,
                               "os": "Windows 11 x64", "agent_version": "0.2.0"})

    def test_heartbeat_and_bye(self):
        self.assertEqual(json.loads(build_heartbeat_message(7)), {"type": "heartbeat", "seq": 7})
        self.assertEqual(json.loads(BYE_MESSAGE), {"type": "bye"})

    def test_os_name_normalization_matches_backend_limits(self):
        self.assertEqual(len(normalize_os_name("x" * 200)), 50)
        self.assertEqual(normalize_os_name("Win\x00dows\n 11"), "Windows 11")
        self.assertEqual(normalize_os_name("   "), "unknown")


class RegisteredTests(unittest.TestCase):
    def parse(self, **overrides):
        return parse_registered(json.dumps(registered_msg(**overrides)), AGENT_ID)

    def test_valid(self):
        reg = self.parse(heartbeat_interval_seconds=30.0, heartbeat_timeout_seconds=90.0)
        self.assertEqual(reg.agent_id, AGENT_ID)
        self.assertEqual((reg.heartbeat_interval, reg.heartbeat_timeout), (30.0, 90.0))
        self.assertEqual(len(reg.connection_id), 36)

    def test_integer_timings_accepted(self):
        reg = self.parse(heartbeat_interval_seconds=30, heartbeat_timeout_seconds=90)
        self.assertEqual(reg.heartbeat_interval, 30.0)

    def test_agent_id_case_insensitive(self):
        self.assertEqual(self.parse(agent_id=AGENT_ID.upper()).agent_id, AGENT_ID)

    def test_rejections(self):
        cases = {
            "wrong version": dict(protocol_version=2),
            "bool version": dict(protocol_version=True),
            "missing version": dict(protocol_version=None),
            "other agent": dict(agent_id="11111111-2222-4333-8444-555555555555"),
            "bad agent id": dict(agent_id="nope"),
            "no connection id": dict(connection_id=None),
            "bad connection id": dict(connection_id="x" * 36),
            "zero interval": dict(heartbeat_interval_seconds=0),
            "negative interval": dict(heartbeat_interval_seconds=-1),
            "string interval": dict(heartbeat_interval_seconds="30"),
            "bool interval": dict(heartbeat_interval_seconds=True),
            "huge interval": dict(heartbeat_interval_seconds=10**9, heartbeat_timeout_seconds=10**10),
            "timeout <= interval": dict(heartbeat_interval_seconds=30, heartbeat_timeout_seconds=30),
            "no server time": dict(server_time=None),
            "bad server time": dict(server_time="yesterday-ish"),
            "wrong type": dict(type="authenticated"),
        }
        for name, overrides in cases.items():
            with self.subTest(name), self.assertRaises(ProtocolViolation):
                self.parse(**overrides)

    def test_error_message_becomes_server_error(self):
        with self.assertRaises(ServerError) as ctx:
            parse_registered(json.dumps({"type": "error", "code": "protocol_error",
                                         "message": "unsupported protocol_version"}), AGENT_ID)
        self.assertEqual(ctx.exception.code, "protocol_error")


class MalformedInputTests(unittest.TestCase):
    def test_invalid_json_and_shapes(self):
        for raw in ("", "not json", "{", "[]", "null", "42", '"str"', '{"no_type":1}',
                    '{"type":5}', '{"type":"x","v":NaN}', '{"type":"x","v":Infinity}',
                    "[" * 100000):
            with self.subTest(raw=raw[:20]), self.assertRaises(ProtocolViolation):
                decode_message(raw)

    def test_binary_frame(self):
        with self.assertRaises(ProtocolViolation):
            decode_message(b'{"type":"registered"}')

    def test_oversized(self):
        raw = json.dumps({"type": "x", "pad": "a" * MAX_MESSAGE_BYTES})
        with self.assertRaises(ProtocolViolation):
            decode_message(raw)

    def test_parse_registered_survives_garbage(self):
        for raw in ("garbage", "[]", b"\x00", None, 5):
            with self.subTest(raw=raw), self.assertRaises(ProtocolViolation):
                parse_registered(raw, AGENT_ID)

    def test_error_text_is_bounded_and_printable(self):
        with self.assertRaises(ServerError) as ctx:
            parse_registered(json.dumps({"type": "error", "code": "c\x1b[31m" * 50,
                                         "message": "m" * 5000}), AGENT_ID)
        self.assertLessEqual(len(ctx.exception.message), 120)
        self.assertTrue(ctx.exception.code.isprintable())


class HeartbeatAckTests(unittest.TestCase):
    def ack(self, seq, **extra):
        return json.dumps({"type": "heartbeat_ack", "seq": seq,
                           "server_time": "2026-11-05T07:00:00+00:00", **extra})

    def test_matching_seq(self):
        parse_heartbeat_ack(self.ack(5), 5)

    def test_mismatch(self):
        for seq in (4, 6, 0, None, "5", True, 5.0 + 0.5):
            with self.subTest(seq=seq), self.assertRaises(HeartbeatMismatch):
                parse_heartbeat_ack(self.ack(seq), 5)

    def test_wrong_type_and_error(self):
        with self.assertRaises(ProtocolViolation):
            parse_heartbeat_ack(json.dumps({"type": "registered"}), 1)
        with self.assertRaises(ServerError):
            parse_heartbeat_ack(json.dumps({"type": "error", "code": "protocol_error", "message": "m"}), 1)


if __name__ == "__main__":
    unittest.main()
