"""
Tests for Device and Credential Data Model & Multi-Tenant Owner Isolation.

Covers:
8. User A attempts to access User B's device -> 404
9. User A attempts to access User B's credential -> 404
15. Device can be created for authenticated user.
16. Device cannot be retrieved by another user.
17. Device cannot reference another user's credential.
- Credential creation and owner scoping.
- AuditLog owner scoping.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.database.models import Credential, Device, User
from app.database.session import SessionLocal
from app.main import app
from app.security.hashing import create_access_token

client = TestClient(app)


def _create_user_and_headers(label: str) -> tuple[dict[str, str], uuid.UUID]:
    uid = uuid.uuid4()
    db = SessionLocal()
    try:
        user = User(
            id=uid,
            email=f"{label}-{uid.hex[:8]}@example.com",
            hashed_password="placeholder_hash",
            is_active=True,
        )
        db.add(user)
        db.commit()
    finally:
        db.close()

    token = create_access_token(subject=str(uid))
    return {"Authorization": f"Bearer {token}"}, uid


# ============================================================
# Device & Credential Tests (Phase 6, 7, 8)
# ============================================================

def test_create_device_for_authenticated_user():
    """15. Device can be created for authenticated user."""
    headers_a, uid_a = _create_user_and_headers("user-a")

    payload = {
        "name": "edge-router-01",
        "platform": "linux",
        "host": "192.168.1.50",
        "port": 22,
        "connection_type": "ssh",
        "status": "active",
        "metadata": {"rack": "A1", "site": "hq"},
    }

    res = client.post("/devices", headers=headers_a, json=payload)
    assert res.status_code == 201
    body = res.json()
    assert body["name"] == "edge-router-01"
    assert body["platform"] == "linux"
    assert body["owner_id"] == str(uid_a)
    assert body["metadata"]["rack"] == "A1"


def test_device_cannot_be_retrieved_by_another_user():
    """8. User A attempts to access User B's device -> 404
       16. Device cannot be retrieved by another user."""
    headers_a, uid_a = _create_user_and_headers("owner-a")
    headers_b, uid_b = _create_user_and_headers("owner-b")

    # User A creates a device
    res_a = client.post(
        "/devices",
        headers=headers_a,
        json={
            "name": "private-server-a",
            "platform": "linux",
            "host": "10.0.0.10",
            "port": 22,
        },
    )
    assert res_a.status_code == 201
    device_id = res_a.json()["id"]

    # User A can retrieve it
    get_a = client.get(f"/devices/{device_id}", headers=headers_a)
    assert get_a.status_code == 200
    assert get_a.json()["id"] == device_id

    # User B attempts to access User A's device -> 404 (anti-enumeration)
    get_b = client.get(f"/devices/{device_id}", headers=headers_b)
    assert get_b.status_code == 404
    assert get_b.json()["detail"] == "Device not found."

    # User B lists devices -> User A's device must not appear
    list_b = client.get("/devices", headers=headers_b)
    assert list_b.status_code == 200
    device_ids_b = [d["id"] for d in list_b.json()]
    assert device_id not in device_ids_b


def test_credential_creation_and_isolation():
    """9. User A attempts to access User B's credential -> 404"""
    headers_a, uid_a = _create_user_and_headers("cred-owner-a")
    headers_b, uid_b = _create_user_and_headers("cred-owner-b")

    # User A creates a credential
    res_cred = client.post(
        "/credentials",
        headers=headers_a,
        json={
            "name": "ssh-key-prod",
            "type": "ssh_key",
            "secret_reference": "vault://keys/prod-ssh-key",
        },
    )
    assert res_cred.status_code == 201
    cred_body = res_cred.json()
    assert cred_body["name"] == "ssh-key-prod"
    assert cred_body["owner_id"] == str(uid_a)
    # Zero Secret Exposure: secret_reference is not returned in CredentialResponse
    assert "secret_reference" not in cred_body

    cred_id = cred_body["id"]

    # User A can view credential details
    get_a = client.get(f"/credentials/{cred_id}", headers=headers_a)
    assert get_a.status_code == 200

    # User B attempts to view User A's credential -> 404
    get_b = client.get(f"/credentials/{cred_id}", headers=headers_b)
    assert get_b.status_code == 404
    assert get_b.json()["detail"] == "Credential not found."


def test_device_cannot_reference_another_users_credential():
    """17. Device cannot reference another user's credential."""
    headers_a, _ = _create_user_and_headers("user-with-cred")
    headers_b, _ = _create_user_and_headers("malicious-user")

    # User A creates a credential
    res_cred = client.post(
        "/credentials",
        headers=headers_a,
        json={
            "name": "secret-api-token",
            "type": "api_token",
            "secret_reference": "vault://tokens/nova-token",
        },
    )
    assert res_cred.status_code == 201
    cred_id_a = res_cred.json()["id"]

    # User B tries to associate User A's credential with User B's device -> 400
    res_device = client.post(
        "/devices",
        headers=headers_b,
        json={
            "name": "unauthorized-hijack-device",
            "platform": "cisco",
            "host": "10.0.0.99",
            "credential_id": cred_id_a,
        },
    )
    assert res_device.status_code == 400
    assert "does not belong" in res_device.json()["detail"]


def test_audit_logs_tenant_isolation():
    """Audit logs must be isolated by user."""
    headers_a, uid_a = _create_user_and_headers("audit-user-a")
    headers_b, uid_b = _create_user_and_headers("audit-user-b")

    # User A runs a tool to generate audit log
    client.post(
        "/tools/execute",
        headers=headers_a,
        json={"tool_name": "ping", "arguments": {"target": "127.0.0.1", "count": 1}, "confirmed": False},
    )

    # User A sees their audit logs
    logs_a = client.get("/audit-logs", headers=headers_a).json()
    assert len(logs_a) >= 1
    assert all(entry["user_id"] == str(uid_a) for entry in logs_a)

    # User B sees only their own audit logs (none so far)
    logs_b = client.get("/audit-logs", headers=headers_b).json()
    assert all(entry["user_id"] == str(uid_b) for entry in logs_b)
