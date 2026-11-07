from types import SimpleNamespace

import pytest

from app.config import settings
from app.tools.mikrotik import MikrotikConnectionError, _connect


def _mikrotik_device(metadata=None):
    return SimpleNamespace(
        connection_type="api-ssl",
        device_metadata={"username": "operator", **(metadata or {})},
        host="192.0.2.1",
        port=8729,
    )


def test_local_api_ssl_without_pin_rejected_in_production(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "allow_unpinned_local_tls", False)
    with pytest.raises(MikrotikConnectionError, match="tanpa pin"):
        _connect(_mikrotik_device(), "router-password")


def test_local_api_ssl_without_pin_allowed_in_development(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "allow_unpinned_local_tls", False)
    monkeypatch.setattr("app.tools.mikrotik.librouteros.connect", lambda **kwargs: kwargs)
    result = _connect(_mikrotik_device(), "router-password")
    assert callable(result["ssl_wrapper"])


def test_local_api_ssl_without_pin_allowed_only_with_explicit_production_opt_in(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "allow_unpinned_local_tls", True)
    monkeypatch.setattr("app.tools.mikrotik.librouteros.connect", lambda **kwargs: kwargs)
    result = _connect(_mikrotik_device(), "router-password")
    assert callable(result["ssl_wrapper"])


def test_production_legacy_ssh_tool_rejects_disabled_host_key_checking(monkeypatch):
    from app.tools import linux

    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "linux_ssh_host_key_checking", False)
    monkeypatch.setattr(settings, "linux_ssh_known_hosts_path", None)
    with pytest.raises(RuntimeError, match="known_hosts"):
        linux._open_connection()
