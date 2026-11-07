"""GET /network/topology dan POST /network/devices/{id}/refresh (Phase 6).

Butuh PostgreSQL + `alembic upgrade head` (kolom devices.reachability dst.).
Relay dan TLS di-fake; yang diuji: scoping owner, status jujur, throttle, tanpa login/credential.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient

import app.network.probe as probe
from app.agents.relay_service import AgentOffline
from app.database.models import Agent, Device
from app.database.session import SessionLocal
from app.main import app
from app.network.relay_tls import RelayTlsError
from app.security.hashing import create_access_token
from app.database.models import User

client = TestClient(app)
FP = "ab" * 32


def _user(label="n"):
    uid = uuid.uuid4()
    with SessionLocal() as db:
        db.add(User(id=uid, email=f"{label}-{uid.hex[:8]}@example.com",
                    hashed_password="placeholder_hash", is_active=True))
        db.commit()
    return uid, {"Authorization": f"Bearer {create_access_token(subject=str(uid))}"}


def _agent(headers, online=False):
    res = client.post("/agents", headers=headers, json={"name": f"pc-{uuid.uuid4().hex[:6]}"})
    assert res.status_code == 201, res.text
    agent = res.json()
    if online:
        with SessionLocal() as db:
            a = db.get(Agent, uuid.UUID(agent["id"]))
            a.status = "online"
            a.last_heartbeat_at = datetime.now(timezone.utc)
            db.commit()
    return agent


def _device(owner_id, port=8729, conn="api-ssl") -> str:
    did = uuid.uuid4()
    with SessionLocal() as db:
        db.add(Device(id=did, owner_id=owner_id, name=f"r-{did.hex[:6]}", platform="mikrotik",
                      host="192.168.7.5", port=port, connection_type=conn,
                      device_metadata={"username": "nova"}))
        db.commit()
    return str(did)


def _link(headers, agent_id, device_id, ports=(8729,), fp=FP):
    body = {"name": f"t-{uuid.uuid4().hex[:6]}", "host": "192.168.7.5",
            "ports": list(ports), "device_id": device_id}
    if fp:
        body["tls_fingerprint"] = fp
    res = client.post(f"/agents/{agent_id}/targets", headers=headers, json=body)
    assert res.status_code == 201, res.text
    return res.json()


def _topo(h):
    res = client.get("/network/topology", headers=h)
    assert res.status_code == 200, res.text
    return res.json()


def _dev_node(topo, device_id):
    return next(n for n in topo["nodes"] if n["id"] == f"device:{device_id}")


class _FakeChannel:
    async def close(self, reason="requested"):
        pass


class _FakeTls:
    aclosed = False

    async def aclose(self):
        _FakeTls.aclosed = True


def _patch_probe(monkeypatch, *, relay=None, tls=None):
    async def fake_relay(db, *, owner_id, target_id, port, **k):
        if relay is not None:
            raise relay
        return _FakeChannel()

    async def fake_tls(channel, *, fingerprint, **k):
        if tls is not None:
            raise tls
        return _FakeTls()

    monkeypatch.setattr(probe, "open_relay", fake_relay)
    monkeypatch.setattr(probe, "open_pinned_tls_socket", fake_tls)


def test_requires_auth():
    assert client.get("/network/topology").status_code in (401, 403)
    assert client.post(f"/network/devices/{uuid.uuid4()}/refresh").status_code in (401, 403)


def test_new_user_topology_is_only_nova():
    _, h = _user()
    topo = _topo(h)
    assert [n["id"] for n in topo["nodes"]] == ["nova"]
    assert topo["summary"]["devices_total"] == 0


def test_topology_shows_agent_device_and_relay_edge():
    uid, h = _user()
    agent = _agent(h, online=True)
    dev = _device(uid)
    _link(h, agent["id"], dev)
    topo = _topo(h)
    d = _dev_node(topo, dev)
    assert d["route"] == "agent" and d["agent_id"] == agent["id"] and d["issues"] == []
    assert d["status"] == "unknown"  # belum pernah di-refresh -> jujur: unknown
    assert any(e["kind"] == "relay" and e["to"] == f"device:{dev}" for e in topo["edges"])
    assert next(n for n in topo["nodes"] if n["id"] == f"agent:{agent['id']}")["status"] == "online"


def test_offline_agent_makes_device_agent_offline():
    uid, h = _user()
    agent = _agent(h, online=False)
    dev = _device(uid)
    _link(h, agent["id"], dev)
    assert _dev_node(_topo(h), dev)["status"] == "agent_offline"


def test_topology_flags_real_world_misconfig():
    uid, h = _user()
    dev = _device(uid, port=8728, conn="api-ssl")
    assert "port_8728_with_api_ssl" in _dev_node(_topo(h), dev)["issues"]


def test_topology_is_tenant_isolated():
    uid_a, ha = _user("a")
    uid_b, hb = _user("b")
    agent_a = _agent(ha)
    dev_a = _device(uid_a)
    _link(ha, agent_a["id"], dev_a)
    ids_b = {n["id"] for n in _topo(hb)["nodes"]}
    assert ids_b == {"nova"}
    assert client.post(f"/network/devices/{dev_a}/refresh", headers=hb).status_code == 404


def test_refresh_unknown_device_404():
    _, h = _user()
    assert client.post(f"/network/devices/{uuid.uuid4()}/refresh", headers=h).status_code == 404


def test_refresh_without_target_does_not_probe_and_stays_unknown(monkeypatch):
    uid, h = _user()
    dev = _device(uid)

    async def boom(*a, **k):
        raise AssertionError("must not dial for a direct device")

    monkeypatch.setattr(probe, "open_relay", boom)
    res = client.post(f"/network/devices/{dev}/refresh", headers=h).json()
    assert res["reachability"] == "unknown"


def test_refresh_online_then_topology_reports_online(monkeypatch):
    uid, h = _user()
    agent = _agent(h, online=True)
    dev = _device(uid)
    _link(h, agent["id"], dev)
    _patch_probe(monkeypatch)
    res = client.post(f"/network/devices/{dev}/refresh", headers=h).json()
    assert res["reachability"] == "online" and res["cached"] is False
    assert _FakeTls.aclosed is True  # sesi ditutup setelah probe
    d = _dev_node(_topo(h), dev)
    assert d["status"] == "online" and d["stale"] is False and d["last_checked_at"]


def test_refresh_is_throttled_with_cached_result(monkeypatch):
    uid, h = _user()
    agent = _agent(h, online=True)
    dev = _device(uid)
    _link(h, agent["id"], dev)
    _patch_probe(monkeypatch)
    first = client.post(f"/network/devices/{dev}/refresh", headers=h).json()
    calls = {"n": 0}

    async def counting(*a, **k):
        calls["n"] += 1
        return _FakeChannel()

    monkeypatch.setattr(probe, "open_relay", counting)
    second = client.post(f"/network/devices/{dev}/refresh", headers=h).json()
    assert second["cached"] is True and second["reachability"] == first["reachability"]
    assert calls["n"] == 0


def test_refresh_pin_mismatch_is_offline_and_leaks_nothing(monkeypatch):
    uid, h = _user()
    agent = _agent(h, online=True)
    dev = _device(uid)
    _link(h, agent["id"], dev)
    _patch_probe(monkeypatch, tls=RelayTlsError("FINGERPRINT_MISMATCH", observed="cd" * 32))
    res = client.post(f"/network/devices/{dev}/refresh", headers=h).json()
    assert res["reachability"] == "offline"
    assert "cd" * 32 not in res["detail"] and FP not in res["detail"] and "192.168" not in res["detail"]


def test_refresh_agent_offline_is_offline(monkeypatch):
    uid, h = _user()
    agent = _agent(h)
    dev = _device(uid)
    _link(h, agent["id"], dev)
    _patch_probe(monkeypatch, relay=AgentOffline("agent is offline"))
    res = client.post(f"/network/devices/{dev}/refresh", headers=h).json()
    assert res["reachability"] == "offline" and "offline" in res["detail"]


def test_refresh_target_without_pin_is_offline_and_never_dials(monkeypatch):
    uid, h = _user()
    agent = _agent(h, online=True)
    dev = _device(uid)
    _link(h, agent["id"], dev, fp=None)

    async def boom(*a, **k):
        raise AssertionError("must not dial without a pin")

    monkeypatch.setattr(probe, "open_relay", boom)
    res = client.post(f"/network/devices/{dev}/refresh", headers=h).json()
    assert res["reachability"] == "offline" and "pin" in res["detail"].lower()
