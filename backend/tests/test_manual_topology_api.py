"""Owner-scoped manual topology CRUD API tests."""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.database.models import Device, User
from app.database.session import SessionLocal
from app.main import app
from app.security.hashing import create_access_token

client = TestClient(app)


def _user(label: str):
    uid = uuid.uuid4()
    with SessionLocal() as db:
        db.add(User(id=uid, email=f"{label}-{uid.hex[:8]}@example.com",
                    hashed_password="placeholder_hash", is_active=True))
        db.commit()
    return uid, {"Authorization": f"Bearer {create_access_token(subject=str(uid))}"}


def test_manual_topology_node_link_crud_and_device_status_payload():
    uid, headers = _user("manual-topology")
    device_id = uuid.uuid4()
    with SessionLocal() as db:
        db.add(Device(id=device_id, owner_id=uid, name="Core Router", platform="mikrotik",
                      host="10.0.0.1", port=8729, connection_type="api-ssl"))
        db.commit()

    agent_response = client.post("/agents", headers=headers, json={"name": f"agent-{uuid.uuid4().hex[:6]}"})
    assert agent_response.status_code == 201, agent_response.text
    agent_id = agent_response.json()["id"]
    target_response = client.post(f"/agents/{agent_id}/targets", headers=headers, json={
        "name": "router-relay", "host": "10.0.0.1", "ports": [8729], "device_id": str(device_id),
    })
    assert target_response.status_code == 201, target_response.text

    first = client.post("/network/manual-topology/nodes", headers=headers, json={
        "device_id": str(device_id), "name": "Core Router", "kind": "mikrotik", "x": 120, "y": 90,
    })
    assert first.status_code == 201, first.text
    node_a = first.json()
    assert node_a["device"]["host"] == "10.0.0.1"
    assert node_a["device"]["reachability"] == "unknown"

    second = client.post("/network/manual-topology/nodes", headers=headers, json={
        "name": "Distribution Switch", "kind": "switch", "x": 420, "y": 90,
    })
    assert second.status_code == 201, second.text
    node_b = second.json()

    duplicate_device = client.post("/network/manual-topology/nodes", headers=headers, json={
        "device_id": str(device_id), "name": "Duplicate",
    })
    assert duplicate_device.status_code == 409

    link = client.post("/network/manual-topology/links", headers=headers, json={
        "source_node_id": node_a["id"], "target_node_id": node_b["id"],
        "label": "ether1", "connection_type": "ethernet",
    })
    assert link.status_code == 201, link.text

    updated = client.patch(f"/network/manual-topology/nodes/{node_b['id']}", headers=headers,
                           json={"x": 510, "y": 240})
    assert updated.status_code == 200
    assert updated.json()["x"] == 510

    saved = client.get("/network/manual-topology", headers=headers)
    assert saved.status_code == 200
    assert len(saved.json()["nodes"]) == 2
    assert len(saved.json()["links"]) == 1\n    assert saved.json()["available_devices"] == []

    deleted = client.delete(f"/network/manual-topology/nodes/{node_a['id']}", headers=headers)
    assert deleted.status_code == 204
    saved = client.get("/network/manual-topology", headers=headers).json()
    assert len(saved["nodes"]) == 1
    assert saved["links"] == []


def test_manual_topology_rejects_cross_owner_device_and_node_access():
    owner_a, headers_a = _user("manual-a")
    _, headers_b = _user("manual-b")
    device_id = uuid.uuid4()
    with SessionLocal() as db:
        db.add(Device(id=device_id, owner_id=owner_a, name="Private", platform="cisco",
                      host="192.0.2.1", port=22, connection_type="ssh"))
        db.commit()

    response = client.post("/network/manual-topology/nodes", headers=headers_b, json={
        "device_id": str(device_id), "name": "Hijack",
    })
    assert response.status_code == 404

    node = client.post("/network/manual-topology/nodes", headers=headers_a, json={
        "name": "Owner A node", "kind": "router",
    }).json()
    assert client.patch(f"/network/manual-topology/nodes/{node['id']}", headers=headers_b,
                        json={"x": 999}).status_code == 404
    assert client.delete(f"/network/manual-topology/nodes/{node['id']}", headers=headers_b).status_code == 404
    assert client.get("/network/manual-topology", headers=headers_b).json() == {"nodes": [], "links": [], "available_devices": []}
