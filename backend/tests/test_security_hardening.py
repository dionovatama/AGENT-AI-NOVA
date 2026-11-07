from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import EmailStr

from app.config import settings
from app.api.auth import RegisterRequest, register
from app.api.devices import _validate_production_device_host
from app.tools.mikrotik import MikrotikConnectionError, _connect


def test_public_registration_is_closed_when_flag_is_false(monkeypatch):
    monkeypatch.setattr(settings, "public_registration_enabled", False)
    payload = RegisterRequest(email="new-user@example.com", password="a-strong-test-password")
    with pytest.raises(HTTPException) as error:
        register(payload, db=None)
    assert error.value.status_code == 403


@pytest.mark.parametrize("host", ["192.168.1.20", "10.20.30.40", "fd00::10"])
def test_production_device_host_accepts_private_ip_literals(monkeypatch, host):
    monkeypatch.setattr(settings, "app_env", "production")
    _validate_production_device_host(host)


@pytest.mark.parametrize("host", ["example.com", "8.8.8.8", "127.0.0.1", "169.254.1.1"])
def test_production_device_host_rejects_non_private_or_special_targets(monkeypatch, host):
    monkeypatch.setattr(settings, "app_env", "production")
    with pytest.raises(HTTPException) as error:
        _validate_production_device_host(host)
    assert error.value.status_code == 422


def test_direct_mikrotik_connection_is_blocked_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "allow_direct_device_connections", False)
    device = SimpleNamespace(
        connection_type="api-ssl",
        device_metadata={"username": "nova"},
        host="192.168.1.10",
        port=8729,
    )
    with pytest.raises(MikrotikConnectionError, match="Koneksi langsung"):
        _connect(device, "not-a-real-password")
