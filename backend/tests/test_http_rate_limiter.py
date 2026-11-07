from __future__ import annotations

from starlette.requests import Request

from app.config import settings
from app.security.rate_limiter import get_client_ip


def _request(peer: str, forwarded: str | None = None) -> Request:
    headers = []
    if forwarded is not None:
        headers.append((b"x-forwarded-for", forwarded.encode("ascii")))
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers,
        "client": (peer, 12345),
        "server": ("nova", 8000),
        "scheme": "http",
        "query_string": b"",
    })


def test_untrusted_peer_cannot_spoof_forwarded_ip(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_ips", [])
    request = _request("198.51.100.20", "203.0.113.99")
    assert get_client_ip(request) == "198.51.100.20"


def test_trusted_proxy_chain_uses_first_untrusted_hop_from_right(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_ips", ["10.0.0.0/8"])
    request = _request("10.0.0.2", "198.51.100.77, 10.0.0.3")
    assert get_client_ip(request) == "198.51.100.77"


def test_invalid_forwarded_chain_falls_back_to_proxy_peer(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_ips", ["10.0.0.0/8"])
    request = _request("10.0.0.2", "not-an-ip")
    assert get_client_ip(request) == "10.0.0.2"
