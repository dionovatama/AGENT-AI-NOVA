from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.bind9_generator import Bind9Request, generate, _reverse_zone
import ipaddress


def run(**overrides):
    data = {"profile": "resolver"}
    data.update(overrides)
    return generate(Bind9Request(**data), current_user=SimpleNamespace())


def by_name(result, name):
    return next(item for item in result.files if item.filename == name)


def test_resolver_generates_recursion_acl_and_forwarders():
    result = run(profile="resolver", allow_recursion=["192.168.1.0/24"], forwarders=["8.8.8.8", "8.8.4.4"])
    text = by_name(result, "named.conf.options").content
    assert "recursion yes;" in text
    assert "192.168.1.0/24" in text
    assert "8.8.8.8; 8.8.4.4;" in text
    assert "forward first;" in text


def test_master_generates_forward_and_reverse_zone_files():
    result = run(profile="master", domain="dio-tkj.id", master_ip="192.168.133.207",
                 slave_ip="192.168.133.107", network_cidr="192.168.133.0/24")
    names = {f.filename for f in result.files}
    assert {"named.conf.local", "db.dio-tkj.id", "db.133.168.192", "README.txt", "manifest.json"} <= names
    assert 'type master;' in by_name(result, "named.conf.local").content
    assert "allow-transfer { 192.168.133.107; };" in by_name(result, "named.conf.local").content


def test_slave_generates_secondary_zone_declarations():
    result = run(profile="slave", domain="dio-tkj.id", master_ip="192.168.133.207",
                 network_cidr="192.168.133.0/24")
    config = by_name(result, "named.conf.local").content
    assert "type slave;" in config
    assert "masters { 192.168.133.207; };" in config
    assert "/var/cache/bind/" in config


def test_master_slave_profile_separates_both_sides():
    result = run(profile="master-slave", domain="dio-tkj.id", network_cidr="192.168.133.0/24")
    names = {f.filename for f in result.files}
    assert "master/named.conf.local" in names
    assert "slave/named.conf.local" in names
    assert "master/db.dio-tkj.id" in names


def test_custom_profile_builds_structured_zone_files():
    result = run(profile="custom", domain="lab.example")
    assert "db.lab.example" in {f.filename for f in result.files}


def test_invalid_forwarder_is_rejected():
    with pytest.raises(HTTPException) as exc:
        run(profile="resolver", forwarders=["not-an-ip"])
    assert exc.value.status_code == 422


def test_reverse_zone_derived_from_network_prefix():
    assert _reverse_zone(ipaddress.IPv4Network("192.168.133.0/24")) == "133.168.192.in-addr.arpa"


def test_preview_only_manifest():
    result = run(profile="master")
    manifest = by_name(result, "manifest.json").content
    assert '"apply_automatically": false' in manifest
    assert "restart" not in manifest.lower()
