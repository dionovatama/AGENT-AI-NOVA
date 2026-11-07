import uuid

from fastapi.testclient import TestClient

from app.database.models import AuditLog, Device, User
from app.database.session import SessionLocal
from app.main import app
from app.security.hashing import create_access_token

client = TestClient(app)


def _owner():
    uid = uuid.uuid4()
    with SessionLocal() as db:
        db.add(User(id=uid, email=f"pin-{uid.hex}@example.com", hashed_password="placeholder", is_active=True))
        db.commit()
    return uid, {"Authorization": f"Bearer {create_access_token(subject=str(uid))}"}


def _device(owner_id):
    did = uuid.uuid4()
    with SessionLocal() as db:
        db.add(Device(
            id=did, owner_id=owner_id, name="router", platform="mikrotik",
            host="192.0.2.10", port=8729, connection_type="api-ssl",
            status="active", device_metadata={"username": "operator"},
        ))
        db.commit()
    return did


def test_local_device_pin_change_requires_confirmation_and_audits_prefixes():
    owner_id, headers = _owner()
    device_id = _device(owner_id)

    denied = client.patch(f"/devices/{device_id}", headers=headers, json={"tls_fingerprint": "ab" * 32})
    assert denied.status_code == 409

    accepted = client.patch(
        f"/devices/{device_id}",
        headers=headers,
        json={"tls_fingerprint": "ab" * 32, "confirm_tls_fingerprint_change": True},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["metadata"]["tls_fingerprint"] == "ab" * 32

    with SessionLocal() as db:
        event = db.query(AuditLog).filter(
            AuditLog.user_id == owner_id, AuditLog.action == "device.tls_pin_updated"
        ).order_by(AuditLog.created_at.desc()).first()
        assert event is not None
        assert event.request_metadata["new_fingerprint_prefix"] == "ab" * 6
        assert "ab" * 32 not in str(event.request_metadata)


def test_foreign_user_cannot_update_local_device_pin():
    owner_id, _ = _owner()
    device_id = _device(owner_id)
    _, other_headers = _owner()
    response = client.patch(
        f"/devices/{device_id}",
        headers=other_headers,
        json={"tls_fingerprint": "cd" * 32, "confirm_tls_fingerprint_change": True},
    )
    assert response.status_code == 404
