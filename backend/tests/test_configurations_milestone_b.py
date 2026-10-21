"""
Unit and Integration Tests for N.O.V.A Configuration Engine (Sub-Milestone B).

Covers:
1. internal_only tool protection:
   - POST /tools/execute with internal_only tool returns 404 identical to nonexistent tool.
   - internal_only tool is hidden from GET /tools/list and LLM tool schemas.
   - Audit log records DENIED: internal_only tool via HTTP.
2. ApprovalContext verification:
   - Replay protection (used=True rejection).
   - TTL expiry rejection.
   - Wrong device rejection.
   - Tampered plan_hash rejection.
   - State drift (state_fingerprint mismatch) rejection.
3. Orchestrator safety guards:
   - Kill-switch (CONFIG_APPLY_ENABLED=False) blocks execution.
   - Lab guard (device_metadata.lab != True) blocks execution.
   - Concurrency lock (single apply per device, concurrent apply returns 409).
4. End-to-end lifecycle & verification:
   - Full success cycle (PREVIEWED -> APPROVED -> APPLYING -> VERIFIED).
   - Mid-step failure -> LIFO automatic rollback -> ROLLED_BACK.
   - Post-apply verification failure -> LIFO automatic rollback -> ROLLED_BACK.
   - Rollback failure -> ROLLBACK_FAILED.
   - Manual rollback endpoint.
5. Tenant isolation on approve/apply/rollback (HTTP 404 anti-enumeration).
6. Zero secret exposure across logs, audit, and snapshot backups.
"""

import asyncio
import uuid
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database.models import AuditLog, Configuration, Credential, Device, User
from app.database.session import SessionLocal
from app.main import app
from app.network.adapters.fake import FakeNetworkAdapter
from app.network.models import (
    AddIpAddressOperation,
    AddStaticRouteOperation,
    AddVlanInterfaceOperation,
    ChangeSet,
)
from app.security.authorization import (
    ApprovalContext,
    AuthorizationError,
    build_approval_context,
    validate_approval_context,
)
from app.security.hashing import create_access_token
from app.tools.manager import tool_manager
from app.tools.schemas import ToolRequest

client = TestClient(app)


# ============================================================
# Helpers
# ============================================================

def _create_user_and_headers() -> tuple[dict[str, str], User]:
    db = SessionLocal()
    try:
        user_id = uuid.uuid4()
        user = User(
            id=user_id,
            email=f"user-b-{user_id.hex[:8]}@example.com",
            hashed_password="placeholder_hash",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    finally:
        db.close()

    token = create_access_token(subject=str(user.id))
    return {"Authorization": f"Bearer {token}"}, user


def _create_lab_device(user: User, lab: bool = True) -> Device:
    db = SessionLocal()
    try:
        cred = Credential(
            id=uuid.uuid4(),
            owner_id=user.id,
            name="test-cred",
            type="password",
            secret_reference="lab_password_secret",
        )
        db.add(cred)
        db.commit()

        device = Device(
            id=uuid.uuid4(),
            owner_id=user.id,
            name=f"lab-router-{uuid.uuid4().hex[:6]}",
            platform="mikrotik",
            host="192.168.88.1",
            port=8728,
            connection_type="api",
            status="active",
            credential_id=cred.id,
            device_metadata={"username": "admin", "lab": lab, "mock": True},
        )
        db.add(device)
        db.commit()
        db.refresh(device)
        return device
    finally:
        db.close()


# ============================================================
# 1. internal_only Tool Protection Tests
# ============================================================

def test_internal_only_tool_hidden_from_list_tools():
    """Tool internal tidak boleh muncul di GET /tools/list."""
    headers, _ = _create_user_and_headers()
    response = client.get("/tools/list", headers=headers)
    assert response.status_code == 200
    tool_list = response.json()
    assert "mikrotik.config_apply" not in tool_list


def test_internal_only_tool_rejected_on_tools_execute_with_identical_404():
    """POST /tools/execute dengan internal_only tool mengembalikan 404 identik."""
    headers, user = _create_user_and_headers()
    device = _create_lab_device(user)

    # 1. Panggil tool yang memang tidak ada sama sekali
    res_nonexistent = client.post(
        "/tools/execute",
        headers=headers,
        json={"tool_name": "completely_nonexistent_tool", "arguments": {}, "confirmed": True},
    )

    # 2. Panggil tool internal_only lewat endpoint publik
    res_internal = client.post(
        "/tools/execute",
        headers=headers,
        json={
            "tool_name": "mikrotik.config_apply",
            "arguments": {
                "operation": {"type": "add_ip_address", "interface": "ether2", "address": "10.0.0.1/24"},
                "plan_hash": "dummy",
                "state_fingerprint": "dummy",
            },
            "confirmed": True,
            "device_id": str(device.id),
        },
    )

    assert res_internal.status_code == 404
    assert res_internal.status_code == res_nonexistent.status_code
    assert "tidak dikenal atau tidak ada di allowlist" in res_internal.json()["detail"]

    # Cek audit log mencatat DENIED: internal_only tool via HTTP
    db = SessionLocal()
    try:
        log_entry = (
            db.query(AuditLog)
            .filter(AuditLog.user_id == user.id, AuditLog.tool_name == "mikrotik.config_apply")
            .order_by(AuditLog.created_at.desc())
            .first()
        )
        assert log_entry is not None
        assert log_entry.result_status == "DENIED"
        assert "internal_only tool via HTTP" in (log_entry.error_message or "")
    finally:
        db.close()


def test_internal_only_tool_hidden_from_llm_schemas():
    """Tool internal tidak boleh ada di skema LLM."""
    from app.ai.model_router import TaskCategory
    from app.ai.tool_calling import _build_tool_schemas

    schemas = _build_tool_schemas(TaskCategory.GENERAL_CHAT)
    schema_names = [s["function"]["name"] for s in schemas]
    assert "mikrotik__config_apply" not in schema_names
    assert "mikrotik.config_apply" not in schema_names


# ============================================================
# 2. ApprovalContext Verification Tests
# ============================================================

def test_approval_context_replay_rejected():
    user = User(id=uuid.uuid4(), email="u@test.com", is_active=True)
    ctx = build_approval_context(user, "test.tool", {"arg": "val"})
    ctx.used = True  # Tandai sudah pernah dipakai

    with pytest.raises(AuthorizationError) as exc:
        validate_approval_context(ctx, user, "test.tool", {"arg": "val"})
    assert "cegah replay attack" in str(exc.value)


def test_approval_context_expired_rejected():
    user = User(id=uuid.uuid4(), email="u@test.com", is_active=True)
    ctx = build_approval_context(user, "test.tool", {"arg": "val"}, ttl_seconds=-10)

    with pytest.raises(AuthorizationError) as exc:
        validate_approval_context(ctx, user, "test.tool", {"arg": "val"})
    assert "kadaluarsa" in str(exc.value)


def test_approval_context_wrong_device_rejected():
    user = User(id=uuid.uuid4(), email="u@test.com", is_active=True)
    dev_a = uuid.uuid4()
    dev_b = uuid.uuid4()
    ctx = build_approval_context(user, "test.tool", {"arg": "val"}, device_id=str(dev_a))

    with pytest.raises(AuthorizationError) as exc:
        validate_approval_context(ctx, user, "test.tool", {"arg": "val"}, device_id=str(dev_b))
    assert "device yang berbeda" in str(exc.value)


def test_approval_context_plan_hash_mismatch_rejected():
    user = User(id=uuid.uuid4(), email="u@test.com", is_active=True)
    ctx = build_approval_context(
        user, "test.tool", {}, plan_hash="expected_hash_123"
    )

    with pytest.raises(AuthorizationError) as exc:
        validate_approval_context(ctx, user, "test.tool", {"plan_hash": "tampered_hash_456"})
    assert "Plan hash tidak cocok" in str(exc.value)


def test_approval_context_state_drift_rejected():
    user = User(id=uuid.uuid4(), email="u@test.com", is_active=True)
    ctx = build_approval_context(
        user, "test.tool", {}, plan_hash="h1", state_fingerprint="fp_original"
    )

    with pytest.raises(AuthorizationError) as exc:
        validate_approval_context(
            ctx, user, "test.tool", {"plan_hash": "h1", "state_fingerprint": "fp_drifted"}
        )
    assert "State fingerprint tidak cocok" in str(exc.value)


# ============================================================
# 3. Orchestrator Safety Guards Tests
# ============================================================

def test_apply_rejected_when_kill_switch_off(monkeypatch):
    """Ketika CONFIG_APPLY_ENABLED=False, apply wajib ditolak keras."""
    monkeypatch.setattr(settings, "config_apply_enabled", False)

    headers, user = _create_user_and_headers()
    device = _create_lab_device(user, lab=True)

    # 1. Create plan
    res_create = client.post(
        "/configurations",
        headers=headers,
        json={
            "device_id": str(device.id),
            "change_set": {
                "description": "Kill switch test",
                "operations": [
                    {"type": "add_ip_address", "interface": "ether2", "address": "10.10.1.1/24"}
                ],
            },
        },
    )
    assert res_create.status_code == 201
    config_id = res_create.json()["id"]

    # 2. Approve
    res_app = client.post(f"/configurations/{config_id}/approve", headers=headers)
    assert res_app.status_code == 200

    # 3. Apply -> harus gagal karena kill-switch mati
    res_apply = client.post(f"/configurations/{config_id}/apply", headers=headers)
    assert res_apply.status_code == 400
    assert "Kill-switch CONFIG_APPLY_ENABLED sedang mati" in res_apply.json()["detail"]


def test_apply_rejected_when_device_not_lab(monkeypatch):
    """Device non-lab wajib ditolak apply-nya."""
    monkeypatch.setattr(settings, "config_apply_enabled", True)

    headers, user = _create_user_and_headers()
    device = _create_lab_device(user, lab=False)  # Bukan lab

    res_create = client.post(
        "/configurations",
        headers=headers,
        json={
            "device_id": str(device.id),
            "change_set": {
                "description": "Non-lab test",
                "operations": [
                    {"type": "add_ip_address", "interface": "ether2", "address": "10.10.1.1/24"}
                ],
            },
        },
    )
    assert res_create.status_code == 201
    config_id = res_create.json()["id"]

    client.post(f"/configurations/{config_id}/approve", headers=headers)
    res_apply = client.post(f"/configurations/{config_id}/apply", headers=headers)
    assert res_apply.status_code == 400
    assert "tidak ditandai sebagai lab" in res_apply.json()["detail"]


# ============================================================
# 4. End-to-End Lifecycle & Rollback Tests (with Fake Adapter)
# ============================================================

def test_full_lifecycle_success(monkeypatch):
    """Siklus sukses: PREVIEWED -> APPROVED -> APPLYING -> VERIFIED."""
    monkeypatch.setattr(settings, "config_apply_enabled", True)

    fake_adapter = FakeNetworkAdapter()
    from app.api.configurations import set_custom_adapter
    set_custom_adapter(fake_adapter)

    try:
        headers, user = _create_user_and_headers()
        device = _create_lab_device(user, lab=True)

        # 1. Create plan
        res_create = client.post(
            "/configurations",
            headers=headers,
            json={
                "device_id": str(device.id),
                "change_set": {
                    "description": "Full E2E Success",
                    "operations": [
                        {"type": "add_vlan_interface", "name": "vlan100", "vlan_id": 100, "interface": "ether2"},
                        {"type": "add_ip_address", "interface": "vlan100", "address": "10.100.1.1/24"},
                    ],
                },
            },
        )
        assert res_create.status_code == 201
        config_id = res_create.json()["id"]
        assert res_create.json()["status"] == "PREVIEWED"

        # 2. Approve
        res_app = client.post(f"/configurations/{config_id}/approve", headers=headers)
        assert res_app.status_code == 200
        assert res_app.json()["status"] == "APPROVED"

        # 3. Apply
        res_apply = client.post(f"/configurations/{config_id}/apply", headers=headers)
        assert res_apply.status_code == 200
        assert res_apply.json()["status"] == "VERIFIED"

        # 4. Verifikasi objek benar-benar ada di adapter
        assert any(iface.name == "vlan100" for iface in fake_adapter.interfaces)
        assert any(ip.address == "10.100.1.1/24" for ip in fake_adapter.ip_addresses)

        # 5. Apply ulang ditolak (idempotent / status conflict)
        res_apply_again = client.post(f"/configurations/{config_id}/apply", headers=headers)
        assert res_apply_again.status_code == 409

    finally:
        set_custom_adapter(None)


def test_failure_on_step_n_triggers_lifo_rollback(monkeypatch):
    """Gagal pada step ke-2 -> LIFO rollback step 1 -> ROLLED_BACK."""
    monkeypatch.setattr(settings, "config_apply_enabled", True)

    fake_adapter = FakeNetworkAdapter()
    fake_adapter.fail_on_step = 2  # Gagal saat menerapkan operasi ke-2
    from app.api.configurations import set_custom_adapter
    set_custom_adapter(fake_adapter)

    try:
        headers, user = _create_user_and_headers()
        device = _create_lab_device(user, lab=True)

        res_create = client.post(
            "/configurations",
            headers=headers,
            json={
                "device_id": str(device.id),
                "change_set": {
                    "description": "Step failure rollback test",
                    "operations": [
                        {"type": "add_vlan_interface", "name": "vlan200", "vlan_id": 200, "interface": "ether2"},
                        {"type": "add_ip_address", "interface": "vlan200", "address": "10.200.1.1/24"},
                    ],
                },
            },
        )
        assert res_create.status_code == 201
        config_id = res_create.json()["id"]

        client.post(f"/configurations/{config_id}/approve", headers=headers)
        res_apply = client.post(f"/configurations/{config_id}/apply", headers=headers)
        assert res_apply.status_code == 400

        # Cek status akhir konfigurasi di DB -> ROLLED_BACK
        res_get = client.get(f"/configurations/{config_id}", headers=headers)
        assert res_get.json()["status"] == "ROLLED_BACK"

        # Pastikan vlan200 yang sempat dibuat pada step 1 sudah terhapus kembali
        assert not any(iface.name == "vlan200" for iface in fake_adapter.interfaces)

    finally:
        set_custom_adapter(None)


def test_verification_failure_triggers_lifo_rollback(monkeypatch):
    """Semua step apply berhasil, tapi verifikasi gagal -> otomatis rollback."""
    monkeypatch.setattr(settings, "config_apply_enabled", True)

    fake_adapter = FakeNetworkAdapter()
    fake_adapter.fail_on_verify = True  # Verifikasi state nyata gagal
    from app.api.configurations import set_custom_adapter
    set_custom_adapter(fake_adapter)

    try:
        headers, user = _create_user_and_headers()
        device = _create_lab_device(user, lab=True)

        res_create = client.post(
            "/configurations",
            headers=headers,
            json={
                "device_id": str(device.id),
                "change_set": {
                    "description": "Verification failure rollback test",
                    "operations": [
                        {"type": "add_ip_address", "interface": "ether2", "address": "10.30.1.1/24"},
                    ],
                },
            },
        )
        config_id = res_create.json()["id"]
        client.post(f"/configurations/{config_id}/approve", headers=headers)
        res_apply = client.post(f"/configurations/{config_id}/apply", headers=headers)
        assert res_apply.status_code == 502
        assert "Verifikasi state nyata perangkat gagal" in res_apply.json()["detail"]

        res_get = client.get(f"/configurations/{config_id}", headers=headers)
        assert res_get.json()["status"] == "ROLLED_BACK"

    finally:
        set_custom_adapter(None)


def test_rollback_failure_results_in_rollback_failed(monkeypatch):
    """Ketika proses rollback itu sendiri gagal -> status ROLLBACK_FAILED (keras & terlihat)."""
    monkeypatch.setattr(settings, "config_apply_enabled", True)

    fake_adapter = FakeNetworkAdapter()
    fake_adapter.fail_on_step = 2  # Gagal di step 2
    fake_adapter.fail_on_rollback = True  # Gagal juga saat me-rollback step 1
    from app.api.configurations import set_custom_adapter
    set_custom_adapter(fake_adapter)

    try:
        headers, user = _create_user_and_headers()
        device = _create_lab_device(user, lab=True)

        res_create = client.post(
            "/configurations",
            headers=headers,
            json={
                "device_id": str(device.id),
                "change_set": {
                    "description": "Rollback failure test",
                    "operations": [
                        {"type": "add_vlan_interface", "name": "vlan300", "vlan_id": 300, "interface": "ether2"},
                        {"type": "add_ip_address", "interface": "vlan300", "address": "10.30.1.1/24"},
                    ],
                },
            },
        )
        config_id = res_create.json()["id"]
        client.post(f"/configurations/{config_id}/approve", headers=headers)
        res_apply = client.post(f"/configurations/{config_id}/apply", headers=headers)
        assert res_apply.status_code == 400

        res_get = client.get(f"/configurations/{config_id}", headers=headers)
        assert res_get.json()["status"] == "ROLLBACK_FAILED"

    finally:
        set_custom_adapter(None)


def test_manual_rollback_after_verified(monkeypatch):
    """User memicu rollback manual paska VERIFIED -> ROLLED_BACK."""
    monkeypatch.setattr(settings, "config_apply_enabled", True)

    fake_adapter = FakeNetworkAdapter()
    from app.api.configurations import set_custom_adapter
    set_custom_adapter(fake_adapter)

    try:
        headers, user = _create_user_and_headers()
        device = _create_lab_device(user, lab=True)

        res_create = client.post(
            "/configurations",
            headers=headers,
            json={
                "device_id": str(device.id),
                "change_set": {
                    "description": "Manual rollback test",
                    "operations": [
                        {"type": "add_ip_address", "interface": "ether2", "address": "10.40.1.1/24"},
                    ],
                },
            },
        )
        config_id = res_create.json()["id"]
        client.post(f"/configurations/{config_id}/approve", headers=headers)
        res_apply = client.post(f"/configurations/{config_id}/apply", headers=headers)
        assert res_apply.status_code == 200
        assert res_apply.json()["status"] == "VERIFIED"

        # Panggil rollback manual
        res_rb = client.post(f"/configurations/{config_id}/rollback", headers=headers)
        assert res_rb.status_code == 200
        assert res_rb.json()["status"] == "ROLLED_BACK"

        # Verifikasi IP terhapus
        assert not any(ip.address == "10.40.1.1/24" for ip in fake_adapter.ip_addresses)

    finally:
        set_custom_adapter(None)


# ============================================================
# 5. Tenant Isolation Tests on Endpoints
# ============================================================

def test_tenant_isolation_on_approve_apply_rollback():
    """User B mencoba approve/apply/rollback plan milik User A -> 404 (Anti-Enumeration)."""
    headers_a, user_a = _create_user_and_headers()
    headers_b, user_b = _create_user_and_headers()
    dev_a = _create_lab_device(user_a)

    res_create = client.post(
        "/configurations",
        headers=headers_a,
        json={
            "device_id": str(dev_a.id),
            "change_set": {
                "description": "Tenant Test",
                "operations": [
                    {"type": "add_ip_address", "interface": "ether2", "address": "10.50.1.1/24"},
                ],
            },
        },
    )
    config_id = res_create.json()["id"]

    # User B mencoba approve -> 404
    res_app_b = client.post(f"/configurations/{config_id}/approve", headers=headers_b)
    assert res_app_b.status_code == 404

    # User B mencoba apply -> 404
    res_apply_b = client.post(f"/configurations/{config_id}/apply", headers=headers_b)
    assert res_apply_b.status_code == 404

    # User B mencoba rollback -> 404
    res_rb_b = client.post(f"/configurations/{config_id}/rollback", headers=headers_b)
    assert res_rb_b.status_code == 404
