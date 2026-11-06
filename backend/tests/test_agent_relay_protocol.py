import base64
import json
import uuid

import pytest

from app.agents.relay_protocol import (
    MAX_RELAY_DATA_BYTES, RelayProtocolError, close_tunnel_message,
    data_message, encode_relay_message, open_tunnel_message,
    parse_relay_message, tunnel_error_message, tunnel_opened_message,
)
from app.agents.relay_sessions import RelaySessionError, RelaySessionRegistry, RelayState


def uid():
    return uuid.uuid4()


def test_open_tunnel_round_trip_and_direction_guard():
    payload = open_tunnel_message(request_id=uid(), session_id=uid(), target_id=uid(), port=8729)
    parsed = parse_relay_message(encode_relay_message(payload), direction="server_to_agent")
    assert parsed.type == "OPEN_TUNNEL" and parsed.port == 8729
    with pytest.raises(RelayProtocolError):
        parse_relay_message(encode_relay_message(payload), direction="agent_to_server")


def test_open_tunnel_rejects_invalid_port_and_non_uuid_target():
    with pytest.raises(RelayProtocolError):
        open_tunnel_message(request_id=uid(), session_id=uid(), target_id=uid(), port=0)
    bad = {"type": "OPEN_TUNNEL", "request_id": str(uid()), "session_id": str(uid()),
           "target_id": "127.0.0.1", "port": 8729}
    with pytest.raises(RelayProtocolError):
        parse_relay_message(json.dumps(bad), direction="server_to_agent")


def test_opened_and_error_messages_are_correlated_and_bounded():
    req, sid = uid(), uid()
    opened = parse_relay_message(encode_relay_message(tunnel_opened_message(request_id=req, session_id=sid)),
                                 direction="agent_to_server")
    assert opened.request_id == str(req) and opened.session_id == str(sid)
    err = tunnel_error_message(request_id=req, session_id=sid, code="TARGET_NOT_ALLOWED", message="not allowed")
    assert parse_relay_message(encode_relay_message(err), direction="agent_to_server").code == "TARGET_NOT_ALLOWED"
    with pytest.raises(RelayProtocolError):
        tunnel_error_message(request_id=req, session_id=sid, code="ARBITRARY", message="x")


def test_data_is_bounded_and_base64_validated_in_both_directions():
    sid = uid()
    payload = b"nova-relay" * 100
    msg = data_message(session_id=sid, seq=3, data=payload)
    parsed = parse_relay_message(encode_relay_message(msg), direction="agent_to_server")
    assert parsed.data == payload and parsed.seq == 3
    assert parse_relay_message(encode_relay_message(msg), direction="server_to_agent").data == payload
    with pytest.raises(RelayProtocolError):
        data_message(session_id=sid, seq=1, data=b"x" * (MAX_RELAY_DATA_BYTES + 1))
    malformed = {"type": "DATA", "session_id": str(sid), "seq": 1, "data": "%%%"}
    with pytest.raises(RelayProtocolError):
        parse_relay_message(json.dumps(malformed), direction="agent_to_server")


def test_close_message_rejects_unknown_reason():
    with pytest.raises(RelayProtocolError):
        close_tunnel_message(session_id=uid(), reason="execute-anything")


def test_session_state_machine_enforces_identity_and_terminal_states():
    agent, owner, conn, target = uid(), uid(), uid(), uid()
    registry = RelaySessionRegistry(max_per_agent=2, idle_timeout=10)
    session = registry.create(agent_id=agent, owner_id=owner, connection_id=conn, target_id=target, port=8729)
    assert session.state is RelayState.REQUESTED
    with pytest.raises(RelaySessionError):
        registry.get(session.session_id, agent_id=agent, owner_id=uid(), connection_id=conn)
    registry.mark_open(session.session_id, agent_id=agent, owner_id=owner, connection_id=conn)
    registry.touch(session.session_id, agent_id=agent, owner_id=owner, connection_id=conn)
    registry.close(session.session_id, agent_id=agent, owner_id=owner, connection_id=conn)
    assert session.state is RelayState.CLOSED
    with pytest.raises(RelaySessionError):
        registry.touch(session.session_id, agent_id=agent, owner_id=owner, connection_id=conn)


def test_session_limit_disconnect_cleanup_and_idle_expiry():
    now = [100.0]
    registry = RelaySessionRegistry(max_per_agent=1, idle_timeout=5, clock=lambda: now[0])
    agent, owner, conn = uid(), uid(), uid()
    one = registry.create(agent_id=agent, owner_id=owner, connection_id=conn, target_id=uid(), port=8729)
    with pytest.raises(RelaySessionError):
        registry.create(agent_id=agent, owner_id=owner, connection_id=conn, target_id=uid(), port=8729)
    now[0] += 6
    assert registry.expire_idle() == 1
    assert one.state is RelayState.CLOSED
    two = registry.create(agent_id=agent, owner_id=owner, connection_id=conn, target_id=uid(), port=8729)
    registry.mark_open(two.session_id, agent_id=agent, owner_id=owner, connection_id=conn)
    assert registry.cleanup_connection(agent_id=agent, connection_id=conn) == 1
    assert two.state is RelayState.CLOSED
