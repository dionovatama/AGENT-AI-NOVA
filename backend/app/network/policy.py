"""
Policy Engine for N.O.V.A Configuration Engine.

Otoritas tunggal untuk klasifikasi risiko hardcoded dan penegakan aturan larangan
(PRD section 17.3, 19, 23, 30, 39).
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
    NetworkOperation,
    OperationType,
)
from app.tools.schemas import RiskLevel

logger = logging.getLogger("nova.network.policy")


@dataclass
class PolicyEvaluationResult:
    is_allowed: bool
    risk_level: RiskLevel
    violations: list[str] = field(default_factory=list)


# Kata kunci yang dilarang keras muncul dalam nama atau komentar (Defense in Depth)
_PROHIBITED_KEYWORDS = {
    "firewall",
    "filter",
    "nat",
    "mangle",
    "user",
    "password",
    "ssh",
    "api",
    "winbox",
    "dhcp-server",
    "dhcp",
    "drop",
    "reject",
}


def classify_operation_risk(op: NetworkOperation) -> RiskLevel:
    """
    Menentukan tingkat risiko satu operasi secara deterministik.
    Aturan:
    - add_static_route dengan 0.0.0.0/0 (default route) -> HIGH (berisiko mengubah jalur keluar seluruh router)
    - add_static_route lainnya -> MEDIUM
    - add_ip_address -> MEDIUM (mengikat subnet baru ke interface)
    - add_vlan_interface -> LOW (membuat interface logis VLAN)
    """
    if isinstance(op, AddStaticRouteOperation):
        try:
            net = ipaddress.IPv4Network(op.dst_address, strict=False)
            if net == ipaddress.IPv4Network("0.0.0.0/0"):
                return RiskLevel.HIGH
        except Exception:
            return RiskLevel.HIGH
        return RiskLevel.MEDIUM

    if isinstance(op, AddIpAddressOperation):
        return RiskLevel.MEDIUM

    if isinstance(op, AddVlanInterfaceOperation):
        return RiskLevel.LOW

    return RiskLevel.HIGH


def evaluate_change_set_policy(
    change_set: ChangeSet,
    device_management_ip: str | None = None,
    proposed_risk_level: RiskLevel | None = None,
) -> PolicyEvaluationResult:
    """
    Evaluasi kebijakan hardcoded terhadap kumpulan operasi:
    1. Memeriksa keberadaan operasi terlarang.
    2. Menegakkan proteksi lockout (NOVA tidak boleh mengutak-atik IP/interface manajemen).
    3. Menentukan risk_level tertinggi dari semua operasi.
    4. Mengakomodasi usulan LLM/klien hanya jika menaikkan tingkat risiko (tidak pernah menurunkan).
    """
    violations: list[str] = []
    max_risk = RiskLevel.LOW

    # Priority risk ordering
    risk_ranks = {RiskLevel.LOW: 1, RiskLevel.MEDIUM: 2, RiskLevel.HIGH: 3}

    mgmt_ip_obj = None
    if device_management_ip:
        try:
            mgmt_ip_obj = ipaddress.IPv4Address(device_management_ip.strip())
        except Exception:
            mgmt_ip_obj = None

    for idx, op in enumerate(change_set.operations, start=1):
        # 1. Klasifikasi risiko per operasi
        op_risk = classify_operation_risk(op)
        if risk_ranks[op_risk] > risk_ranks[max_risk]:
            max_risk = op_risk

        # 2. Cek keyword terlarang di comment atau nama
        comment = getattr(op, "comment", None) or ""
        comment_lower = comment.lower()
        for kw in _PROHIBITED_KEYWORDS:
            if kw in comment_lower.split():
                violations.append(
                    f"Operasi #{idx} ({op.type.value}) memuat kata kunci terlarang '{kw}' dalam komentar."
                )

        # 3. Proteksi Lockout untuk IP Address
        if isinstance(op, AddIpAddressOperation):
            try:
                op_iface = ipaddress.IPv4Interface(op.address)
                if mgmt_ip_obj and op_iface.ip == mgmt_ip_obj:
                    violations.append(
                        f"Operasi #{idx} melanggar proteksi lockout: mencoba menambahkan alamat IP "
                        f"yang identik dengan IP manajemen NOVA ({device_management_ip})."
                    )
            except Exception as exc:
                violations.append(f"Operasi #{idx} alamat IP tidak valid: {exc}")

        # 4. Proteksi Lockout untuk Static Route
        elif isinstance(op, AddStaticRouteOperation):
            # Jika rute baru mencoba mengarahkan subnet manajemen ke gateway yang berbeda
            if mgmt_ip_obj:
                try:
                    route_net = ipaddress.IPv4Network(op.dst_address, strict=False)
                    if mgmt_ip_obj in route_net and route_net.prefixlen > 0:
                        violations.append(
                            f"Operasi #{idx} melanggar proteksi lockout: rute baru untuk "
                            f"{op.dst_address} mencakup IP manajemen NOVA ({device_management_ip})."
                        )
                except Exception as exc:
                    violations.append(f"Operasi #{idx} rute tujuan tidak valid: {exc}")

    # Kebijakan usulan LLM/klien: hanya bisa dinaikkan, tidak pernah diturunkan
    final_risk = max_risk
    if proposed_risk_level is not None:
        if risk_ranks[proposed_risk_level] > risk_ranks[max_risk]:
            final_risk = proposed_risk_level

    is_allowed = len(violations) == 0
    return PolicyEvaluationResult(
        is_allowed=is_allowed,
        risk_level=final_risk,
        violations=violations,
    )
