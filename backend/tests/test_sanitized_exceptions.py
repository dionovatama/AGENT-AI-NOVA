import logging
import uuid
import pytest
from starlette.testclient import TestClient

from app.main import app, fastapi_app
from app.database.models import User, Device
from app.security.hashing import create_access_token
from app.security.sanitization import format_safe_exception_response
from app.tools.mikrotik import (
    _connection_error_message,
    _api_error_message,
)
from app.ai.openrouter import OpenRouterError


def test_format_safe_exception_response_helper():
    exc = ValueError("sensitive internal db string")
    safe = format_safe_exception_response(exc, prefix="Action failed")
    assert safe == "Action failed [ValueError]"
    assert "sensitive" not in safe


def test_mikrotik_tool_error_messages_sanitize_exceptions(caplog):
    with caplog.at_level(logging.WARNING):
        raw_exc = ConnectionRefusedError("sensitive_token_12345 to 192.168.1.1:8728")
        msg = _connection_error_message(raw_exc)
        assert msg == "Connection error [ConnectionRefusedError]"
        assert "sensitive_token_12345" not in msg

        api_exc = RuntimeError("internal sensitive query text")
        api_msg = _api_error_message(api_exc)
        assert api_msg == "RouterOS API error [RuntimeError]"
        assert "sensitive" not in api_msg


def test_mikrotik_monitoring_502_sanitized_response(monkeypatch, caplog):
    client = TestClient(app)
    user_id = uuid.uuid4()
    device_id = uuid.uuid4()
    token = create_access_token(subject=str(user_id))

    test_user = User(id=user_id, email="mon-sanitized@nova.corp", is_active=True)
    test_device = Device(
        id=device_id,
        owner_id=user_id,
        name="Router-Test",
        platform="mikrotik",
        connection_type="api-ssl",
        host="10.0.0.1",
        port=8729,
    )

    from app.security.dependencies import get_current_user
    fastapi_app.dependency_overrides[get_current_user] = lambda: test_user

    from app.database.session import get_db
    class MockDb:
        def query(self, model):
            return self
        def filter(self, *args, **kwargs):
            return self
        def first(self):
            return test_device
        def rollback(self):
            pass

    fastapi_app.dependency_overrides[get_db] = lambda: MockDb()
    monkeypatch.setattr("app.api.mikrotik_monitoring.build_device_context", lambda *a, **k: object())

    # Mock _run_on_device to raise an exception containing sensitive leak simulation
    async def _mock_run(*args, **kwargs):
        raise RuntimeError("LEAKED_CREDENTIAL_DATA: password=supersecretpass")

    monkeypatch.setattr("app.api.mikrotik_monitoring._run_on_device", _mock_run)

    try:
        with caplog.at_level(logging.ERROR):
            res = client.get(
                f"/devices/{device_id}/monitoring",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert res.status_code == 502
            detail = res.json()["detail"]
            assert detail == "RouterOS monitoring failed [RuntimeError]"
            assert "LEAKED_CREDENTIAL_DATA" not in detail
            assert "supersecretpass" not in detail

            # Verify that the server log recorded the full exception
            assert any("LEAKED_CREDENTIAL_DATA" in record.message or (record.exc_info and "LEAKED_CREDENTIAL_DATA" in str(record.exc_info)) for record in caplog.records)
    finally:
        fastapi_app.dependency_overrides.pop(get_current_user, None)
        fastapi_app.dependency_overrides.pop(get_db, None)


def test_chat_openrouter_502_sanitized_response(monkeypatch, caplog):
    client = TestClient(app)
    user_id = uuid.uuid4()
    token = create_access_token(subject=str(user_id))
    test_user = User(id=user_id, email="chat-sanitized@nova.corp", is_active=True)

    from app.security.dependencies import get_current_user
    fastapi_app.dependency_overrides[get_current_user] = lambda: test_user

    async def _mock_bad_completion(*args, **kwargs):
        raise OpenRouterError("401 Unauthorized: Authorization token sk-or-v1-secret-key is invalid")

    monkeypatch.setattr("app.api.chat.get_completion", _mock_bad_completion)

    try:
        with caplog.at_level(logging.ERROR):
            res = client.post(
                "/chat/completions",
                headers={"Authorization": f"Bearer {token}"},
                json={"message": "hello"},
            )
            assert res.status_code == 502
            detail = res.json()["detail"]
            assert detail == "AI Gateway request failed [OpenRouterError]"
            assert "sk-or-v1-secret-key" not in detail
    finally:
        fastapi_app.dependency_overrides.pop(get_current_user, None)
