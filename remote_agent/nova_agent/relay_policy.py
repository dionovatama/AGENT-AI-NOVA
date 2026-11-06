"""Agent-side destination allow-list for the TCP relay (Phase 4).

The backend only ever sends a ``target_id`` and a port. The Agent maps
``target_id`` to a host using *local, trusted* configuration
(``relay_targets`` in config.json) and refuses everything else. The backend
can never make the Agent dial an arbitrary host.

Config entry:
    {"target_id": "<uuid v4>", "host": "192.168.88.1",
     "ports": [8729], "allow_loopback": false}

Resolution policy (applied to every address that will actually be dialed):
  * the requested port must be in the target's ``ports``
  * unspecified (0.0.0.0, ::), multicast, link-local (169.254/16, fe80::/10,
    includes cloud metadata) and reserved addresses are always refused
  * loopback is refused unless the target sets ``allow_loopback`` (dev/test)
  * if ANY resolved address is refused, the whole target is refused
  * the Agent connects to the validated IP, never re-resolving the name
    (no DNS-rebinding window between check and connect)
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass
from typing import Awaitable, Callable

from .protocol import parse_agent_id

MAX_TARGETS = 256
MAX_PORTS_PER_TARGET = 16

_HOST_RE = re.compile(
    r"^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$"
)

Resolver = Callable[[str, int], Awaitable[list[str]]]


class TargetConfigError(ValueError):
    """Invalid ``relay_targets`` configuration."""


class TargetNotAllowed(Exception):
    """Target/port/address is not permitted by the allow-list."""


@dataclass(frozen=True)
class RelayTarget:
    target_id: str
    host: str
    ports: frozenset[int]
    allow_loopback: bool = False


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def parse_relay_targets(value: object) -> tuple[RelayTarget, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise TargetConfigError("relay_targets must be a list")
    if len(value) > MAX_TARGETS:
        raise TargetConfigError("too many relay_targets")
    targets: list[RelayTarget] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            raise TargetConfigError("each relay target must be an object")
        parsed = parse_agent_id(item.get("target_id"))  # same canonical UUID v4 rule
        if parsed is None:
            raise TargetConfigError("relay target_id must be a canonical UUID v4")
        target_id = str(parsed)
        if target_id in seen:
            raise TargetConfigError("duplicate relay target_id")
        seen.add(target_id)

        host = item.get("host")
        if not isinstance(host, str) or not (_is_ip_literal(host) or _HOST_RE.fullmatch(host)):
            raise TargetConfigError("relay target host must be an IP address or hostname")

        ports = item.get("ports")
        if (not isinstance(ports, list) or not ports or len(ports) > MAX_PORTS_PER_TARGET
                or any(isinstance(p, bool) or not isinstance(p, int) or not 1 <= p <= 65535
                       for p in ports)):
            raise TargetConfigError("relay target ports must be 1-16 integers in 1..65535")

        allow_loopback = item.get("allow_loopback", False)
        if not isinstance(allow_loopback, bool):
            raise TargetConfigError("allow_loopback must be true or false")
        targets.append(RelayTarget(target_id, host, frozenset(ports), allow_loopback))
    return tuple(targets)


def relay_targets_to_json(targets: tuple[RelayTarget, ...]) -> list[dict]:
    out = []
    for t in targets:
        entry: dict = {"target_id": t.target_id, "host": t.host, "ports": sorted(t.ports)}
        if t.allow_loopback:
            entry["allow_loopback"] = True
        out.append(entry)
    return out


def address_allowed(addr: str, *, allow_loopback: bool) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_unspecified or ip.is_multicast or ip.is_link_local or ip.is_reserved:
        return False
    if ip.is_loopback:
        return allow_loopback
    return True


async def system_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addrs: list[str] = []
    for *_, sockaddr in infos:
        addr = sockaddr[0].split("%", 1)[0]
        if addr not in addrs:
            addrs.append(addr)
    return addrs


class AllowList:
    def __init__(self, targets: tuple[RelayTarget, ...], resolver: Resolver | None = None) -> None:
        self._targets = {t.target_id: t for t in targets}
        self._resolver = resolver or system_resolver

    def __bool__(self) -> bool:
        return bool(self._targets)

    async def authorize(self, target_id: str, port: int) -> tuple[RelayTarget, list[str]]:
        """Return the target and the validated IPs to dial, or raise
        :class:`TargetNotAllowed`. Raises ``OSError`` if DNS fails."""
        target = self._targets.get(target_id)
        if target is None or port not in target.ports:
            raise TargetNotAllowed("target not allowed")
        if _is_ip_literal(target.host):
            addrs = [target.host]
        else:
            addrs = await self._resolver(target.host, port)
        if not addrs or not all(address_allowed(a, allow_loopback=target.allow_loopback)
                                for a in addrs):
            raise TargetNotAllowed("target address not allowed")
        return target, addrs
