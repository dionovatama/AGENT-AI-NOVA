import base64
import json
import unittest
import uuid

from nova_agent.relay_protocol import (
    MAX_RELAY_DATA_BYTES, RelayProtocolViolation, build_tunnel_error,
    build_tunnel_opened, parse_server_relay_message,
)


def uid():
    return str(uuid.uuid4())


class RelayProtocolTests(unittest.TestCase):
    def test_open_tunnel(self):
        request_id, session_id, target_id = uid(), uid(), uid()
        cmd = parse_server_relay_message(json.dumps({
            "type": "OPEN_TUNNEL", "request_id": request_id,
            "session_id": session_id, "target_id": target_id, "port": 8729,
        }))
        self.assertEqual(cmd.type, "OPEN_TUNNEL")
        self.assertEqual(cmd.port, 8729)
        self.assertEqual(build_tunnel_opened(request_id=request_id, session_id=session_id)["type"], "TUNNEL_OPENED")

    def test_rejects_arbitrary_host_and_invalid_port(self):
        for target, port in (("10.0.0.1", 8729), (uid(), 0), (uid(), True), (uid(), 65536)):
            with self.subTest(target=target, port=port), self.assertRaises(RelayProtocolViolation):
                parse_server_relay_message(json.dumps({"type": "OPEN_TUNNEL", "request_id": uid(),
                    "session_id": uid(), "target_id": target, "port": port}))

    def test_data_validation(self):
        sid, data = uid(), b"relay payload"
        cmd = parse_server_relay_message(json.dumps({"type": "DATA", "session_id": sid,
            "seq": 9, "data": base64.b64encode(data).decode()}))
        self.assertEqual(cmd.data, data)
        with self.assertRaises(RelayProtocolViolation):
            parse_server_relay_message(json.dumps({"type": "DATA", "session_id": sid,
                "seq": 0, "data": base64.b64encode(b"x" * (MAX_RELAY_DATA_BYTES + 1)).decode()}))

    def test_close_reason_and_error_code_are_allowlisted(self):
        with self.assertRaises(RelayProtocolViolation):
            parse_server_relay_message(json.dumps({"type": "CLOSE_TUNNEL", "session_id": uid(), "reason": "shell"}))
        with self.assertRaises(RelayProtocolViolation):
            build_tunnel_error(request_id=uid(), session_id=uid(), code="ARBITRARY", message="bad")

    def test_unknown_message_rejected(self):
        with self.assertRaises(RelayProtocolViolation):
            parse_server_relay_message(json.dumps({"type": "RUN_COMMAND"}))


if __name__ == "__main__":
    unittest.main()
