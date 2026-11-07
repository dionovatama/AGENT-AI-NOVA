import uuid
import pytest
from starlette.testclient import TestClient

from app.main import app, fastapi_app
from app.config import settings
from app.database.session import get_db
from app.database.models import User
from app.security.hashing import hash_password, create_access_token
from app.security.rate_limiter import (
    auth_login_limiter,
    auth_register_limiter,
    chat_limiter,
    tools_execute_limiter,
    monitoring_limiter,
)


def _from_peer(asgi_app, host: str = "10.0.0.2", port: int = 50000):
    """Bungkus app ASGI agar peer soket terlihat berasal dari ``host``.

    TestClient versi lama tidak punya parameter ``client=`` dan peer-nya selalu
    "testclient" (bukan IP), sehingga X-Forwarded-For tidak pernah dipercaya. Pembungkus ini
    mengisi scope["client"] dengan IP proxy, jadi logika kepercayaan asli yang diuji.
    """
    async def wrapped(scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            scope = {**scope, "client": (host, port)}
        await asgi_app(scope, receive, send)

    return wrapped


@pytest.fixture(autouse=True)
def reset_limiters():
    auth_login_limiter.reset()
    auth_register_limiter.reset()
    chat_limiter.reset()
    tools_execute_limiter.reset()
    monitoring_limiter.reset()
    yield
    auth_login_limiter.reset()
    auth_register_limiter.reset()
    chat_limiter.reset()
    tools_execute_limiter.reset()
    monitoring_limiter.reset()


def test_auth_login_rate_limit(monkeypatch):
    # XFF hanya dipercaya bila peer soket adalah proxy tepercaya. Tanpa ini semua request
    # dianggap satu IP ("testclient"), sehingga IP lain pun kena 429.
    monkeypatch.setattr(settings, "trusted_proxy_ips", ["10.0.0.0/8"])
    client = TestClient(_from_peer(app))
    # Temporarily set a low limit for fast testing
    orig_limit = settings.rate_limit_auth_login_limit
    settings.rate_limit_auth_login_limit = 3
    try:
        # 3 allowed requests
        for i in range(3):
            res = client.post(
                "/auth/login",
                json={"email": f"user{i}@example.com", "password": "wrongpassword"},
                headers={"X-Forwarded-For": "198.51.100.1"},
            )
            assert res.status_code == 401

        # 4th request must be rate-limited (429)
        res4 = client.post(
            "/auth/login",
            json={"email": "user@example.com", "password": "wrongpassword"},
            headers={"X-Forwarded-For": "198.51.100.1"},
        )
        assert res4.status_code == 429
        assert "Rate limit exceeded" in res4.json()["detail"]
        assert "Retry-After" in res4.headers

        # Another IP should not be blocked
        res_other = client.post(
            "/auth/login",
            json={"email": "user@example.com", "password": "wrongpassword"},
            headers={"X-Forwarded-For": "198.51.100.2"},
        )
        assert res_other.status_code == 401
    finally:
        settings.rate_limit_auth_login_limit = orig_limit


def test_auth_register_rate_limit(monkeypatch):
    monkeypatch.setattr(settings, "public_registration_enabled", True)
    monkeypatch.setattr(settings, "trusted_proxy_ips", ["10.0.0.0/8"])
    client = TestClient(_from_peer(app))
    orig_limit = settings.rate_limit_auth_register_limit
    settings.rate_limit_auth_register_limit = 2
    try:
        for i in range(2):
            res = client.post(
                "/auth/register",
                json={"email": f"unique_{uuid.uuid4()}@example.com", "password": "securepassword123"},
                headers={"X-Forwarded-For": "203.0.113.5"},
            )
            assert res.status_code in (201, 409)

        # 3rd request from same IP is rate-limited
        res3 = client.post(
            "/auth/register",
            json={"email": f"unique_{uuid.uuid4()}@example.com", "password": "securepassword123"},
            headers={"X-Forwarded-For": "203.0.113.5"},
        )
        assert res3.status_code == 429
        assert "Rate limit exceeded" in res3.json()["detail"]
        assert "Retry-After" in res3.headers
    finally:
        settings.rate_limit_auth_register_limit = orig_limit


def test_chat_completions_rate_limit(monkeypatch):
    client = TestClient(app)
    orig_limit = settings.rate_limit_chat_limit
    settings.rate_limit_chat_limit = 2
    try:
        # Create a test user token
        user_id = uuid.uuid4()
        token = create_access_token(subject=str(user_id))

        # Mock get_current_user to return mock user without DB lookup
        test_user = User(id=user_id, email="chat-rate@nova.corp", is_active=True)
        from app.security.dependencies import get_current_user
        fastapi_app.dependency_overrides[get_current_user] = lambda: test_user

        # Mock get_completion
        from app.ai.openrouter import ChatCompletionResult
        async def _fake_completion(*args, **kwargs):
            return ChatCompletionResult(
                content="mock reply",
                model_used="test",
                category="general_chat",
                used_fallback=False,
                prompt_tokens=10,
                completion_tokens=10,
                total_tokens=20,
            )
        monkeypatch.setattr("app.api.chat.get_completion", _fake_completion)

        headers = {"Authorization": f"Bearer {token}"}
        # Hit 1 & 2
        for _ in range(2):
            res = client.post("/chat/completions", headers=headers, json={"message": "hello"})
            assert res.status_code == 200

        # Hit 3 -> 429
        res3 = client.post("/chat/completions", headers=headers, json={"message": "hello again"})
        assert res3.status_code == 429
        assert "Rate limit exceeded" in res3.json()["detail"]
    finally:
        fastapi_app.dependency_overrides.pop(get_current_user, None)
        settings.rate_limit_chat_limit = orig_limit


def test_tools_execute_rate_limit():
    client = TestClient(app)
    orig_limit = settings.rate_limit_tools_execute_limit
    settings.rate_limit_tools_execute_limit = 2
    try:
        user_id = uuid.uuid4()
        token = create_access_token(subject=str(user_id))
        test_user = User(id=user_id, email="tool-rate@nova.corp", is_active=True)
        from app.security.dependencies import get_current_user
        fastapi_app.dependency_overrides[get_current_user] = lambda: test_user

        headers = {"Authorization": f"Bearer {token}"}
        # Hit 1 & 2
        for _ in range(2):
            res = client.post("/tools/execute", headers=headers, json={"tool_name": "ping", "parameters": {"host": "127.0.0.1"}})
            assert res.status_code in (200, 400, 422, 502)

        # Hit 3 -> 429
        res3 = client.post("/tools/execute", headers=headers, json={"tool_name": "ping", "parameters": {"host": "127.0.0.1"}})
        assert res3.status_code == 429
        assert "Rate limit exceeded" in res3.json()["detail"]
    finally:
        fastapi_app.dependency_overrides.pop(get_current_user, None)
        settings.rate_limit_tools_execute_limit = orig_limit


def test_monitoring_rate_limit():
    client = TestClient(app)
    orig_limit = settings.rate_limit_monitoring_limit
    settings.rate_limit_monitoring_limit = 2
    try:
        user_id = uuid.uuid4()
        token = create_access_token(subject=str(user_id))
        test_user = User(id=user_id, email="mon-rate@nova.corp", is_active=True)
        from app.security.dependencies import get_current_user
        fastapi_app.dependency_overrides[get_current_user] = lambda: test_user

        headers = {"Authorization": f"Bearer {token}"}
        random_device_id = str(uuid.uuid4())

        # Hit 1 & 2 -> 404 because device doesn't exist, but rate limiter still registers
        for _ in range(2):
            res = client.get(f"/devices/{random_device_id}/monitoring", headers=headers)
            assert res.status_code == 404

        # Hit 3 -> 429
        res3 = client.get(f"/devices/{random_device_id}/monitoring", headers=headers)
        assert res3.status_code == 429
        assert "Rate limit exceeded" in res3.json()["detail"]
    finally:
        fastapi_app.dependency_overrides.pop(get_current_user, None)
        settings.rate_limit_monitoring_limit = orig_limit
