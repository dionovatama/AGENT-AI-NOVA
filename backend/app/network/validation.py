"""
Validation Service for N.O.V.A Configuration Engine.

Memvalidasi sintaksis, semantik, konflik terhadap state nyata perangkat,
dan proteksi lockout (PRD section 19, 21, 39).
"""

from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass, field

from app.network.models import (
    AddIpAddressOperation,
    AddStaticRouteOperation,
    AddVlanInterfaceOperation,
    ChangeSet,
    DeviceStateSnapshot,
    NetworkOperation,
)
from app.network.policy import evaluate_change_set_policy
from app.tools.schemas import RiskLevel

logger = logging.getLogger("nova.network.validation")


@dataclass
class ValidationIssue:
    field: str
    message: str
    severity: str = "ERROR"  # ERROR atau WARNING


@dataclass
class ChangeSetValidationResult:
    is_valid: bool
    risk_level: RiskLevel
    issues: list[ValidationIssue] = field(default_factory=list)
    policy_violations: list[str] = field(default_factory=list)


def validate_change_set(
    change_set: ChangeSet,
    device_state: DeviceStateSnapshot,
    device_management_ip: str | None = None,
    proposed_risk_level: RiskLevel | None = None,
) -> ChangeSetValidationResult:
    """
    Memvalidasi seluruh operasi di dalam ChangeSet terhadap state nyata perangkat.
    """
    issues: list[ValidationIssue] = []

    # 1. Evaluasi Policy Engine (Hardcoded risk & larangan)
    policy_eval = evaluate_change_set_policy(
        change_set=change_set,
        device_management_ip=device_management_ip,
        proposed_risk_level=proposed_risk_level,
    )

    for violation in policy_eval.violations:
        issues.append(ValidationIssue(field="policy", message=violation, severity="ERROR"))

    # Kumpulkan nama-nama interface yang sudah ada
    existing_interfaces = {iface.name for iface in device_state.interfaces}
    # Track interface baru yang dibuat di dalam changeset ini (memungkinkan buat VLAN lalu pasang IP di VLAN tsb)
    virtual_interfaces = set(existing_interfaces)

    # Identifikasi interface manajemen dari device_management_ip
    mgmt_interface_name: str | None = None
    if device_management_ip:
        clean_mgmt_ip = device_management_ip.strip()
        for ip_st in device_state.ip_addresses:
            try:
                if ipaddress.IPv4Interface(ip_st.address).ip == ipaddress.IPv4Address(clean_mgmt_ip):
                    mgmt_interface_name = ip_st.interface
                    break
            except Exception:
                pass

    # Kumpulkan IP dan VLAN yang sudah ada
    existing_ips = {ip_st.address for ip_st in device_state.ip_addresses}
    existing_vlans = {
        (iface.name, getattr(iface, "comment", None))
        for iface in device_state.interfaces
        if iface.type == "vlan"
    }

    # Tracking dalam satu changeset (anti-duplikasi internal)
    seen_ips_in_plan: set[str] = set()
    seen_vlans_in_plan: set[tuple[str, int]] = set()  # (parent_iface, vlan_id)
    seen_vlan_names_in_plan: set[str] = set()
    seen_routes_in_plan: set[tuple[str, str]] = set()

    for idx, op in enumerate(change_set.operations, start=1):
        if isinstance(op, AddVlanInterfaceOperation):
            # Cek parent interface harus ada di existing_interfaces
            if op.interface not in existing_interfaces:
                issues.append(
                    ValidationIssue(
                        field=f"operations[{idx-1}].interface",
                        message=f"Parent interface '{op.interface}' tidak ditemukan di perangkat.",
                    )
                )

            # Cek nama VLAN belum dipakai
            if op.name in virtual_interfaces:
                issues.append(
                    ValidationIssue(
                        field=f"operations[{idx-1}].name",
                        message=f"Interface dengan nama '{op.name}' sudah ada di perangkat.",
                    )
                )
            if op.name in seen_vlan_names_in_plan:
                issues.append(
                    ValidationIssue(
                        field=f"operations[{idx-1}].name",
                        message=f"Nama VLAN '{op.name}' terduplikasi di dalam plan ini.",
                    )
                )

            # Cek vlan_id pada parent_interface yang sama
            vlan_key = (op.interface, op.vlan_id)
            if vlan_key in seen_vlans_in_plan:
                issues.append(
                    ValidationIssue(
                        field=f"operations[{idx-1}].vlan_id",
                        message=f"VLAN ID {op.vlan_id} terduplikasi pada parent interface '{op.interface}' di plan ini.",
                    )
                )

            seen_vlan_names_in_plan.add(op.name)
            seen_vlans_in_plan.add(vlan_key)
            virtual_interfaces.add(op.name)

        elif isinstance(op, AddIpAddressOperation):
            # Interface target harus ada (bisa fisik eksisting atau VLAN yang dibuat sebelumnya di plan ini)
            if op.interface not in virtual_interfaces:
                issues.append(
                    ValidationIssue(
                        field=f"operations[{idx-1}].interface",
                        message=f"Interface target '{op.interface}' tidak ditemukan di perangkat.",
                    )
                )

            # Cek IP duplikat
            if op.address in existing_ips:
                issues.append(
                    ValidationIssue(
                        field=f"operations[{idx-1}].address",
                        message=f"Alamat IP {op.address} sudah terpasang di perangkat.",
                    )
                )
            if op.address in seen_ips_in_plan:
                issues.append(
                    ValidationIssue(
                        field=f"operations[{idx-1}].address",
                        message=f"Alamat IP {op.address} terduplikasi di dalam plan ini.",
                    )
                )

            # Proteksi lockout: Jangan tambahkan IP baru pada interface manajemen jika subnet bentrok
            if mgmt_interface_name and op.interface == mgmt_interface_name:
                issues.append(
                    ValidationIssue(
                        field=f"operations[{idx-1}].interface",
                        message=(
                            f"Operasi menyasar interface manajemen NOVA ('{mgmt_interface_name}'). "
                            "Ditolak demi keamanan konektivitas."
                        ),
                    )
                )

            seen_ips_in_plan.add(op.address)

        elif isinstance(op, AddStaticRouteOperation):
            # Jika gateway adalah nama interface, interface harus ada
            if not any(c.isdigit() for c in op.gateway.split(".")) and op.gateway not in virtual_interfaces:
                issues.append(
                    ValidationIssue(
                        field=f"operations[{idx-1}].gateway",
                        message=f"Gateway interface '{op.gateway}' tidak ditemukan di perangkat.",
                    )
                )

            # Cek rute duplikat
            route_key = (op.dst_address, op.gateway)
            if route_key in seen_routes_in_plan:
                issues.append(
                    ValidationIssue(
                        field=f"operations[{idx-1}]",
                        message=f"Rute ke {op.dst_address} via {op.gateway} terduplikasi di dalam plan ini.",
                    )
                )
            for r in device_state.routes:
                if r.dst_address == op.dst_address and r.gateway == op.gateway:
                    issues.append(
                        ValidationIssue(
                            field=f"operations[{idx-1}]",
                            message=f"Rute ke {op.dst_address} via {op.gateway} sudah ada di perangkat.",
                        )
                    )

            seen_routes_in_plan.add(route_key)

    is_valid = len(issues) == 0
    return ChangeSetValidationResult(
        is_valid=is_valid,
        risk_level=policy_eval.risk_level,
        issues=issues,
        policy_violations=policy_eval.violations,
    )
