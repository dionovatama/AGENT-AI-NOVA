"""
Tests for Authorization Boundary & Policy Checks (READ, MODIFY, HIGH_RISK).

Covers:
5. Authenticated READ tool -> allowed if tool is permitted
6. MODIFY tool without confirmation -> denied (403)
7. HIGH_RISK tool without confirmation -> denied (403)
- Explicit confirmation as action approval signal, NOT identity.
- Inactive user rejection.
"""

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.database.models import User
from app.database.session import SessionLocal
from app.main import app
from app.security.authorization import AuthorizationError, authorize_tool_execution
from app.security.hashing import create_access_token
from app.tools.manager import tool_manager
from app.tools.schemas import LoggingPolicy, PermissionLevel, RiskLevel, ToolDefinition, ToolRequest

client = TestClient(app)


class MockInput(BaseModel):
    command: str = "default"


class MockOutput(BaseModel):
    result: str = "ok"


@pytest.fixture(scope="module")
def setup_test_tools():
    """Register dummy tools for testing MODIFY and HIGH_RISK policies."""
    async def mock_exec(inp: MockInput) -> MockOutput:
        return MockOutput(result=f"executed_{inp.command}")

    read_tool = ToolDefinition(
        name="test.read_tool",
        description="Test READ",
        input_model=MockInput,
        output_model=MockOutput,
        permission_level=PermissionLevel.READ,
        risk_level=RiskLevel.LOW,
        supported_platforms=["linux"],
        executor=mock_exec,
    )
    modify_tool = ToolDefinition(
        name="test.modify_tool",
        description="Test MODIFY",
        input_model=MockInput,
        output_model=MockOutput,
        permission_level=PermissionLevel.MODIFY,
        risk_level=RiskLevel.MEDIUM,
        supported_platforms=["linux"],
        executor=mock_exec,
    )
    high_risk_tool = ToolDefinition(
        name="test.high_risk_tool",
        description="Test HIGH_RISK",
        input_model=MockInput,
        output_model=MockOutput,
        permission_level=PermissionLevel.HIGH_RISK,
        risk_level=RiskLevel.HIGH,
        supported_platforms=["linux"],
        executor=mock_exec,
    )

    tool_manager._registry["test.read_tool"] = read_tool
    tool_manager._registry["test.modify_tool"] = modify_tool
    tool_manager._registry["test.high_risk_tool"] = high_risk_tool

    yield

    tool_manager._registry.pop("test.read_tool", None)
    tool_manager._registry.pop("test.modify_tool", None)
    tool_manager._registry.pop("test.high_risk_tool", None)


def _get_auth_headers(is_active: bool = True) -> tuple[dict[str, str], uuid.UUID]:
    uid = uuid.uuid4()
    db = SessionLocal()
    try:
        user = User(
            id=uid,
            email=f"auth-test-{uid.hex[:8]}@example.com",
            hashed_password="placeholder_hash",
            is_active=is_active,
        )
        db.add(user)
        db.commit()
    finally:
        db.close()

    token = create_access_token(subject=str(uid))
    return {"Authorization": f"Bearer {token}"}, uid


# ============================================================
# Unit Tests for authorize_tool_execution
# ============================================================

def test_authorize_read_allowed():
    user = User(id=uuid.uuid4(), email="user@test.com", is_active=True)
    # Should not raise
    authorize_tool_execution(user, "test.read_tool", PermissionLevel.READ, confirmed=False)


def test_authorize_modify_requires_confirmation():
    user = User(id=uuid.uuid4(), email="user@test.com", is_active=True)
    with pytest.raises(AuthorizationError) as exc_info:
        authorize_tool_execution(user, "test.modify_tool", PermissionLevel.MODIFY, confirmed=False)
    assert "memerlukan confirmation" in str(exc_info.value)

    # Allowed when confirmed=True
    authorize_tool_execution(user, "test.modify_tool", PermissionLevel.MODIFY, confirmed=True)


def test_authorize_high_risk_requires_confirmation():
    user = User(id=uuid.uuid4(), email="user@test.com", is_active=True)
    with pytest.raises(AuthorizationError) as exc_info:
        authorize_tool_execution(user, "test.high_risk_tool", PermissionLevel.HIGH_RISK, confirmed=False)
    assert "HIGH_RISK" in str(exc_info.value)

    # Allowed when confirmed=True
    authorize_tool_execution(user, "test.high_risk_tool", PermissionLevel.HIGH_RISK, confirmed=True)


def test_authorize_inactive_user_rejected():
    inactive_user = User(id=uuid.uuid4(), email="inactive@test.com", is_active=False)
    with pytest.raises(AuthorizationError) as exc_info:
        authorize_tool_execution(inactive_user, "test.read_tool", PermissionLevel.READ, confirmed=False)
    assert "tidak aktif" in str(exc_info.value)


# ============================================================
# HTTP API Tests
# ============================================================

def test_api_read_tool_allowed(setup_test_tools):
    """5. Authenticated READ tool -> allowed if tool is permitted."""
    headers, _ = _get_auth_headers()
    response = client.post(
        "/tools/execute",
        headers=headers,
        json={"tool_name": "test.read_tool", "arguments": {"command": "check"}, "confirmed": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["output"]["result"] == "executed_check"


def test_api_modify_tool_without_confirmation_denied(setup_test_tools):
    """6. MODIFY tool without confirmation -> denied (403)."""
    headers, _ = _get_auth_headers()
    response = client.post(
        "/tools/execute",
        headers=headers,
        json={"tool_name": "test.modify_tool", "arguments": {"command": "change"}, "confirmed": False},
    )
    assert response.status_code == 403
    assert "MODIFY" in response.json()["detail"]


def test_api_modify_tool_with_confirmation_allowed(setup_test_tools):
    headers, _ = _get_auth_headers()
    response = client.post(
        "/tools/execute",
        headers=headers,
        json={"tool_name": "test.modify_tool", "arguments": {"command": "change"}, "confirmed": True},
    )
    assert response.status_code == 200
    assert response.json()["success"] is True


def test_api_high_risk_tool_without_confirmation_denied(setup_test_tools):
    """7. HIGH_RISK tool without confirmation -> denied (403)."""
    headers, _ = _get_auth_headers()
    response = client.post(
        "/tools/execute",
        headers=headers,
        json={"tool_name": "test.high_risk_tool", "arguments": {"command": "critical"}, "confirmed": False},
    )
    assert response.status_code == 403
    assert "HIGH_RISK" in response.json()["detail"]


def test_api_high_risk_tool_with_confirmation_allowed(setup_test_tools):
    headers, _ = _get_auth_headers()
    response = client.post(
        "/tools/execute",
        headers=headers,
        json={"tool_name": "test.high_risk_tool", "arguments": {"command": "critical"}, "confirmed": True},
    )
    assert response.status_code == 200
    assert response.json()["success"] is True
