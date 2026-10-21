"""
Unit and Integration Tests for N.O.V.A Configuration Engine (Sub-Milestone A).

Covers:
1. Pydantic operation models and ChangeSet validation (whitelist enums, strict types).
2. Hardcoded Policy Engine and risk classification (elevation only, no demotion).
3. State conflict validation (duplicate IPs, duplicate VLANs, nonexistent interfaces).
4. Lockout protection (safeguarding NOVA's management IP/interface).
5. Structured diff and deterministic CLI preview generation.
6. Plan hash and state fingerprint determinism.
7. Backup storage security (path traversal protection, hash verification, sanitization).
8. REST API endpoints (POST /configurations, GET /configurations, GET /configurations/{id}).
9. Tenant isolation (anti-enumeration: 404 for other user's device and configuration).
"""

import uuid
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.database.models import Configuration, Device, User
from app.database.session import SessionLocal
from app.main import app
from app.network.adapters.fake import FakeNetworkAdapter
from app.network.backup import (
    get_device_backup_dir,
    save_state_snapshot,
    verify_backup_file,
)
from app.network.models import (
    AddIpAddressOperation,
    AddStaticRouteOperation,
    AddVlanInterfaceOperation,
    ChangeSet,
    DeviceStateSnapshot,
    InterfaceState,
    IpAddressState,
    OperationType,
    RouteState,
)
from app.network.policy import (
    classify_operation_risk,
    evaluate_change_set_policy,
)
from app.network.preview import (
    calculate_plan_hash,
    calculate_state_fingerprint,
    generate_structured_diff,
    render_cli_preview,
)
from app.network.validation import validate_change_set
from app.security.hashing import create_access_token
from app.tools.schemas import RiskLevel

client = TestClient(app)


# ============================================================
# Helpers
# ============================================================

def _create_test_user() -> tuple[dict[str, str], User]:
    db = SessionLocal()
    try:
        user_id = uuid.uuid4()
        user = User(
            id=user_id,
            email=f"config-user-{user_id.hex[:8]}@example.com",
            hashed_password="hashed_placeholder",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    finally:
        db.close()

    token = create_access_token(subject=str(user.id))
    headers = {"Authorization": f"Bearer {token}"}
    return headers, user


def _create_test_device(user: User, host: str = "192.168.88.1") -> Device:
    db = SessionLocal()
    try:
        device = Device(
            id=uuid.uuid4(),
            owner_id=user.id,
            name=f"lab-router-{uuid.uuid4().hex[:6]}",
            platform="mikrotik",
            host=host,
            port=8728,
            connection_type="api",
            status="active",
            device_metadata={"username": "admin", "lab": True},
        )
        db.add(device)
        db.commit()
        db.refresh(device)
        return device
    finally:
        db.close()


# ============================================================
# 1. Pydantic Operations Schema & Strict Validation Tests
# ============================================================

def test_add_ip_address_valid():
    op = AddIpAddressOperation(interface="ether2", address="192.168.10.1/24", comment="LAN IP")
    assert op.type == OperationType.ADD_IP_ADDRESS
    assert op.interface == "ether2"
    assert op.address == "192.168.10.1/24"


def test_add_ip_address_rejects_missing_cidr_prefix():
    with pytest.raises(ValidationError) as exc:
        AddIpAddressOperation(interface="ether2", address="192.168.10.1")
    assert "CIDR lengkap" in str(exc.value)


def test_add_ip_address_rejects_network_and_broadcast_addresses():
    with pytest.raises(ValidationError) as exc:
        AddIpAddressOperation(interface="ether2", address="192.168.10.0/24")
    assert "network address" in str(exc.value)

    with pytest.raises(ValidationError) as exc2:
        AddIpAddressOperation(interface="ether2", address="192.168.10.255/24")
    assert "broadcast address" in str(exc2.value)


def test_add_ip_address_rejects_dangerous_interface_name():
    with pytest.raises(ValidationError):
        AddIpAddressOperation(interface="ether2; rm -rf /", address="192.168.10.1/24")


def test_add_vlan_interface_valid():
    op = AddVlanInterfaceOperation(name="vlan10", vlan_id=10, interface="ether1")
    assert op.type == OperationType.ADD_VLAN_INTERFACE
    assert op.vlan_id == 10


def test_add_vlan_interface_rejects_out_of_range_vlan_id():
    with pytest.raises(ValidationError):
        AddVlanInterfaceOperation(name="vlan0", vlan_id=0, interface="ether1")

    with pytest.raises(ValidationError):
        AddVlanInterfaceOperation(name="vlan5000", vlan_id=5000, interface="ether1")


def test_add_static_route_valid():
    op = AddStaticRouteOperation(dst_address="10.0.0.0/8", gateway="192.168.1.254", distance=1)
    assert op.type == OperationType.ADD_STATIC_ROUTE
    assert op.distance == 1


def test_add_static_route_rejects_invalid_destination():
    with pytest.raises(ValidationError):
        AddStaticRouteOperation(dst_address="999.999.999.999/24", gateway="192.168.1.1")


def test_changeset_rejects_unwhitelisted_operation():
    """Operasi DELETE atau di luar whitelist ditolak di level schema Pydantic."""
    raw_data = {
        "description": "Exploit attempt",
        "operations": [
            {"type": "delete_firewall", "rule_id": "*1"},
        ],
    }
    with pytest.raises(ValidationError):
        ChangeSet.model_validate(raw_data)


# ============================================================
# 2. Policy Engine & Risk Classification Tests
# ============================================================

def test_policy_risk_classification():
    op_vlan = AddVlanInterfaceOperation(name="vlan10", vlan_id=10, interface="ether1")
    assert classify_operation_risk(op_vlan) == RiskLevel.LOW

    op_ip = AddIpAddressOperation(interface="ether1", address="192.168.20.1/24")
    assert classify_operation_risk(op_ip) == RiskLevel.MEDIUM

    op_route_normal = AddStaticRouteOperation(dst_address="10.10.0.0/16", gateway="192.168.88.254")
    assert classify_operation_risk(op_route_normal) == RiskLevel.MEDIUM

    op_route_default = AddStaticRouteOperation(dst_address="0.0.0.0/0", gateway="192.168.88.254")
    assert classify_operation_risk(op_route_default) == RiskLevel.HIGH


def test_policy_risk_elevation_only():
    """Policy risk can be elevated, but NEVER demoted."""
    cs = ChangeSet(
        description="Normal route",
        operations=[
            AddStaticRouteOperation(dst_address="0.0.0.0/0", gateway="192.168.88.254"),
        ],
    )
    # LLM/client proposes LOW, but policy must keep HIGH
    res = evaluate_change_set_policy(cs, proposed_risk_level=RiskLevel.LOW)
    assert res.risk_level == RiskLevel.HIGH

    # If policy is MEDIUM and proposed is HIGH -> elevated to HIGH
    cs_medium = ChangeSet(
        description="IP add",
        operations=[AddIpAddressOperation(interface="ether2", address="10.0.0.1/24")],
    )
    res_elevated = evaluate_change_set_policy(cs_medium, proposed_risk_level=RiskLevel.HIGH)
    assert res_elevated.risk_level == RiskLevel.HIGH


def test_policy_prohibited_keywords_rejected():
    cs = ChangeSet(
        description="Hidden firewall tweak",
        operations=[
            AddIpAddressOperation(interface="ether2", address="10.1.1.1/24", comment="bypass firewall rule"),
        ],
    )
    res = evaluate_change_set_policy(cs)
    assert res.is_allowed is False
    assert any("firewall" in v for v in res.violations)


def test_policy_lockout_protection():
    """Lockout protection: operation targeting NOVA's management IP is blocked."""
    mgmt_ip = "192.168.88.1"
    cs = ChangeSet(
        description="Lockout attack",
        operations=[
            AddIpAddressOperation(interface="ether3", address=f"{mgmt_ip}/24"),
        ],
    )
    res = evaluate_change_set_policy(cs, device_management_ip=mgmt_ip)
    assert res.is_allowed is False
    assert any("proteksi lockout" in v for v in res.violations)


# ============================================================
# 3. State Conflict Validation Tests
# ============================================================

def test_validation_rejects_nonexistent_interface():
    state = DeviceStateSnapshot(
        interfaces=[InterfaceState(name="ether1"), InterfaceState(name="ether2")],
        ip_addresses=[],
        routes=[],
    )
    cs = ChangeSet(
        description="Add IP to ether99",
        operations=[AddIpAddressOperation(interface="ether99", address="10.50.0.1/24")],
    )
    res = validate_change_set(cs, state)
    assert res.is_valid is False
    assert any("ether99" in issue.message for issue in res.issues)


def test_validation_rejects_duplicate_ip():
    state = DeviceStateSnapshot(
        interfaces=[InterfaceState(name="ether1")],
        ip_addresses=[IpAddressState(address="192.168.1.1/24", interface="ether1")],
        routes=[],
    )
    cs = ChangeSet(
        description="Duplicate IP",
        operations=[AddIpAddressOperation(interface="ether1", address="192.168.1.1/24")],
    )
    res = validate_change_set(cs, state)
    assert res.is_valid is False
    assert any("sudah terpasang" in issue.message for issue in res.issues)


def test_validation_rejects_duplicate_vlan_name():
    state = DeviceStateSnapshot(
        interfaces=[InterfaceState(name="ether1"), InterfaceState(name="vlan10", type="vlan")],
        ip_addresses=[],
        routes=[],
    )
    cs = ChangeSet(
        description="Duplicate VLAN",
        operations=[AddVlanInterfaceOperation(name="vlan10", vlan_id=20, interface="ether1")],
    )
    res = validate_change_set(cs, state)
    assert res.is_valid is False
    assert any("sudah ada" in issue.message for issue in res.issues)


def test_validation_allows_valid_chaining_in_same_plan():
    """Create VLAN10 on ether1, then assign IP on VLAN10 in same plan -> Valid!"""
    state = DeviceStateSnapshot(
        interfaces=[InterfaceState(name="ether1")],
        ip_addresses=[],
        routes=[],
    )
    cs = ChangeSet(
        description="Chain VLAN then IP",
        operations=[
            AddVlanInterfaceOperation(name="vlan10", vlan_id=10, interface="ether1"),
            AddIpAddressOperation(interface="vlan10", address="192.168.10.1/24"),
        ],
    )
    res = validate_change_set(cs, state)
    assert res.is_valid is True
    assert len(res.issues) == 0


# ============================================================
# 4. Preview, Structured Diff, and Hash Determinism Tests
# ============================================================

def test_structured_diff_and_cli_preview():
    adapter = FakeNetworkAdapter()
    state = DeviceStateSnapshot(
        interfaces=[InterfaceState(name="ether1"), InterfaceState(name="ether2")],
        ip_addresses=[],
        routes=[],
    )
    cs = ChangeSet(
        description="Setup LAN",
        operations=[
            AddVlanInterfaceOperation(name="vlan20", vlan_id=20, interface="ether2"),
            AddIpAddressOperation(interface="vlan20", address="10.20.0.1/24"),
        ],
    )
    diff = generate_structured_diff(cs, state)
    assert len(diff) == 2
    assert diff[0]["target"] == "vlan:vlan20"
    assert diff[1]["target"] == "interface:vlan20"
    assert diff[1]["after"]["address"] == "10.20.0.1/24"

    cli_text = render_cli_preview(cs, adapter)
    assert '/interface vlan add name="vlan20" vlan-id=20 interface="ether2"' in cli_text
    assert '/ip address add address="10.20.0.1/24" interface="vlan20"' in cli_text


def test_plan_hash_and_state_fingerprint_determinism():
    dev_id = uuid.uuid4()
    cs = ChangeSet(
        description="Hash test",
        operations=[AddIpAddressOperation(interface="ether1", address="10.0.0.1/24")],
    )
    hash_1 = calculate_plan_hash(dev_id, cs)
    hash_2 = calculate_plan_hash(dev_id, cs)
    assert hash_1 == hash_2
    assert len(hash_1) == 64

    state = DeviceStateSnapshot(
        interfaces=[InterfaceState(name="ether1")],
        ip_addresses=[IpAddressState(address="192.168.1.1/24", interface="ether1")],
        routes=[],
    )
    fp_1 = calculate_state_fingerprint(state)
    fp_2 = calculate_state_fingerprint(state)
    assert fp_1 == fp_2
    assert len(fp_1) == 64


# ============================================================
# 5. Backup Storage Security Tests
# ============================================================

def test_backup_path_traversal_protection():
    with pytest.raises(ValueError):
        get_device_backup_dir("../../etc", uuid.uuid4())


def test_save_state_snapshot_and_hash_verification():
    owner_id = uuid.uuid4()
    device_id = uuid.uuid4()
    state_data = {
        "interfaces": [{"name": "ether1"}],
        "sensitive_token": "super_secret_jwt_token_value",
    }
    backup_ref = save_state_snapshot(owner_id, device_id, state_data)

    assert "path" in backup_ref
    assert "sha256" in backup_ref
    assert backup_ref["size_bytes"] > 0
    # Relative path verification
    assert not backup_ref["path"].startswith("/")
    assert not backup_ref["path"].startswith("C:")

    # Verify backup file on disk
    assert verify_backup_file(backup_ref) is True

    # Tampered hash must fail
    tampered_ref = dict(backup_ref)
    tampered_ref["sha256"] = "0" * 64
    assert verify_backup_file(tampered_ref) is False


# ============================================================
# 6. REST API Endpoints & Tenant Isolation Tests
# ============================================================

def test_create_configuration_without_jwt_returns_401():
    response = client.post("/configurations", json={"device_id": str(uuid.uuid4()), "change_set": {}})
    assert response.status_code == 401


def test_create_configuration_device_not_owned_returns_404():
    headers_a, user_a = _create_test_user()
    _, user_b = _create_test_user()
    device_b = _create_test_device(user_b)

    payload = {
        "device_id": str(device_b.id),
        "change_set": {
            "description": "Cross tenant probe",
            "operations": [
                {"type": "add_ip_address", "interface": "ether2", "address": "10.0.0.1/24"}
            ],
        },
    }
    # User A tries to create config on User B's device -> 404 (Anti-Enumeration)
    response = client.post("/configurations", headers=headers_a, json=payload)
    assert response.status_code == 404
    assert "tidak ditemukan" in response.json()["detail"]


def test_create_configuration_valid_succeeds_with_preview():
    headers, user = _create_test_user()
    device = _create_test_device(user)

    payload = {
        "device_id": str(device.id),
        "change_set": {
            "description": "Setup test vlan and IP",
            "operations": [
                {"type": "add_vlan_interface", "name": "vlan50", "vlan_id": 50, "interface": "ether2"},
                {"type": "add_ip_address", "interface": "vlan50", "address": "10.50.0.1/24"},
            ],
        },
    }

    response = client.post("/configurations", headers=headers, json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "PREVIEWED"
    assert body["owner_id"] == str(user.id)
    assert body["device_id"] == str(device.id)
    assert body["plan_hash"] is not None
    assert body["state_fingerprint"] is not None
    assert len(body["structured_diff"]) == 2
    assert "vlan50" in body["cli_preview"]


def test_create_configuration_validation_failure_returns_422():
    headers, user = _create_test_user()
    device = _create_test_device(user)

    payload = {
        "device_id": str(device.id),
        "change_set": {
            "description": "Invalid IP",
            "operations": [
                {"type": "add_ip_address", "interface": "ether99", "address": "10.0.0.1/24"},
            ],
        },
    }

    response = client.post("/configurations", headers=headers, json=payload)
    assert response.status_code == 422
    assert "Validasi konfigurasi gagal" in response.json()["detail"]["message"]


def test_list_and_get_configurations_tenant_isolation():
    headers_a, user_a = _create_test_user()
    headers_b, user_b = _create_test_user()
    dev_a = _create_test_device(user_a)

    # User A creates config
    payload = {
        "device_id": str(dev_a.id),
        "change_set": {
            "description": "User A Plan",
            "operations": [
                {"type": "add_ip_address", "interface": "ether2", "address": "172.16.1.1/24"}
            ],
        },
    }
    res_create = client.post("/configurations", headers=headers_a, json=payload)
    assert res_create.status_code == 201
    config_a_id = res_create.json()["id"]

    # User A can get it
    res_get_a = client.get(f"/configurations/{config_a_id}", headers=headers_a)
    assert res_get_a.status_code == 200

    # User B list configs -> does not see User A's config
    res_list_b = client.get("/configurations", headers=headers_b)
    assert res_list_b.status_code == 200
    b_ids = [c["id"] for c in res_list_b.json()]
    assert config_a_id not in b_ids

    # User B get User A's config -> 404 (Anti-Enumeration)
    res_get_b = client.get(f"/configurations/{config_a_id}", headers=headers_b)
    assert res_get_b.status_code == 404
