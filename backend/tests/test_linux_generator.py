from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.linux_generator import LinuxGeneratorRequest, _validate_hostname, generate


def call_generator(**overrides):
    values = {"distro": "debian", "modules": ["packages"], "hostname": "nova-server"}
    values.update(overrides)
    payload = LinuxGeneratorRequest(**values)
    return generate(payload, current_user=SimpleNamespace())


@pytest.mark.parametrize("hostname", ["nova-server", "lab.example", "srv01", "a-b.c-d"])
def test_hostname_accepts_valid_dns_labels(hostname):
    assert _validate_hostname(hostname)


@pytest.mark.parametrize("hostname", ["", "-bad", "bad-", "bad..host", "bad host", "x;id", "$(id)", "a_" + "b" * 60])
def test_hostname_rejects_invalid_labels(hostname):
    assert not _validate_hostname(hostname)


def test_packages_only_does_not_generate_unselected_service_configs():
    result = call_generator(modules=["packages"])
    names = {item.filename for item in result.files}
    assert "README.txt" in names
    assert "hostname.txt" in names
    assert "60-nova.conf" not in names
    assert "named.conf.options" not in names
    assert "nova-rules.txt" not in names
    manifest = next(item for item in result.files if item.filename == "manifest.json")
    assert '"apply_automatically": false' in manifest.content
    assert '"distro": "debian"' in manifest.content


def test_ssh_port_is_reflected_in_ssh_file_and_bundle():
    result = call_generator(modules=["ssh"], ssh_port=2222)
    ssh_file = next(item for item in result.files if item.filename == "60-nova.conf")
    bundle = next(item for item in result.files if item.filename == "nova-linux-setup.sh")
    assert "Port 2222" in ssh_file.content
    assert "60-nova.conf" in bundle.content
    assert "Required packages: openssh-server" in next(
        item for item in result.files if item.filename == "README.txt"
    ).content


def test_firewall_does_not_open_ssh_when_ssh_module_not_selected():
    result = call_generator(modules=["firewall"], firewall_ssh=True)
    rules = next(item for item in result.files if item.filename == "nova-rules.txt")
    assert "ufw default deny incoming" in rules.content
    assert "ufw allow 22/tcp" not in rules.content
    assert "ufw enable" not in rules.content


def test_firewall_opens_selected_ssh_port_only_when_both_modules_selected():
    result = call_generator(modules=["firewall", "ssh"], ssh_port=2202, firewall_ssh=True)
    rules = next(item for item in result.files if item.filename == "nova-rules.txt")
    assert "ufw allow 2202/tcp" in rules.content


def test_invalid_dns_address_is_rejected():
    with pytest.raises(HTTPException) as exc:
        call_generator(modules=["bind9"], dns_listen_address="not-an-ip")
    assert exc.value.status_code == 422


def test_generated_bundle_is_preview_only():
    result = call_generator(modules=["packages", "ssh", "bind9", "firewall"])
    script = next(item for item in result.files if item.filename == "nova-linux-setup.sh")
    assert "does not execute" in script.content.lower() or "preview script" in script.content.lower()
    assert "apt install" not in script.content
    assert "ufw enable" not in script.content
