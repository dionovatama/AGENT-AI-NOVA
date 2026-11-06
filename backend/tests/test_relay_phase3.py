import base64
import uuid

import pytest

from app.agents.relay_protocol import (
    RelayProtocolError,
    data_message,
    encode_relay_message,
    open_tunnel_message,
    parse_relay_message,
)
from app.agents.relay_sessions import RelaySessionError, RelaySessionRegistry, RelayState


def ids():
    return uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def test_open_tunnel_roundtrip_and_direction():
    request_id, session_id, target_id, _, _ = ids()
    raw = encode_relay_message(
        open_tunnel_message(
            request_id=request_id,
            session_id=session_id,
            target_id=target_id,
            port=8728,
        )
    )
    msg = parse_relay_message(raw, direction="server_to_agent")
    assert msg.type == "OPEN_TUNNEL"
    assert msg.request_id == str(request_id)
    assert msg.session_id == str(session_id)
    assert msg.target_id == str(target_id)
    assert msg.port == 8728

    with pytest.raises(RelayProtocolError):
        parse_relay_message(raw, direction="agent_to_server")


def test_data_roundtrip_preserves_binary_payload():
    _, session_id, _, _, _ = ids()
    payload = bytes(range(256)) * 8
    raw = encode_relay_message(
        data_message(session_id=session_id, seq=7, data=payload)
    )
    msg = parse_relay_message(raw, direction="agent_to_server")
    assert msg.type == "DATA"
    assert msg.session_id == str(session_id)
    assert msg.seq == 7
    assert msg.data == payload


@pytest.mark.parametrize("port", [0, 65536, -1, True, "8728"])
def test_open_tunnel_rejects_invalid_port(port):
    request_id, session_id, target_id, _, _ = ids()
    with pytest.raises(RelayProtocolError):
        open_tunnel_message(
            request_id=request_id,
            session_id=session_id,
            target_id=target_id,
            port=port,
        )


def test_registry_enforces_owner_and_connection_isolation():
    agent_id, owner_id, connection_id, target_id, _ = ids()
    other_owner = uuid.uuid4()
    registry = RelaySessionRegistry(max_per_agent=2, idle_timeout=60)
    session = registry.create(
        agent_id=agent_id,
        owner_id=owner_id,
        connection_id=connection_id,
        target_id=target_id,
        port=8728,
    )

    with pytest.raises(RelaySessionError):
        registry.get(
            session.session_id,
            agent_id=agent_id,
            owner_id=other_owner,
            connection_id=connection_id,
        )

    with pytest.raises(RelaySessionError):
        registry.get(
            session.session_id,
            agent_id=agent_id,
            owner_id=owner_id,
            connection_id=uuid.uuid4(),
        )

    assert registry.mark_open(
        session.session_id,
        agent_id=agent_id,
        owner_id=owner_id,
        connection_id=connection_id,
    ).state is RelayState.OPEN


def test_registry_enforces_per_agent_limit():
    agent_id, owner_id, connection_id, target_id, _ = ids()
    registry = RelaySessionRegistry(max_per_agent=2, idle_timeout=60)

    for _ in range(2):
        registry.create(
            agent_id=agent_id,
            owner_id=owner_id,
            connection_id=connection_id,
            target_id=target_id,
            port=8728,
        )

    with pytest.raises(RelaySessionError, match="session limit"):
        registry.create(
            agent_id=agent_id,
            owner_id=owner_id,
            connection_id=connection_id,
            target_id=target_id,
            port=8728,
        )


def test_registry_disconnect_cleanup_closes_active_sessions():
    agent_id, owner_id, connection_id, target_id, _ = ids()
    registry = RelaySessionRegistry(max_per_agent=8, idle_timeout=60)
    session = registry.create(
        agent_id=agent_id,
        owner_id=owner_id,
        connection_id=connection_id,
        target_id=target_id,
        port=8728,
    )
    registry.mark_open(
        session.session_id,
        agent_id=agent_id,
        owner_id=owner_id,
        connection_id=connection_id,
    )

    assert registry.cleanup_connection(
        agent_id=agent_id,
        connection_id=connection_id,
    ) == 1
    assert session.state is RelayState.CLOSED


def test_registry_idle_timeout_closes_requested_and_open_sessions():
    now = [100.0]
    clock = lambda: now[0]
    agent_id, owner_id, connection_id, target_id, _ = ids()
    registry = RelaySessionRegistry(max_per_agent=8, idle_timeout=10, clock=clock)

    requested = registry.create(
        agent_id=agent_id,
        owner_id=owner_id,
        connection_id=connection_id,
        target_id=target_id,
        port=8728,
    )
    opened = registry.create(
        agent_id=agent_id,
        owner_id=owner_id,
        connection_id=connection_id,
        target_id=target_id,
        port=8729,
    )
    registry.mark_open(
        opened.session_id,
        agent_id=agent_id,
        owner_id=owner_id,
        connection_id=connection_id,
    )

    now[0] = 111.0
    assert registry.expire_idle() == 2
    assert requested.state is RelayState.CLOSED
    assert opened.state is RelayState.CLOSED
