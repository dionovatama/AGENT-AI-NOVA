"""Cross-tenant regression checks for high-value owner-scoped resources."""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.database.models import AuditLog, Configuration, Credential, Device, User
from app.database.session import SessionLocal
from app.main import app
from app.security.hashing import create_access_token

client = TestClient(app)


def _user(label: str):
    user_id = uuid.uuid4()
    with SessionLocal() as db:
        db.add(User(
            id=user_id, email=f"{label}-{user_id.hex}@example.com",
            hashed_password="placeholder", is_active=True,
        ))
        db.commit()
    return user_id, {"Authorization": f"Bearer {create_access_token(subject=str(user_id))}"}


def test_foreign_device_credential_configuration_and_audit_are_not_accessible():
    owner_id, _ = _user("tenant-owner")
    _, other_headers = _user("tenant-other")
    device_id, credential_id, config_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    with SessionLocal() as db:
        db.add(Device(
            id=device_id, owner_id=owner_id, name="tenant-router", platform="mikrotik",
            host="192.0.2.20", port=8728, connection_type="api", status="active",
        ))
        db.add(Credential(
            id=credential_id, owner_id=owner_id, name="tenant-credential",
            type="password", secret_reference=None, encrypted_secret="ciphertext",
            encryption_nonce="nonce", encryption_key_id="key-1",
        ))
        db.add(Configuration(
            id=config_id, owner_id=owner_id, device_id=device_id, status="DRAFT",
            risk_level="LOW", change_set={"operations": []},
            plan_hash="a" * 64, state_fingerprint="b" * 64,
        ))
        db.add(AuditLog(
            user_id=owner_id, device_id=device_id, action="tenant.test",
            result_status="SUCCESS", request_metadata={"marker": "owner-only"},
        ))
        db.commit()

    assert client.get(f"/devices/{device_id}", headers=other_headers).status_code == 404
    assert client.patch(
        f"/devices/{device_id}", headers=other_headers,
        json={"name": "stolen"},
    ).status_code == 404
    assert client.get(f"/credentials/{credential_id}", headers=other_headers).status_code == 404
    assert client.delete(f"/credentials/{credential_id}", headers=other_headers).status_code == 404
    assert client.get(f"/configurations/{config_id}", headers=other_headers).status_code == 404

    other_audit = client.get("/audit-logs", headers=other_headers)
    assert other_audit.status_code == 200
    assert all(item["action"] != "tenant.test" for item in other_audit.json())
