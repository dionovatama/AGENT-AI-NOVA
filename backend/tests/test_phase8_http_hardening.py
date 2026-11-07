from types import SimpleNamespace

import pytest

from app.config import validate_production_settings
from app.security.http_hardening import MAX_REQUEST_BODY_BYTES, HttpHardeningMiddleware, _Window, websocket_origin_allowed


def _production(**overrides):
    values = {
        "app_env": "production",
        "jwt_secret_key": "Aa1!Bb2@Cc3#Dd4$Ee5%Ff6^Gg7&",
        "agent_require_tls": True,
        "linux_ssh_host_key_checking": True,
        "linux_ssh_known_hosts_path": "/tmp/nova-known-hosts",
        "cors_origins": ["https://console.example.com"],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_production_settings_accept_strong_secret_tls_and_https_origin():
    validate_production_settings(_production())


@pytest.mark.parametrize(
    "overrides",
    [
        {"jwt_secret_key": "short"},
        {"jwt_secret_key": "changeme"},
        {"jwt_secret_key": "a" * 64},
        {"agent_require_tls": False},
        {"agent_require_tls": None},
        {"linux_ssh_host_key_checking": False},
        {"linux_ssh_known_hosts_path": None},
        {"cors_origins": ["http://localhost:3000"]},
        {"cors_origins": ["https://console.example.com", "http://127.0.0.1:3000"]},
        {"cors_origins": []},
    ],
)
def test_production_settings_reject_unsafe_configuration(overrides):
    with pytest.raises(RuntimeError):
        validate_production_settings(_production(**overrides))


def test_development_settings_keep_legacy_local_configuration():
    validate_production_settings(
        SimpleNamespace(
            app_env="development",
            jwt_secret_key="dev",
            agent_require_tls=False,
            linux_ssh_host_key_checking=False,
            linux_ssh_known_hosts_path=None,
            cors_origins=["http://localhost:3000"],
        )
    )


def test_endpoint_rate_window_blocks_nth_request_and_resets():
    now = [100.0]
    limiter = _Window(2, 60.0, clock=lambda: now[0])

    assert limiter.hit("client") is True
    assert limiter.hit("client") is True
    assert limiter.hit("client") is False

    now[0] = 161.0
    assert limiter.hit("client") is True



def test_websocket_origin_policy_allows_native_agent_and_configured_browser():
    assert websocket_origin_allowed(None, ["https://console.example.com"])
    assert websocket_origin_allowed("https://console.example.com", ["https://console.example.com"])
    assert not websocket_origin_allowed("https://evil.example", ["https://console.example.com"])


def test_rate_window_caps_unique_client_keys():
    now = [1.0]
    limiter = _Window(1, 60.0, clock=lambda: now[0], max_keys=1)
    assert limiter.hit("first") is True
    assert limiter.hit("second") is False
    now[0] = 62.0
    assert limiter.hit("second") is True



@pytest.mark.asyncio
async def test_http_hardening_rejects_declared_oversized_body():
    sent = []

    async def app(scope, receive, send):
        raise AssertionError("downstream app must not be called")

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    middleware = HttpHardeningMiddleware(app)
    await middleware(
        {"type": "http", "path": "/upload", "headers": [
            (b"content-length", str(MAX_REQUEST_BODY_BYTES + 1).encode())
        ], "client": ("127.0.0.1", 1234)},
        receive, send,
    )
    assert sent[0]["status"] == 413


@pytest.mark.asyncio
async def test_http_hardening_rejects_chunked_oversized_body():
    sent = []

    async def app(scope, receive, send):
        await receive()

    async def receive():
        return {"type": "http.request", "body": b"x" * (MAX_REQUEST_BODY_BYTES + 1), "more_body": False}

    async def send(message):
        sent.append(message)

    middleware = HttpHardeningMiddleware(app)
    await middleware(
        {"type": "http", "path": "/upload", "headers": [], "client": ("127.0.0.1", 1234)},
        receive, send,
    )
    assert sent[0]["status"] == 413
