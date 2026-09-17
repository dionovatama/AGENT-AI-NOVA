"""
Tests for Persistent Audit Logging and Zero Secret Exposure.

Covers:
10. Successful tool execution creates persistent audit record.
11. Failed tool execution creates persistent audit record.
12. Denied execution creates persistent audit record.
13. Audit record contains authenticated user ID.
14. Audit record does NOT contain passwords, private keys, tokens, JWTs, secrets.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.database.models import AuditLog, User
from app.database.session import SessionLocal
from app.main import app
from app.security.hashing import create_access_token
from app.security.sanitization import sanitize_error_message, sanitize_metadata
from app.tools.manager import tool_manager
from app.tools.schemas import PermissionLevel, RiskLevel, ToolDefinition

client = TestClient(app)


class AuditInput(BaseModel):
    action: str
    password: str | None = None
    api_key: str | None = None
    private_key: str | None = None
    token: str | None = None


class AuditOutput(BaseModel):
    status: str


@pytest.fixture(scope="module")
def setup_audit_tools():
    async def successful_exec(inp: AuditInput) -> AuditOutput:
        return AuditOutput(status=f"ok_{inp.action}")

    async def failing_exec(inp: AuditInput) -> AuditOutput:
        raise RuntimeError("Internal hardware connection failure to host: 10.0.0.1")

    tool_manager._registry["test.audit_success"] = ToolDefinition(
        name="test.audit_success",
        description="Audit success tool",
        input_model=AuditInput,
        output_model=AuditOutput,
        permission_level=PermissionLevel.READ,
        risk_level=RiskLevel.LOW,
        supported_platforms=["linux"],
        executor=successful_exec,
    )

    tool_manager._registry["test.audit_fail"] = ToolDefinition(
        name="test.audit_fail",
        description="Audit fail tool",
        input_model=AuditInput,
        output_model=AuditOutput,
        permission_level=PermissionLevel.READ,
        risk_level=RiskLevel.LOW,
        supported_platforms=["linux"],
        executor=failing_exec,
    )

    tool_manager._registry["test.audit_modify"] = ToolDefinition(
        name="test.audit_modify",
        description="Audit modify tool",
        input_model=AuditInput,
        output_model=AuditOutput,
        permission_level=PermissionLevel.MODIFY,
        risk_level=RiskLevel.MEDIUM,
        supported_platforms=["linux"],
        executor=successful_exec,
    )

    yield

    tool_manager._registry.pop("test.audit_success", None)
    tool_manager._registry.pop("test.audit_fail", None)
    tool_manager._registry.pop("test.audit_modify", None)


def _get_auth_headers() -> tuple[dict[str, str], uuid.UUID]:
    uid = uuid.uuid4()
    db = SessionLocal()
    try:
        user = User(
            id=uid,
            email=f"audit-tester-{uid.hex[:8]}@example.com",
            hashed_password="placeholder_hash",
            is_active=True,
        )
        db.add(user)
        db.commit()
    finally:
        db.close()

    token = create_access_token(subject=str(uid))
    return {"Authorization": f"Bearer {token}"}, uid


# ============================================================
# Sanitization Unit Tests (Phase 4, 14)
# ============================================================

def test_sanitization_redacts_sensitive_keys():
    """14. Audit record does NOT contain secrets/passwords."""
    raw_metadata = {
        "device_name": "router-1",
        "password": "SuperSecretPassword123!",
        "api_key": "sk-or-v1-abcdef123456",
        "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----",
        "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHw",
        "safe_param": 42,
        "nested": {
            "admin_secret": "my-secret",
            "normal_field": "ok",
        },
    }

    sanitized = sanitize_metadata(raw_metadata)

    assert sanitized["device_name"] == "router-1"
    assert sanitized["safe_param"] == 42
    assert sanitized["nested"]["normal_field"] == "ok"

    # All sensitive keys must be redacted
    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["private_key"] == "[REDACTED]"
    assert sanitized["access_token"] == "[REDACTED]"
    assert sanitized["nested"]["admin_secret"] == "[REDACTED]"


def test_sanitization_cleans_sensitive_errors():
    error_with_db = "OperationalError: could not connect to postgresql://postgres:SecretDBPass123@localhost:5432/nova_db"
    cleaned = sanitize_error_message(error_with_db)
    assert "SecretDBPass123" not in cleaned
    assert "[REDACTED]" in cleaned


# ============================================================
# Persistent Audit Lifecycle Integration Tests (Phase 4, 5)
# ============================================================

def test_successful_execution_creates_audit_record(setup_audit_tools):
    """10. Successful tool execution creates persistent audit record.
       13. Audit record contains authenticated user ID."""
    headers, uid = _get_auth_headers()
    res = client.post(
        "/tools/execute",
        headers=headers,
        json={"tool_name": "test.audit_success", "arguments": {"action": "check_status"}, "confirmed": False},
    )
    assert res.status_code == 200

    db = SessionLocal()
    try:
        log_entry = (
            db.query(AuditLog)
            .filter(AuditLog.user_id == uid, AuditLog.tool_name == "test.audit_success")
            .first()
        )
        assert log_entry is not None
        assert log_entry.result_status == "SUCCESS"
        assert log_entry.action == "tool.execute"
        assert log_entry.user_id == uid
        assert log_entry.request_metadata["action"] == "check_status"
        assert log_entry.duration_ms is not None
        assert log_entry.error_message is None
    finally:
        db.close()


def test_failed_execution_creates_audit_record(setup_audit_tools):
    """11. Failed tool execution creates persistent audit record."""
    headers, uid = _get_auth_headers()
    res = client.post(
        "/tools/execute",
        headers=headers,
        json={"tool_name": "test.audit_fail", "arguments": {"action": "trigger_failure"}, "confirmed": False},
    )
    assert res.status_code == 502

    db = SessionLocal()
    try:
        log_entry = (
            db.query(AuditLog)
            .filter(AuditLog.user_id == uid, AuditLog.tool_name == "test.audit_fail")
            .first()
        )
        assert log_entry is not None
        assert log_entry.result_status == "FAILED"
        assert "Internal hardware connection failure" in log_entry.error_message
    finally:
        db.close()


def test_denied_execution_creates_audit_record(setup_audit_tools):
    """12. Denied execution creates persistent audit record."""
    headers, uid = _get_auth_headers()
    res = client.post(
        "/tools/execute",
        headers=headers,
        json={"tool_name": "test.audit_modify", "arguments": {"action": "unconfirmed_action"}, "confirmed": False},
    )
    assert res.status_code == 403

    db = SessionLocal()
    try:
        log_entry = (
            db.query(AuditLog)
            .filter(AuditLog.user_id == uid, AuditLog.tool_name == "test.audit_modify")
            .first()
        )
        assert log_entry is not None
        assert log_entry.result_status == "DENIED"
        assert "memerlukan confirmation" in log_entry.error_message
    finally:
        db.close()


def test_secrets_never_enter_audit_records(setup_audit_tools):
    """14. Audit record does NOT contain secrets even if client sent them."""
    headers, uid = _get_auth_headers()
    raw_secret = "UltraSecretPassword999!"
    raw_api_key = "sk-live-999988887777"

    res = client.post(
        "/tools/execute",
        headers=headers,
        json={
            "tool_name": "test.audit_success",
            "arguments": {
                "action": "login_attempt",
                "password": raw_secret,
                "api_key": raw_api_key,
            },
            "confirmed": False,
        },
    )
    assert res.status_code == 200

    db = SessionLocal()
    try:
        log_entry = (
            db.query(AuditLog)
            .filter(AuditLog.user_id == uid, AuditLog.tool_name == "test.audit_success")
            .order_by(AuditLog.created_at.desc())
            .first()
        )
        assert log_entry is not None
        metadata = log_entry.request_metadata

        # Plaintext secrets must NOT be in the DB
        assert raw_secret not in str(metadata)
        assert raw_api_key not in str(metadata)
        assert metadata["password"] == "[REDACTED]"
        assert metadata["api_key"] == "[REDACTED]"
    finally:
        db.close()
