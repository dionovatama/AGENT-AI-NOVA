import pytest
from fastapi import HTTPException

from app.api.chat import _configuration_from_message, _configuration_intent


def test_vlan_only_request_selects_only_vlan():
    request = _configuration_from_message(
        "Buat file konfigurasi MikroTik RouterOS v7 dengan modul VLAN saja:\n"
        "- VLAN name: vlan10-test\n- VLAN ID: 10\n"
        "- Parent interface: ether1\n- Comment: NOVA VLAN test"
    )
    assert request.modules == ["vlan"]
    assert request.vlan_name == "vlan10-test"
    assert request.vlan_id == 10
    assert request.vlan_parent_interface == "ether1"


def test_negative_modules_do_not_trigger_configuration():
    request = _configuration_from_message(
        "Buatkan VLAN 10 saja. Jangan tambahkan DHCP, NAT, atau firewall. "
        "Parent interface: ether1"
    )
    assert request.modules == ["vlan"]


def test_nat_only_does_not_add_vlan_from_context():
    request = _configuration_from_message(
        "Buatkan NAT saja untuk VLAN 10. WAN: ether1"
    )
    assert request.modules == ["nat"]


def test_missing_vlan_parent_requests_clarification():
    with pytest.raises(HTTPException) as error:
        _configuration_from_message("Buatkan VLAN 10 saja")
    assert error.value.status_code == 422
    assert "parent interface" in error.value.detail.lower()


def test_read_only_ip_check_is_not_configuration_intent():
    assert not _configuration_intent("tolong cek ip address router")


def test_firewall_requires_explicit_action():
    with pytest.raises(HTTPException) as error:
        _configuration_from_message("Buatkan konfigurasi firewall")
    assert error.value.status_code == 422
    assert "aksi firewall" in error.value.detail.lower()
