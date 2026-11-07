import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from app.config import Settings, DEFAULT_DEV_CORS_ORIGINS
from app.main import validate_production_startup, app


def _base_settings_kwargs(**overrides):
    base = {
        "database_url": "sqlite:///:memory:",
        "jwt_secret_key": "ci-only-not-a-production-secret-key-32chars",
        "openrouter_api_key": "test-key",
        "linux_ssh_host": "127.0.0.1",
        "linux_ssh_private_key_path": "/tmp/key",
        # Produksi menolak koneksi langsung ke perangkat; basis valid harus mematikannya
        # supaya tiap tes mencapai aturan yang memang ingin diuji.
        "allow_direct_device_connections": False,
    }
    base.update(overrides)
    return base


def test_cors_origins_parsing_from_string():
    # Comma-separated string
    s1 = Settings(
        **_base_settings_kwargs(
            cors_origins="https://nova.corp.com, https://app.nova.corp.com",
        )
    )
    assert s1.cors_origins == ["https://nova.corp.com", "https://app.nova.corp.com"]

    # JSON array string
    s2 = Settings(
        **_base_settings_kwargs(
            cors_origins='["https://one.nova.corp", "https://two.nova.corp"]',
        )
    )
    assert s2.cors_origins == ["https://one.nova.corp", "https://two.nova.corp"]

    # Default dev origins
    s3 = Settings(**_base_settings_kwargs())
    assert s3.cors_origins == DEFAULT_DEV_CORS_ORIGINS


def test_production_settings_rejects_short_jwt_secret():
    with pytest.raises(ValidationError) as exc:
        Settings(
            **_base_settings_kwargs(
                app_env="production",
                jwt_secret_key="too-short-secret",
                agent_require_tls=True,
                cors_origins=["https://nova.corp.com"],
            )
        )
    assert "jwt_secret_key to be at least 32 characters long" in str(exc.value)


def test_production_settings_rejects_missing_or_disabled_agent_tls():
    with pytest.raises(ValidationError) as exc:
        Settings(
            **_base_settings_kwargs(
                app_env="production",
                jwt_secret_key="a" * 32,
                agent_require_tls=False,
                cors_origins=["https://nova.corp.com"],
            )
        )
    assert "agent_require_tls=True" in str(exc.value)

    with pytest.raises(ValidationError) as exc:
        Settings(
            **_base_settings_kwargs(
                app_env="production",
                jwt_secret_key="a" * 32,
                agent_require_tls=None,
                cors_origins=["https://nova.corp.com"],
            )
        )
    assert "agent_require_tls=True" in str(exc.value)


def test_production_settings_rejects_default_or_insecure_cors():
    # Default dev origins rejected in production
    with pytest.raises(ValidationError) as exc:
        Settings(
            **_base_settings_kwargs(
                app_env="production",
                jwt_secret_key="a" * 32,
                agent_require_tls=True,
            )
        )
    assert "cannot use default localhost CORS origins" in str(exc.value)

    # Empty CORS rejected in production
    with pytest.raises(ValidationError) as exc:
        Settings(
            **_base_settings_kwargs(
                app_env="production",
                jwt_secret_key="a" * 32,
                agent_require_tls=True,
                cors_origins=[],
            )
        )
    assert "cors_origins to be non-empty" in str(exc.value)

    # Wildcard CORS rejected in production
    with pytest.raises(ValidationError) as exc:
        Settings(
            **_base_settings_kwargs(
                app_env="production",
                jwt_secret_key="a" * 32,
                agent_require_tls=True,
                cors_origins=["*"],
            )
        )
    assert "cannot use wildcard" in str(exc.value)

    # Localhost rejected in production
    with pytest.raises(ValidationError) as exc:
        Settings(
            **_base_settings_kwargs(
                app_env="production",
                jwt_secret_key="a" * 32,
                agent_require_tls=True,
                cors_origins=["http://localhost:8080"],
            )
        )
    assert "cannot contain localhost" in str(exc.value)


def test_production_settings_accepts_valid_configuration():
    s = Settings(
        **_base_settings_kwargs(
            app_env="production",
            jwt_secret_key="super-secret-key-that-is-at-least-32-bytes-long",
            agent_require_tls=True,
            cors_origins=["https://console.nova.corp", "https://api.nova.corp"],
        )
    )
    assert s.app_env == "production"
    assert s.agent_require_tls is True
    assert s.cors_origins == ["https://console.nova.corp", "https://api.nova.corp"]


def test_validate_production_startup_fails_closed():
    # In development, startup validator passes with default settings
    dev_settings = Settings(**_base_settings_kwargs(app_env="development"))
    validate_production_startup(dev_settings)

    # In production, invalid attributes raise RuntimeError
    bad_prod = Settings(
        **_base_settings_kwargs(
            app_env="production",
            jwt_secret_key="super-secret-key-that-is-at-least-32-bytes-long",
            agent_require_tls=True,
            cors_origins=["https://console.nova.corp"],
        )
    )
    # Simulate an invalid mutation
    object.__setattr__(bad_prod, "jwt_secret_key", "short")
    with pytest.raises(RuntimeError) as exc:
        validate_production_startup(bad_prod)
    assert "Production startup aborted" in str(exc.value)


def test_cors_middleware_integration():
    client = TestClient(app)
    # Origin from allowed dev origin
    res = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert res.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert res.headers.get("access-control-allow-credentials") == "true"

    # Origin from untrusted origin
    res_untrusted = client.options(
        "/health",
        headers={
            "Origin": "http://evil-attacker.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert res_untrusted.headers.get("access-control-allow-origin") is None
