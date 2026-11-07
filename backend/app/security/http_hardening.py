"""Small ASGI hardening middleware: endpoint-specific abuse limits and security headers.

Limits are intentionally per process. Production relay deployment is guarded to one
worker in Phase 8.3; global quotas across replicas require shared storage.
"""
from __future__ import annotations

import json
import re
import time
from collections import deque
from typing import Callable

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_RULES = (
    (re.compile(r"^/auth/(login|register)$"), 10, 60.0, "auth"),
    (re.compile(r"^/chat/"), 20, 60.0, "chat"),
    (re.compile(r"^/tools/execute$"), 30, 60.0, "tools"),
    (re.compile(r"^/devices/[^/]+/monitoring(?:/history)?$"), 12, 60.0, "monitoring"),
)


class _Window:
    def __init__(self, limit: int, seconds: float, clock: Callable[[], float] = time.monotonic, max_keys: int = 10_000):
        self.limit, self.seconds, self.clock, self.max_keys = limit, seconds, clock, max_keys
        self.events: dict[str, deque[float]] = {}

    def _prune(self, now: float) -> None:
        cutoff = now - self.seconds
        for key, queue in list(self.events.items()):
            while queue and queue[0] <= cutoff:
                queue.popleft()
            if not queue:
                self.events.pop(key, None)

    def hit(self, key: str) -> bool:
        now = self.clock()
        queue = self.events.get(key)
        if queue is None:
            if len(self.events) >= self.max_keys:
                self._prune(now)
            if len(self.events) >= self.max_keys:
                return False
            queue = self.events.setdefault(key, deque())
        while queue and queue[0] <= now - self.seconds:
            queue.popleft()
        if len(queue) >= self.limit:
            return False
        queue.append(now)
        return True


def websocket_origin_allowed(origin: str | None, allowed_origins: list[str]) -> bool:
    """Allow native clients without Origin; enforce configured origins for browsers."""
    if not origin:
        return True
    return origin.rstrip("/") in {item.rstrip("/") for item in allowed_origins}


class HttpHardeningMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app
        self._windows = {name: _Window(limit, seconds) for _, limit, seconds, name in _RULES}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        client = scope.get("client")
        ip = str(client[0]) if client else "unknown"
        for pattern, _, _, name in _RULES:
            if pattern.match(path):
                if not self._windows[name].hit(f"{ip}:{name}"):
                    body = json.dumps({"detail": "Too many requests. Please retry later."}).encode()
                    await send({"type": "http.response.start", "status": 429, "headers": [
                        (b"content-type", b"application/json"),
                        (b"retry-after", b"60"),
                        (b"content-length", str(len(body)).encode()),
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"strict-origin-when-cross-origin"),
                        (b"content-security-policy", b"frame-ancestors 'none'"),
                    ]})
                    await send({"type": "http.response.body", "body": body})
                    return
                break

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {key.lower() for key, _ in headers}
                defaults = (
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (b"content-security-policy", b"frame-ancestors 'none'"),
                )
                headers.extend((key, value) for key, value in defaults if key not in existing)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
