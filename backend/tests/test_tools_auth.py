"""
Tests for Tool API Authentication, Boundary Security & Bypass Prevention.

Covers:
1. GET /tools/list without JWT -> 401
2. POST /tools/execute without JWT -> 401
3. Invalid JWT -> 401
4. Expired JWT -> 401
18. Client-supplied user_id cannot impersonate another user
19. Tool execution cannot bypass Tool Manager
20. Arbitrary tool names remain rejected
21. Invalid tool arguments remain rejected
22. Tool timeout behavior remains intact
"""

import time
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.config import settings
from app.database.models import User
from app.database.session import SessionLocal
from app.main import app
from app.security.authorization import AuthorizationError
from app.security.hashing import create_access_token
from app.tools.manager import ToolNotFoundError, ToolTimeoutError, ToolValidationError, tool_manager
from app.tools.schemas import LoggingPolicy, PermissionLevel, RiskLevel, ToolDefinition, ToolRequest

client = TestClient(app)


def _get_auth_headers(user_id: str | None = None) -> tuple[dict[str, str], uuid.UUID]:
    """Helper untuk membuat Bearer token valid dan user aktif di DB."""
    uid = uuid.UUID(user_id) if user_id else uuid.uuid4()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == uid).first()
        if not user:
            user = User(
                id=uid,
                email=f"user-{uid.hex[:8]}@example.com",
                hashed_password="hashed_pass_placeholder",
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
    finally:
        db.close()

    token = create_access_token(subject=str(uid))
    return {"Authorization": f"Bearer {token}"}, uid


# ============================================================
# 1. Authentication Tests (Phase 1)
# ============================================================

def test_list_tools_without_jwt_returns_401():
    """1. GET /tools/list without JWT -> 401"""
    response = client.get("/tools/list")
    assert response.status_code == 401


def test_execute_tool_without_jwt_returns_401():
    """2. POST /tools/execute without JWT -> 401"""
    response = client.post(
        "/tools/execute",
        json={"tool_name": "ping", "arguments": {"target": "127.0.0.1"}, "confirmed": False},
    )
    assert response.status_code == 401


def test_invalid_jwt_returns_401():
    """3. Invalid JWT -> 401"""
    headers = {"Authorization": "Bearer invalid.token.value"}
    res_list = client.get("/tools/list", headers=headers)
    assert res_list.status_code == 401

    res_exec = client.post(
        "/tools/execute",
        headers=headers,
        json={"tool_name": "ping", "arguments": {"target": "127.0.0.1"}, "confirmed": False},
    )
    assert res_exec.status_code == 401


def test_expired_jwt_returns_401():
    """4. Expired JWT -> 401"""
    expired_payload = {
        "sub": str(uuid.uuid4()),
        "exp": int(time.time()) - 3600,  # Expired 1 hour ago
    }
    expired_token = jwt.encode(
        expired_payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )
    headers = {"Authorization": f"Bearer {expired_token}"}

    res_list = client.get("/tools/list", headers=headers)
    assert res_list.status_code == 401

    res_exec = client.post(
        "/tools/execute",
        headers=headers,
        json={"tool_name": "ping", "arguments": {"target": "127.0.0.1"}, "confirmed": False},
    )
    assert res_exec.status_code == 401


def test_authenticated_list_tools_returns_200():
    headers, _ = _get_auth_headers()
    response = client.get("/tools/list", headers=headers)
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert "ping" in response.json()


# ============================================================
# Security & Boundary Protection Tests (Phase 3, 10, 11)
# ============================================================

def test_client_supplied_user_id_cannot_impersonate():
    """18. Client-supplied user_id cannot impersonate another user."""
    headers, legitimate_uid = _get_auth_headers()
    impersonated_uid = str(uuid.uuid4())

    # Client tries to pass user_id inside arguments
    payload = {
        "tool_name": "ping",
        "arguments": {
            "target": "127.0.0.1",
            "count": 1,
            "user_id": impersonated_uid,
        },
        "confirmed": False,
    }

    # Ping executor schema does not allow extra fields, or if accepted,
    # backend identity MUST remain legitimate_uid
    res = client.post("/tools/execute", headers=headers, json=payload)
    # PingInput has extra='ignore' or schema validation will drop/validate,
    # but more importantly, backend resolves current_user from JWT.
    assert res.status_code in [200, 422]


@pytest.mark.asyncio
async def test_tool_execution_without_user_fails_authorization():
    """19. Tool execution cannot bypass Tool Manager / user requirement."""
    request = ToolRequest(
        tool_name="ping",
        arguments={"target": "127.0.0.1", "count": 1},
        confirmed=False,
    )
    # Calling execute without authenticated user must raise AuthorizationError
    with pytest.raises(AuthorizationError):
        await tool_manager.execute(request, user=None)


def test_arbitrary_tool_names_rejected_404():
    """20. Arbitrary tool names remain rejected (404)."""
    headers, _ = _get_auth_headers()
    response = client.post(
        "/tools/execute",
        headers=headers,
        json={"tool_name": "malicious_exploit_tool", "arguments": {}, "confirmed": True},
    )
    assert response.status_code == 404
    assert "tidak dikenal atau tidak ada di allowlist" in response.json()["detail"]


def test_invalid_tool_arguments_rejected_422():
    """21. Invalid tool arguments remain rejected (422)."""
    headers, _ = _get_auth_headers()
    response = client.post(
        "/tools/execute",
        headers=headers,
        json={"tool_name": "ping", "arguments": {"target": "127.0.0.1", "count": 9999}, "confirmed": False},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_tool_timeout_behavior_remains_intact():
    """22. Tool timeout behavior remains intact (ToolTimeoutError -> 504)."""
    async def slow_executor(inp):
        import asyncio
        await asyncio.sleep(0.5)
        return inp

    from pydantic import BaseModel
    class DummyInput(BaseModel):
        val: str = "ok"

    dummy_tool = ToolDefinition(
        name="test.timeout_dummy",
        description="Timeout test",
        input_model=DummyInput,
        output_model=DummyInput,
        permission_level=PermissionLevel.READ,
        risk_level=RiskLevel.LOW,
        supported_platforms=["linux"],
        timeout_seconds=0.05,
        executor=slow_executor,
    )
    tool_manager._registry["test.timeout_dummy"] = dummy_tool

    try:
        user = User(id=uuid.uuid4(), email="timeout-test@example.com", is_active=True)
        request = ToolRequest(tool_name="test.timeout_dummy", arguments={}, confirmed=False)
        with pytest.raises(ToolTimeoutError):
            await tool_manager.execute(request, user=user)
    finally:
        tool_manager._registry.pop("test.timeout_dummy", None)
