"""BIND9 configuration artifact generator.

Generates reviewable Debian BIND9 files only. It never writes to a host,
installs packages, transfers zones, or restarts services.
"""
import ipaddress
import json
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.database.models import User
from app.security.dependencies import get_current_user

router = APIRouter(prefix="/bind9-config-generator", tags=["bind9-config-generator"])

Profile = Literal["resolver", "master", "slave", "master-slave", "custom"]
RecordType = Literal["A", "AAAA", "CNAME", "MX", "NS", "PTR", "TXT"]


class DNSRecord(BaseModel):
    record_type: RecordType
    name: str = Field(min_length=1, max_length=253)
    value: str = Field(min_length=1, max_length=1024)
    priority: int | None = Field(default=None, ge=0, le=65535)
    ttl: int = Field(default=3600, ge=60, le=604800)


class Bind9Request(BaseModel):
    profile: Profile
    domain: str = "example.test"
    master_ip: str = "192.168.1.10"
    slave_ip: str = "192.168.1.11"
    network_cidr: str = "192.168.1.0/24"
    resolver_listen: str = "127.0.0.1"
    allow_recursion: list[str] = Field(default_factory=lambda: ["127.0.0.1"])
    forwarders: list[str] = Field(default_factory=lambda: ["8.8.8.8", "8.8.4.4"])
    forward_first: bool = True
    ipv6_listen: Literal["any", "none"] = "none"
    primary_ns: str = "ns1"
    secondary_ns: str = "ns2"
    soa_contact: str = "hostmaster"
    records: list[DNSRecord] = Field(default_factory=list)
    include_reverse_zone: bool = True
    zone_config_target: Literal["named.conf.local", "named.conf.default-zones"] = "named.conf.local"

    @field_validator("domain")
    @classmethod
    def valid_domain(cls, value: str) -> str:
        value = value.rstrip(".").lower()
        if len(value) > 253 or not value or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label)
            for label in value.split(".")
        ):
            raise ValueError("Domain tidak valid.")
        return value

    @field_validator("master_ip", "slave_ip", "resolver_listen")
    @classmethod
    def valid_ipv4(cls, value: str) -> str:
        try:
            return str(ipaddress.IPv4Address(value))
        except ValueError as exc:
            raise ValueError("Alamat harus berupa IPv4 yang valid.") from exc

    @field_validator("primary_ns", "secondary_ns")
    @classmethod
    def valid_ns_label(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", value):
            raise ValueError("Label nameserver tidak valid.")
        return value

    @field_validator("soa_contact")
    @classmethod
    def valid_soa_contact(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9-]+(?:\\.[A-Za-z0-9-]+)*", value):
            raise ValueError("Label kontak SOA tidak valid; gunakan hostmaster atau admin.example.")
        return value

    @field_validator("network_cidr")
    @classmethod
    def valid_network(cls, value: str) -> str:
        try:
            return str(ipaddress.IPv4Network(value, strict=False))
        except ValueError as exc:
            raise ValueError("Network CIDR tidak valid.") from exc


class GeneratedFile(BaseModel):
    filename: str
    mime_type: str = "text/plain"
    content: str


class Bind9Response(BaseModel):
    profile: str
    files: list[GeneratedFile]
    warnings: list[str]


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _reverse_zone(network: ipaddress.IPv4Network) -> str:
    octets = str(network.network_address).split(".")
    return ".".join(reversed(octets[: network.prefixlen // 8])) + ".in-addr.arpa"


def _zone_name(name: str, domain: str) -> str:
    if name == "@":
        return domain + "."
    if name.endswith("."):
        return name
    if name == domain or name.endswith("." + domain):
        return name + "."
    return name + "." + domain + "."


def _ns_target(value: str, p: Bind9Request) -> str:
    """Resolve an NS RDATA value to a nameserver hostname (FQDN).

    NS records must point to hostnames, not IP addresses. Configured master
    and slave IPs are mapped to their corresponding nameserver labels.
    Unknown IP addresses are rejected rather than being treated as DNS names.
    """
    candidate = value.strip().rstrip(".")
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return _zone_name(value, p.domain)

    if address == ipaddress.ip_address(p.master_ip):
        return _zone_name(p.primary_ns, p.domain)
    if address == ipaddress.ip_address(p.slave_ip):
        return _zone_name(p.secondary_ns, p.domain)
    raise HTTPException(
        status_code=422,
        detail=(
            f"Record NS harus berisi hostname nameserver (mis. "
            f"{_zone_name(p.primary_ns, p.domain)}), bukan alamat IP '{candidate}'."
        ),
    )


def _resolver_options(p: Bind9Request) -> str:
    try:
        listen = ipaddress.IPv4Address(p.resolver_listen)
        acl = [str(ipaddress.ip_network(item, strict=False) if "/" in item else ipaddress.ip_address(item)) for item in p.allow_recursion]
        forwarders = [str(ipaddress.ip_address(item)) for item in p.forwarders]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="IP listen, ACL, atau forwarder tidak valid.") from exc
    if not acl:
        raise HTTPException(status_code=422, detail="Allow-recursion minimal berisi satu alamat atau network.")
    forward_block = ""
    if forwarders:
        forward_block = "    forwarders { " + "; ".join(forwarders) + "; };\n"
        forward_block += f"    forward {'first' if p.forward_first else 'only'};\n"
    return (
        "// Generated by NOVA; review before installation\n"
        "options {\n"
        '    directory "/var/cache/bind";\n'
        f"    listen-on {{ {listen}; }};\n"
        f"    listen-on-v6 {{ {'any' if p.ipv6_listen == 'any' else 'none'}; }};\n"
        "    recursion yes;\n"
        "    allow-query { any; };\n"
        "    allow-recursion { " + "; ".join(acl) + "; };\n"
        "    dnssec-validation auto;\n"
        + forward_block + "};\n"
    )


def _default_records(p: Bind9Request) -> list[DNSRecord]:
    return [
        DNSRecord(record_type="A", name="@", value=p.master_ip),
        DNSRecord(record_type="NS", name="@", value=p.primary_ns + "." + p.domain + "."),
        DNSRecord(record_type="NS", name="@", value=p.secondary_ns + "." + p.domain + "."),
        DNSRecord(record_type="A", name=p.primary_ns, value=p.master_ip),
        DNSRecord(record_type="A", name=p.secondary_ns, value=p.slave_ip),
        DNSRecord(record_type="CNAME", name="www", value="@"),
    ]


def _render_zone(p: Bind9Request, reverse: bool = False) -> str:
    domain = _reverse_zone(ipaddress.IPv4Network(p.network_cidr)) if reverse else p.domain
    records = list(p.records) if p.records else _default_records(p)
    if not reverse and not any(record.record_type == "NS" and record.name == "@" for record in records):
        records.extend([
            DNSRecord(record_type="NS", name="@", value=p.primary_ns + "." + p.domain + "."),
            DNSRecord(record_type="NS", name="@", value=p.secondary_ns + "." + p.domain + "."),
        ])
    serial = "2026103001"
    contact = p.soa_contact.replace("@", ".")
    lines = [
        "; Generated by NOVA; review before installation",
        "$TTL 86400",
        f"@ IN SOA {p.primary_ns}.{p.domain}. {contact}.{p.domain}. (",
        f"    {serial} ; Serial",
        "    3600 ; Refresh",
        "    1800 ; Retry",
        "    604800 ; Expire",
        "    86400 ; Negative Cache TTL",
        ")",
    ]
    if reverse:
        lines += [
            f"@ IN NS {p.primary_ns}.{p.domain}.",
            f"@ IN NS {p.secondary_ns}.{p.domain}.",
        ]
        network = ipaddress.IPv4Network(p.network_cidr)
        for ip, host in [(p.master_ip, p.primary_ns), (p.slave_ip, p.secondary_ns)]:
            address = ipaddress.IPv4Address(ip)
            if address in network:
                host_octets = str(address).split(".")[network.prefixlen // 8:]
                owner = ".".join(reversed(host_octets)) or "@"
                lines.append(f"{owner} IN PTR {host}.{p.domain}.")
    else:
        for record in records:
            name = "@" if record.name == "@" else record.name
            value = record.value
            if record.record_type == "NS":
                value = _ns_target(value, p)
            elif record.record_type in ("CNAME", "PTR"):
                value = _zone_name(value, p.domain)
            elif record.record_type == "MX":
                value = f"{record.priority or 10} {_zone_name(value, p.domain)}"
            elif record.record_type == "TXT":
                value = _quote(value)
            lines.append(f"{name} {record.ttl} IN {record.record_type} {value}")
    return "\n".join(lines) + "\n"


def _master_files(p: Bind9Request) -> list[GeneratedFile]:
    network = ipaddress.IPv4Network(p.network_cidr)
    reverse = _reverse_zone(network)
    allow = f"{{ {p.slave_ip}; }}"
    zones = [
        f'zone "{p.domain}" {{\n    type master;\n    allow-transfer {allow};\n    also-notify {allow};\n    file "/etc/bind/db.{p.domain}";\n}};'
    ]
    files = [GeneratedFile(filename=f"db.{p.domain}", content=_render_zone(p))]
    if p.include_reverse_zone:
        zones.append(
            f'zone "{reverse}" {{\n    type master;\n    allow-transfer {allow};\n    also-notify {allow};\n    file "/etc/bind/db.{reverse.removesuffix(".in-addr.arpa")}";\n}};'
        )
        files.append(GeneratedFile(filename=f"db.{reverse.split('.')[0]}", content=_render_zone(p, reverse=True)))
    files.insert(0, GeneratedFile(filename=p.zone_config_target, content="// Generated by NOVA\n" + "\n\n".join(zones) + "\n"))
    return files


def _slave_config(p: Bind9Request) -> GeneratedFile:
    network = ipaddress.IPv4Network(p.network_cidr)
    reverse = _reverse_zone(network)
    zones = [
        f'zone "{p.domain}" {{\n    type slave;\n    masters {{ {p.master_ip}; }};\n    file "/var/cache/bind/db.{p.domain}";\n}};'
    ]
    if p.include_reverse_zone:
        zones.append(
            f'zone "{reverse}" {{\n    type slave;\n    masters {{ {p.master_ip}; }};\n    file "/var/cache/bind/db.{reverse.split(".")[0]}";\n}};'
        )
    return GeneratedFile(filename=p.zone_config_target, content="// Generated by NOVA\n" + "\n\n".join(zones) + "\n")


@router.post("/generate", response_model=Bind9Response)
def generate(payload: Bind9Request, current_user: User = Depends(get_current_user)) -> Bind9Response:
    warnings = [
        "Preview only: NOVA tidak menulis ke /etc/bind, memasang paket, menjalankan zone transfer, atau me-restart layanan.",
        "Tinjau path file, ACL, alamat server, dan serial SOA sebelum penerapan manual.",
    ]
    files: list[GeneratedFile] = []
    profile = payload.profile
    if profile == "resolver":
        files.append(GeneratedFile(filename="named.conf.options", content=_resolver_options(payload)))
    elif profile == "master":
        files.extend(_master_files(payload))
    elif profile == "slave":
        files.append(_slave_config(payload))
    elif profile == "master-slave":
        files.extend(GeneratedFile(filename="master/" + f.filename, content=f.content) for f in _master_files(payload))
        files.append(GeneratedFile(filename="slave/" + payload.zone_config_target, content=_slave_config(payload).content))
    else:
        files.extend(_master_files(payload))
        warnings.append("Custom profile menggunakan zone builder terstruktur; konfigurasi teks bebas tidak dieksekusi atau disisipkan.")
    readme = (
        "NOVA BIND9 Configuration Generator\n"
        f"Profile: {profile}\n"
        f"Domain: {payload.domain}\n"
        f"Master: {payload.master_ip}\n"
        f"Slave: {payload.slave_ip}\n\n"
        "Preview-only artifact. Tidak ada file sistem yang diubah dan tidak ada service yang dijalankan.\n"
        "Validasi manual yang disarankan:\n"
        f"named-checkzone {payload.domain} db.{payload.domain}\n"
        "named-checkconf -z\n"
    )
    files.append(GeneratedFile(filename="README.txt", content=readme))
    files.append(GeneratedFile(filename="manifest.json", mime_type="application/json", content=json.dumps({
        "generator": "NOVA BIND9 Configuration Generator",
        "profile": profile,
        "domain": payload.domain,
        "master_ip": payload.master_ip,
        "slave_ip": payload.slave_ip,
        "files": [f.filename for f in files],
        "apply_automatically": False,
    }, indent=2) + "\n"))
    return Bind9Response(profile=profile, files=files, warnings=warnings)
