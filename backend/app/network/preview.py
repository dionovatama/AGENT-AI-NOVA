"""
Configuration Preview & Diff Generator.

Menghasilkan structured diff (JSON) dan render CLI-style preview
serta perhitungan plan_hash dan state_fingerprint kanonik (PRD section 20, 21).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from app.network.adapters.base import NetworkDeviceAdapter
from app.network.models import (
    AddIpAddressOperation,
    AddStaticRouteOperation,
    AddVlanInterfaceOperation,
    ChangeSet,
    DeviceStateSnapshot,
    NetworkOperation,
)


def calculate_plan_hash(device_id: uuid.UUID | str, change_set: ChangeSet) -> str:
    """
    Menghitung hash SHA-256 kanonik dari plan konfigurasi.
    Menjamin representasi kanonik dan deterministik.
    """
    payload = {
        "device_id": str(device_id),
        "operations": [op.model_dump(mode="json") for op in change_set.operations],
    }
    canonical_json = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def calculate_state_fingerprint(device_state: DeviceStateSnapshot) -> str:
    """
    Menghitung hash SHA-256 kanonik dari state perangkat yang relevan
    (interface, IP address, routing table).
    Digunakan untuk mendeteksi drift antara waktu Preview dan Apply.
    """
    canonical_interfaces = sorted(
        [{"name": iface.name, "type": iface.type} for iface in device_state.interfaces],
        key=lambda x: x["name"],
    )
    canonical_ips = sorted(
        [{"address": ip.address, "interface": ip.interface} for ip in device_state.ip_addresses],
        key=lambda x: (x["interface"], x["address"]),
    )
    canonical_routes = sorted(
        [{"dst_address": r.dst_address, "gateway": r.gateway} for r in device_state.routes],
        key=lambda x: (x["dst_address"], x["gateway"]),
    )

    payload = {
        "interfaces": canonical_interfaces,
        "ip_addresses": canonical_ips,
        "routes": canonical_routes,
    }
    canonical_json = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def generate_structured_diff(
    change_set: ChangeSet, device_state: DeviceStateSnapshot
) -> list[dict[str, Any]]:
    """
    Membuat structured diff (JSON) per operasi, menunjukkan kondisi sebelum (before)
    dan kondisi setelah (after).
    """
    diff_entries: list[dict[str, Any]] = []

    for idx, op in enumerate(change_set.operations, start=1):
        entry: dict[str, Any] = {
            "step": idx,
            "operation_type": op.type.value,
            "action": "ADD",
        }

        if isinstance(op, AddIpAddressOperation):
            existing_matching = [
                ip.model_dump()
                for ip in device_state.ip_addresses
                if ip.interface == op.interface
            ]
            entry["target"] = f"interface:{op.interface}"
            entry["before"] = {"existing_ips_on_interface": existing_matching}
            entry["after"] = {
                "address": op.address,
                "interface": op.interface,
                "comment": op.comment,
            }

        elif isinstance(op, AddVlanInterfaceOperation):
            entry["target"] = f"vlan:{op.name}"
            entry["before"] = None
            entry["after"] = {
                "name": op.name,
                "vlan_id": op.vlan_id,
                "interface": op.interface,
                "comment": op.comment,
            }

        elif isinstance(op, AddStaticRouteOperation):
            entry["target"] = f"route:{op.dst_address}"
            entry["before"] = None
            entry["after"] = {
                "dst_address": op.dst_address,
                "gateway": op.gateway,
                "distance": op.distance,
                "comment": op.comment,
            }

        diff_entries.append(entry)

    return diff_entries


def render_cli_preview(change_set: ChangeSet, adapter: NetworkDeviceAdapter) -> str:
    """
    Merender preview perintah konfigurasi dalam format CLI vendor
    (menggunakan template adapter vendor, bukan LLM).
    """
    lines = [
        f"# ============================================================",
        f"# N.O.V.A Configuration Preview — {change_set.description}",
        f"# Total Operasi: {len(change_set.operations)}",
        f"# ============================================================",
    ]

    for idx, op in enumerate(change_set.operations, start=1):
        cli_cmd = adapter.render_cli_preview(op)
        lines.append(f"# Step {idx} ({op.type.value})")
        lines.append(cli_cmd)

    return "\n".join(lines)
