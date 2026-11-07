"""Target relay per Agent: REST + open_relay (service). Butuh PostgreSQL dan
`alembic upgrade head` (tabel relay_targets), sama seperti test_agents_api.py."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.agents.manager import AgentConnectionManager, AgentRuntimeConfig
from app.agents.registry import LiveConnection
from app.agents.relay_service import (
    AgentOffline, RelayPortNotAllowed, RelayTargetNotFound, RelayUnavailable, open_relay,
)
from app.database.models import Agent, AuditLog, Device, User
from app.database.session import SessionLocal
from app.main import app
from app.security.hashing import create_access_token
from tests.agents_fakes import FakeStore

client = TestClient(app)


def _user(label="t"):
    uid = uuid.uuid4()
    with SessionLocal() as db:
        db.add(User(id=uid, email=f"{label}-{uid.hex[:8]}@example.com",
                    hashed_password="placeholder_hash", is_active=True))
        db.commit()
    return uid, {"Authorization": f"Bearer {create_access_token(subject=str(uid))}"}


def _agent(headers) -> dict:
    res = client.post("/agents", headers=headers, json={"name": f"pc-{uuid.uuid4().hex[:6]}"})
    assert res.status_code == 201, res.text
    return res.json()


def _target(headers, agent_id, **over):
    body = {"name": f"r-{uuid.uuid4().hex[:6]}", "host": "192.168.88.1", "ports": [8729]}
    body.update(over)
    return client.post(f"/agents/{agent_id}/targets", headers=headers, json=body)


def test_create_list_delete_target_and_agent_config_snippet():
    _, h = _user()
    agent = _agent(h)
    res = _target(h, agent["id"], ports=[8729, 8728, 8729])
    assert res.status_code == 201, res.text
    t = res.json()
    assert t["ports"] == [8728, 8729]
    assert t["agent_config"] == {"target_id": t["id"], "host": "192.168.88.1", "ports": [8728, 8729]}
    listed = client.get(f"/agents/{agent['id']}/targets", headers=h).json()
    assert [x["id"] for x in listed] == [t["id"]]
    assert client.delete(f"/agents/{agent['id']}/targets/{t['id']}", headers=h).status_code == 204
    assert client.get(f"/agents/{agent['id']}/targets", headers=h).json() == []


@pytest.mark.parametrize("over", [
    {"host": "127.0.0.1"}, {"host": "169.254.169.254"}, {"host": "0.0.0.0"},
    {"host": "bad host!"}, {"ports": []}, {"ports": [0]}, {"ports": [70000]},
    {"ports": [True]}, {"name": "  "},
])
def test_create_target_rejects_bad_input(over):
    _, h = _user()
    agent = _agent(h)
    assert _target(h, agent["id"], **over).status_code == 422


def test_duplicate_name_conflicts():
    _, h = _user()
    agent = _agent(h)
    assert _target(h, agent["id"], name="main").status_code == 201
    assert _target(h, agent["id"], name="main").status_code == 409


def test_tenant_isolation_on_agent_device_and_target():
    _, a = _user("a")
    _, b = _user("b")
    agent_a = _agent(a)
    t = _target(a, agent_a["id"]).json()
    assert _target(b, agent_a["id"]).status_code == 404            # foreign agent
    assert client.get(f"/agents/{agent_a['id']}/targets", headers=b).status_code == 404
    assert client.delete(f"/agents/{agent_a['id']}/targets/{t['id']}", headers=b).status_code == 404
    assert t["id"] in client.get(f"/agents/{agent_a['id']}/targets", headers=a).text  # still there

    uid_b, _ = _user("c")
    dev_id = uuid.uuid4()
    with SessionLocal() as db:
        db.add(Device(id=dev_id, owner_id=uid_b, name="d", platform="mikrotik",
                      host="10.0.0.1", port=8728, connection_type="api", status="active"))
        db.commit()
    assert _target(a, agent_a["id"], device_id=str(dev_id)).status_code == 404  # foreign device


def test_deleting_agent_removes_its_targets():
    _, h = _user()
    agent = _agent(h)
    tid = _target(h, agent["id"]).json()["id"]
    assert client.delete(f"/agents/{agent['id']}", headers=h).status_code == 204
    with SessionLocal() as db:
        from app.database.models import RelayTarget
        assert db.get(RelayTarget, uuid.UUID(tid)) is None


# ---------------------------------------------------------------- open_relay

class _Sock:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


def _online(agent_id: str, owner_id: uuid.UUID):
    """Tandai agent online di DB dan pasang koneksi hidup di manager uji."""
    conn = uuid.uuid4()
    with SessionLocal() as db:
        a = db.get(Agent, uuid.UUID(agent_id))
        a.status = "online"; a.connection_id = conn
        a.last_heartbeat_at = datetime.now(timezone.utc)
        db.commit()
    manager = AgentConnectionManager(store=FakeStore(), cfg=AgentRuntimeConfig())
    sock = _Sock()
    manager.registry.register(LiveConnection(uuid.UUID(agent_id), conn, owner_id, sock))
    return manager, sock


@pytest.mark.asyncio
async def test_open_relay_sends_open_tunnel_for_owned_target():
    import asyncio
    uid, h = _user()
    agent = _agent(h)
    t = _target(h, agent["id"]).json()
    manager, sock = _online(agent["id"], uid)
    with SessionLocal() as db:
        task = asyncio.create_task(open_relay(
            db, owner_id=uid, target_id=uuid.UUID(t["id"]), port=8729,
            manager=manager, open_timeout=1.0))
        while not sock.sent:
            await asyncio.sleep(0)
        req = sock.sent[0]
        assert req["type"] == "OPEN_TUNNEL" and req["target_id"] == t["id"] and req["port"] == 8729
        assert "host" not in req  # backend never tells the Agent where to connect
        import json
        await manager._handle_relay_message(json.dumps({
            "type": "TUNNEL_OPENED", "request_id": req["request_id"],
            "session_id": req["session_id"]}), _session(manager, agent["id"], uid))
        channel = await task
        assert not channel.closed


def _session(manager, agent_id, owner_id):
    from app.agents.manager import _Session
    live = manager.registry.get(uuid.UUID(agent_id))
    return _Session(uuid.UUID(agent_id), owner_id, live.connection_id, "Linux", "0.2.0")


@pytest.mark.asyncio
async def test_open_relay_denials():
    uid, h = _user()
    other, _ = _user("other")
    agent = _agent(h)
    t = _target(h, agent["id"]).json()
    manager = AgentConnectionManager(store=FakeStore(), cfg=AgentRuntimeConfig())
    with SessionLocal() as db:
        with pytest.raises(RelayTargetNotFound):   # unknown
            await open_relay(db, owner_id=uid, target_id=uuid.uuid4(), port=8729, manager=manager)
        with pytest.raises(RelayTargetNotFound):   # other tenant's id looks identical
            await open_relay(db, owner_id=other, target_id=uuid.UUID(t["id"]), port=8729, manager=manager)
        with pytest.raises(RelayPortNotAllowed):
            await open_relay(db, owner_id=uid, target_id=uuid.UUID(t["id"]), port=22, manager=manager)
        with pytest.raises(AgentOffline):          # registered but never connected
            await open_relay(db, owner_id=uid, target_id=uuid.UUID(t["id"]), port=8729, manager=manager)

    online_manager, sock = _online(agent["id"], uid)
    with SessionLocal() as db:
        other_worker = AgentConnectionManager(store=FakeStore(), cfg=AgentRuntimeConfig())  # no live socket here
        with pytest.raises(AgentOffline):
            await open_relay(db, owner_id=uid, target_id=uuid.UUID(t["id"]), port=8729, manager=other_worker)
    assert sock.sent == []
    assert issubclass(AgentOffline, RelayUnavailable)

# -- Phase 5: pin fingerprint sertifikat router ---------------------------------

def test_target_tls_fingerprint_is_normalized_and_returned():
    _, h = _user()
    agent = _agent(h)
    pretty = ":".join(["AB"] * 32)
    res = _target(h, agent["id"], tls_fingerprint=pretty)
    assert res.status_code == 201, res.text
    assert res.json()["tls_fingerprint"] == "ab" * 32
    listed = client.get(f"/agents/{agent['id']}/targets", headers=h).json()
    assert listed[0]["tls_fingerprint"] == "ab" * 32


def test_target_without_fingerprint_has_null_pin():
    _, h = _user()
    agent = _agent(h)
    assert _target(h, agent["id"]).json()["tls_fingerprint"] is None


@pytest.mark.parametrize("bad", ["abc", "zz" * 32, "ab" * 31, "ab" * 33])
def test_target_rejects_bad_fingerprint(bad):
    _, h = _user()
    agent = _agent(h)
    assert _target(h, agent["id"], tls_fingerprint=bad).status_code == 422



def test_relay_pin_rotation_requires_confirmation_and_current_pin():
    _, h = _user()
    agent = _agent(h)
    target = _target(h, agent["id"], tls_fingerprint="ab" * 32).json()
    url = f"/agents/{agent['id']}/targets/{target['id']}"

    denied = client.patch(url, headers=h, json={
        "tls_fingerprint": "cd" * 32,
        "expected_current_fingerprint_prefix": "ab" * 8,
        "confirm": False,
    })
    assert denied.status_code == 409

    stale = client.patch(url, headers=h, json={
        "tls_fingerprint": "cd" * 32,
        "expected_current_fingerprint_prefix": "ef" * 8,
        "confirm": True,
    })
    assert stale.status_code == 409

    accepted = client.patch(url, headers=h, json={
        "tls_fingerprint": "cd" * 32,
        "expected_current_fingerprint_prefix": "ab" * 8,
        "confirm": True,
    })
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["tls_fingerprint"] == "cd" * 8
    with SessionLocal() as db:
        event = db.query(AuditLog).filter(
            AuditLog.action == "agent.target.pin_updated"
        ).order_by(AuditLog.created_at.desc()).first()
        assert event is not None
        assert event.request_metadata["old_fingerprint_prefix"] == "ab" * 6
        assert event.request_metadata["new_fingerprint_prefix"] == "cd" * 6
        assert "cd" * 32 not in str(event.request_metadata)



def test_observed_relay_fingerprint_is_owner_only():
    from app.network.remote_transport import record_observed_fingerprint

    owner_id, owner_headers = _user("pin-owner")
    agent = _agent(owner_headers)
    target = _target(owner_headers, agent["id"]).json()
    record_observed_fingerprint(owner_id, uuid.UUID(target["id"]), "ef" * 32)
    own = client.get(
        f"/agents/{agent['id']}/targets/{target['id']}/observed-fingerprint",
        headers=owner_headers,
    )
    assert own.status_code == 200
    assert own.json()["observed"] == "ef" * 32

    _, other_headers = _user("pin-other")
    foreign = client.get(
        f"/agents/{agent['id']}/targets/{target['id']}/observed-fingerprint",
        headers=other_headers,
    )
    assert foreign.status_code == 404
