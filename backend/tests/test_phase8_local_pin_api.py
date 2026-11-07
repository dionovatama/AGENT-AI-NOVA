import uuid

import pytest

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



@pytest.mark.asyncio
async def test_monitoring_error_does_not_echo_exception_secret(monkeypatch, caplog):
    import logging
    from fastapi import HTTPException
    from app.api import mikrotik_monitoring
    from app.database.models import User

    owner_id = uuid.uuid4()
    device_id = uuid.uuid4()
    secret_marker = "PASSWORD_SECRET_SENTINEL"
    with SessionLocal() as db:
        user = User(id=owner_id, email=f"monitor-{owner_id.hex}@example.com",
                    hashed_password="placeholder", is_active=True)
        device = Device(
            id=device_id, owner_id=owner_id, name="router", platform="mikrotik",
            host="192.0.2.11", port=8729, connection_type="api-ssl",
            status="active", device_metadata={"username": "operator"},
        )
        db.add_all([user, device])
        db.commit()
        db.refresh(user)

        monkeypatch.setattr(mikrotik_monitoring, "build_device_context", lambda *args: object())

        async def fail(*args):
            raise RuntimeError(secret_marker)

        monkeypatch.setattr(mikrotik_monitoring, "_run_on_device", fail)
        with caplog.at_level(logging.ERROR):
            with pytest.raises(HTTPException) as raised:
                await mikrotik_monitoring.get_mikrotik_monitoring(device_id, user, db)

    assert raised.value.status_code == 502
    assert secret_marker not in str(raised.value.detail)
    assert secret_marker not in caplog.text



def test_observed_local_tls_fingerprint_is_owner_only():
    from app.network.remote_transport import record_observed_fingerprint

    owner_id, owner_headers = _owner()
    device_id = _device(owner_id)
    record_observed_fingerprint(owner_id, device_id, "ef" * 32)

    own = client.get(f"/devices/{device_id}/observed-tls-fingerprint", headers=owner_headers)
    assert own.status_code == 200
    assert own.json()["observed"] == "ef" * 32

    _, other_headers = _owner()
    foreign = client.get(f"/devices/{device_id}/observed-tls-fingerprint", headers=other_headers)
    assert foreign.status_code == 404
