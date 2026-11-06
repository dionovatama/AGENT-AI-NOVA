"""Pemilihan jalur lokal vs relay + guard fail-closed (Phase 5).

Butuh PostgreSQL + `alembic upgrade head` (tabel relay_targets & kolom tls_fingerprint),
sama seperti test_agent_targets_api.py. Relay dan TLS di-fake: yang diuji di sini adalah
KEPUTUSAN dan penolakannya; byte/TLS sungguhan diuji di test_relay_tls.py.
"""
from __future__ import annotations

import uuid

import pytest

import app.network.remote_transport as rt
from app.agents.relay_service import AgentOffline
from app.database.models import Device, RelayTarget, User
from app.database.session import SessionLocal
from app.network.relay_tls import RelayTlsError
from app.tools.context import ExecutionContext
from app.tools.mikrotik import MikrotikConnectionError

FP = "ab" * 32


class _FakeChannel:
    def __init__(self):
        self.closed = False

    async def close(self, reason: str = "requested"):
        self.closed = True


class _FakeTls:
    def __init__(self):
        self.sock = object()
        self.aclosed = False

    async def aclose(self):
        self.aclosed = True


@pytest.fixture
def world():
    """user + agent + device (api-ssl:8729) di DB; dibersihkan setelah tes."""
    from app.database.models import Agent
    db = SessionLocal()
    user = User(id=uuid.uuid4(), email=f"rt-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password="x", is_active=True)
    db.add(user)
    db.flush()
    agent = Agent(id=uuid.uuid4(), owner_id=user.id, name="pc", token_hash="x" * 8)
    device = Device(id=uuid.uuid4(), owner_id=user.id, name="r1", platform="mikrotik",
                    host="192.168.88.1", port=8729, connection_type="api-ssl",
                    device_metadata={"username": "admin"})
    db.add_all([agent, device])
    db.commit()
    yield db, user, agent, device
    db.rollback()
    db.query(RelayTarget).filter(RelayTarget.owner_id == user.id).delete()
    db.delete(device)
    db.delete(agent)
    db.delete(user)
    db.commit()
    db.close()


def _add_target(db, user, agent, device, *, ports=(8729,), fp=FP):
    t = RelayTarget(owner_id=user.id, agent_id=agent.id, device_id=device.id,
                    name=f"t-{uuid.uuid4().hex[:6]}", host="192.168.88.1",
                    ports=list(ports), tls_fingerprint=fp)
    db.add(t)
    db.commit()
    return t


def _ctx(db, user, device):
    return ExecutionContext(user=user, db=db, device=device, credential_plaintext="pw")


async def _enter(device, ctx):
    async with rt.remote_api_socket(device, ctx) as sock:
        return sock


async def test_device_without_target_uses_local_path(world, monkeypatch):
    db, user, agent, device = world

    async def boom(*a, **k):
        raise AssertionError("relay must not be touched")

    monkeypatch.setattr(rt, "open_relay", boom)
    assert await _enter(device, _ctx(db, user, device)) is None


async def test_no_context_or_db_is_local(world):
    _, _, _, device = world
    assert await _enter(device, None) is None
    assert await _enter(device, ExecutionContext(user=None, db=None, device=device)) is None


async def test_target_without_fingerprint_is_refused_and_never_dials(world, monkeypatch):
    db, user, agent, device = world
    _add_target(db, user, agent, device, fp=None)

    async def boom(*a, **k):
        raise AssertionError("must not dial without a pin")

    monkeypatch.setattr(rt, "open_relay", boom)
    with pytest.raises(rt.RemoteTransportError) as e:
        await _enter(device, _ctx(db, user, device))
    assert isinstance(e.value, MikrotikConnectionError)
    assert "fingerprint" in str(e.value).lower()


async def test_plain_api_over_relay_is_refused(world, monkeypatch):
    db, user, agent, device = world
    _add_target(db, user, agent, device)
    device.connection_type = "api"

    async def boom(*a, **k):
        raise AssertionError("must not dial")

    monkeypatch.setattr(rt, "open_relay", boom)
    with pytest.raises(rt.RemoteTransportError):
        await _enter(device, _ctx(db, user, device))


async def test_port_not_in_target_is_refused_no_local_fallback(world, monkeypatch):
    db, user, agent, device = world
    _add_target(db, user, agent, device, ports=(8728,))

    async def boom(*a, **k):
        raise AssertionError("must not dial")

    monkeypatch.setattr(rt, "open_relay", boom)
    with pytest.raises(rt.RemoteTransportError):
        await _enter(device, _ctx(db, user, device))


async def test_success_yields_socket_and_closes_tls_after(world, monkeypatch):
    db, user, agent, device = world
    target = _add_target(db, user, agent, device)
    chan, tls, seen = _FakeChannel(), _FakeTls(), {}

    async def fake_open_relay(db_, *, owner_id, target_id, port, **k):
        seen.update(owner_id=owner_id, target_id=target_id, port=port)
        return chan

    async def fake_tls(channel, *, fingerprint, **k):
        seen["fp"] = fingerprint
        assert channel is chan
        return tls

    monkeypatch.setattr(rt, "open_relay", fake_open_relay)
    monkeypatch.setattr(rt, "open_pinned_tls_socket", fake_tls)
    async with rt.remote_api_socket(device, _ctx(db, user, device)) as sock:
        assert sock is tls.sock
        assert not tls.aclosed
    assert tls.aclosed
    assert seen == {"owner_id": user.id, "target_id": target.id, "port": 8729, "fp": FP}


async def test_pin_mismatch_maps_to_safe_error_without_fingerprint(world, monkeypatch):
    db, user, agent, device = world
    _add_target(db, user, agent, device)

    async def fake_open_relay(*a, **k):
        return _FakeChannel()

    async def fake_tls(*a, **k):
        raise RelayTlsError("FINGERPRINT_MISMATCH", observed="cd" * 32)

    monkeypatch.setattr(rt, "open_relay", fake_open_relay)
    monkeypatch.setattr(rt, "open_pinned_tls_socket", fake_tls)
    with pytest.raises(rt.RemoteTransportError) as e:
        await _enter(device, _ctx(db, user, device))
    msg = str(e.value)
    assert "cd" * 32 not in msg and FP not in msg and "192.168" not in msg


async def test_agent_offline_maps_to_remote_error(world, monkeypatch):
    db, user, agent, device = world
    _add_target(db, user, agent, device)

    async def fake_open_relay(*a, **k):
        raise AgentOffline("agent is offline")

    monkeypatch.setattr(rt, "open_relay", fake_open_relay)
    with pytest.raises(rt.RemoteTransportError):
        await _enter(device, _ctx(db, user, device))
