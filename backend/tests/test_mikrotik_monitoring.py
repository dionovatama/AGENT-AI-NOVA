"""Tests for read-only MikroTik monitoring history (Phase 7)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import librouteros.exceptions
from fastapi.testclient import TestClient

from app.api import mikrotik_monitoring as monitoring
from app.config import settings
from app.database.models import Device, DeviceMetricSample, User
from app.database.session import SessionLocal
from app.main import app
from app.security.hashing import create_access_token

client = TestClient(app)


def _user(label: str):
    user_id = uuid.uuid4()
    with SessionLocal() as db:
        db.add(User(
            id=user_id, email=f"{label}-{user_id.hex[:8]}@example.com",
            hashed_password="placeholder_hash", is_active=True,
        ))
        db.commit()
    return user_id, {"Authorization": f"Bearer {create_access_token(subject=str(user_id))}"}


def _device(owner_id):
    device_id = uuid.uuid4()
    with SessionLocal() as db:
        db.add(Device(
            id=device_id, owner_id=owner_id, name="history-router",
            platform="mikrotik", host="192.0.2.10", port=8729,
            connection_type="api-ssl",
        ))
        db.commit()
    return device_id


def _raw_snapshot():
    return {
        "resource": {"cpu-load": "12", "total-memory": "1000", "free-memory": "400",
                     "total-hdd-space": "2000", "free-hdd-space": "500", "version": "7.x"},
        "identity": {"name": "test-router"},
        "routerboard": {},
        "interfaces": [{"name": "ether1", "running": True, "rx_bps": 100, "tx_bps": 200}],
        "neighbors": [], "arp": [], "dhcp_leases": [], "bridge_hosts": [],
    }


def _patch_collector(monkeypatch, result=None, error=None):
    monkeypatch.setattr(monitoring, "build_device_context", lambda *args: object())

    async def fake_run(*args):
        if error:
            raise error
        return result if result is not None else _raw_snapshot()

    monkeypatch.setattr(monitoring, "_run_on_device", fake_run)


def _sample_count(device_id):
    with SessionLocal() as db:
        return db.query(DeviceMetricSample).filter(
            DeviceMetricSample.device_id == device_id
        ).count()


def test_monitoring_success_persists_sanitized_sample_and_throttles(monkeypatch):
    owner_id, headers = _user("metric-success")
    device_id = _device(owner_id)
    _patch_collector(monkeypatch)

    first = client.get(f"/devices/{device_id}/monitoring", headers=headers)
    second = client.get(f"/devices/{device_id}/monitoring", headers=headers)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert _sample_count(device_id) == 1
    with SessionLocal() as db:
        sample = db.query(DeviceMetricSample).filter(
            DeviceMetricSample.device_id == device_id
        ).one()
        assert sample.cpu_load_percent == 12
        assert sample.interfaces == [{"name": "ether1", "rx_bps": 100, "tx_bps": 200, "running": True}]
        assert "arp" not in str(sample.interfaces).lower()


def test_monitoring_failure_does_not_persist_sample(monkeypatch):
    owner_id, headers = _user("metric-failure")
    device_id = _device(owner_id)
    _patch_collector(monkeypatch, error=RuntimeError("router unavailable"))

    response = client.get(f"/devices/{device_id}/monitoring", headers=headers)

    assert response.status_code == 502
    assert _sample_count(device_id) == 0


def test_history_is_tenant_isolated_and_minutes_are_validated():
    owner_a, headers_a = _user("metric-owner-a")
    _, headers_b = _user("metric-owner-b")
    device_id = _device(owner_a)

    assert client.get(
        f"/devices/{device_id}/monitoring/history", headers=headers_b
    ).status_code == 404
    assert client.get(
        f"/devices/{device_id}/monitoring/history?minutes=0", headers=headers_a
    ).status_code == 422
    assert client.get(
        f"/devices/{device_id}/monitoring/history?minutes=10081", headers=headers_a
    ).status_code == 422


def test_history_downsamples_to_at_most_500_points():
    owner_id, headers = _user("metric-downsample")
    device_id = _device(owner_id)
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        db.add_all([
            DeviceMetricSample(
                device_id=device_id,
                collected_at=now - timedelta(seconds=59 - index * 59 / 699),
                cpu_load_percent=index % 100,
                memory_used_percent=50,
                storage_used_percent=None,
                interfaces=[{"name": "ether1", "rx_bps": index, "tx_bps": index * 2, "running": True}],
            )
            for index in range(700)
        ])
        db.commit()

    response = client.get(
        f"/devices/{device_id}/monitoring/history?minutes=1&interface=ether1",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["points"]) <= 500
    assert body["count"] == 700
    assert body["points"] == sorted(body["points"], key=lambda point: point["collected_at"])


def test_retention_prunes_old_samples_and_keeps_recent(monkeypatch):
    owner_id, _ = _user("metric-retention")
    device_id = _device(owner_id)
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        db.add_all([
            DeviceMetricSample(
                device_id=device_id, collected_at=now - timedelta(days=8),
                cpu_load_percent=1, memory_used_percent=2, storage_used_percent=None, interfaces=[],
            ),
            DeviceMetricSample(
                device_id=device_id, collected_at=now - timedelta(minutes=1),
                cpu_load_percent=3, memory_used_percent=4, storage_used_percent=None, interfaces=[],
            ),
        ])
        db.commit()

    monkeypatch.setattr(settings, "monitoring_retention_days", 7)
    monitoring._LAST_MONITORING_PRUNE.pop(device_id, None)
    with SessionLocal() as db:
        monitoring._save_metric_sample(db, db.get(Device, device_id), {
            "router": {"cpu_load_percent": 5, "memory_used_percent": 6},
            "interfaces": [],
        })
    with SessionLocal() as db:
        timestamps = [row.collected_at for row in db.query(DeviceMetricSample).filter(
            DeviceMetricSample.device_id == device_id
        ).all()]
    assert all(timestamp > now - timedelta(days=7) for timestamp in timestamps)


def test_metric_write_failure_is_best_effort():
    owner_id, _ = _user("metric-db-failure")
    device_id = _device(owner_id)
    with SessionLocal() as db:
        device = db.get(Device, device_id)

    class BrokenSession:
        def query(self, *args, **kwargs):
            raise RuntimeError("database unavailable")

        def rollback(self):
            pass

    monitoring._save_metric_sample(BrokenSession(), device, {
        "router": {}, "interfaces": [],
    })


def test_rows_catches_multitraperror_for_optional_menus():
    class MissingMenu:
        def path(self, *args):
            raise librouteros.exceptions.MultiTrapError.__new__(librouteros.exceptions.MultiTrapError)

    assert monitoring._rows(MissingMenu(), "system", "routerboard") == []
