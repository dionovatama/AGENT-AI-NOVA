"""
Test endpoint /images/generate — Cloudflare dimock penuh, TIDAK memanggil
API sungguhan (tidak memakai jatah neurons, tidak butuh token).
get_current_user di-override agar tidak butuh PostgreSQL.
"""

import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import images as images_module
from app.main import app
from app.security.dependencies import get_current_user


class _FakeUser:
    id = uuid.uuid4()


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: _FakeUser()
    monkeypatch.setattr(images_module.settings, "cloudflare_account_id", "acc123", raising=False)
    monkeypatch.setattr(images_module.settings, "cloudflare_api_token", "tok-secret", raising=False)
    monkeypatch.setattr(images_module.settings, "image_model", "@cf/black-forest-labs/flux-1-schnell", raising=False)
    images_module._recent_requests.clear()
    yield
    app.dependency_overrides.clear()


client = TestClient(app)


def _resp(status_code: int, body: dict | None):
    req = httpx.Request("POST", "https://api.cloudflare.com/x")
    return httpx.Response(status_code, json=body, request=req)


def test_success_returns_data_url():
    ok = _resp(200, {"success": True, "result": {"image": "/9j/AAAA"}, "errors": []})
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=ok):
        r = client.post("/images/generate", json={"prompt": "a red apple"})
    assert r.status_code == 200
    assert r.json()["image_data_url"].startswith("data:image/jpeg;base64,")


def test_token_never_in_response():
    ok = _resp(200, {"success": True, "result": {"image": "iVBORAAAA"}, "errors": []})
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=ok):
        r = client.post("/images/generate", json={"prompt": "x"})
    assert "tok-secret" not in r.text
    assert r.json()["image_data_url"].startswith("data:image/png;base64,")


def test_missing_config_returns_503(monkeypatch):
    monkeypatch.setattr(images_module.settings, "cloudflare_api_token", None, raising=False)
    r = client.post("/images/generate", json={"prompt": "x"})
    assert r.status_code == 503
    assert "[CONFIG]" in r.json()["detail"]


def test_auth_error_labelled():
    bad = _resp(403, {"success": False, "errors": [{"code": 10000, "message": "Authentication error"}]})
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=bad):
        r = client.post("/images/generate", json={"prompt": "x"})
    assert r.status_code == 502
    assert r.json()["detail"].startswith("[AUTH]")
    assert "tok-secret" not in r.text


def test_quota_error_labelled():
    bad = _resp(400, {"success": False, "errors": [{"code": 4006, "message": "daily free allocation of neurons exceeded"}]})
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=bad):
        r = client.post("/images/generate", json={"prompt": "x"})
    assert r.status_code == 429
    assert r.json()["detail"].startswith("[QUOTA]")


def test_timeout_labelled():
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=httpx.TimeoutException("t")):
        r = client.post("/images/generate", json={"prompt": "x"})
    assert r.status_code == 504
    assert r.json()["detail"].startswith("[TIMEOUT]")


def test_success_flag_without_image_is_failure():
    weird = _resp(200, {"success": True, "result": {}, "errors": []})
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=weird):
        r = client.post("/images/generate", json={"prompt": "x"})
    assert r.status_code == 502


def test_prompt_too_long_rejected_before_provider():
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as m:
        r = client.post("/images/generate", json={"prompt": "a" * 2001})
    assert r.status_code == 422
    m.assert_not_called()


def test_rate_limit_kicks_in():
    ok = _resp(200, {"success": True, "result": {"image": "/9j/AAAA"}, "errors": []})
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=ok):
        codes = [client.post("/images/generate", json={"prompt": "x"}).status_code for _ in range(11)]
    assert codes[:10] == [200] * 10
    assert codes[10] == 429


def test_requires_auth():
    app.dependency_overrides.clear()
    r = client.post("/images/generate", json={"prompt": "x"})
    assert r.status_code in (401, 403)