"""
HTTP Rate Limiting module for N.O.V.A endpoints.

Provides in-memory sliding-window rate limiting for:
- /auth/login (keyed by IP)
- /auth/register (keyed by IP)
- /chat/* (keyed by user ID, fallback IP)
- /tools/execute (keyed by user ID, fallback IP)
- monitoring endpoints (keyed by user ID, fallback IP)

Per-process limitation: documented under SEC-04/SEC-14 until shared cache (Redis) is introduced.
"""

from __future__ import annotations

import ipaddress
import math
from typing import Callable
from fastapi import Depends, HTTPException, Request, status

from app.agents.ratelimit import SlidingWindowLimiter
from app.config import settings
from app.database.models import User
from app.security.dependencies import get_current_user


def _is_trusted_proxy(address: str) -> bool:
    try:
        peer = ipaddress.ip_address(address)
    except ValueError:
        return False
    for configured in settings.trusted_proxy_ips:
        try:
            if peer in ipaddress.ip_network(configured, strict=False):
                return True
        except ValueError:
            continue
    return False


def get_client_ip(request: Request) -> str:
    """Trust X-Forwarded-For only when the immediate socket peer is trusted."""
    peer = request.client.host if request.client and request.client.host else None
    if not peer:
        return "unknown"
    if not _is_trusted_proxy(peer):
        return peer

    chain = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
    for candidate in reversed(chain):
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if not _is_trusted_proxy(candidate):
            return candidate
    return peer


class HttpRateLimiter:
    """Wrapper around SlidingWindowLimiter providing HTTP 429 semantics."""

    def __init__(
        self,
        limit_getter: Callable[[], int],
        window_getter: Callable[[], float],
        name: str,
    ) -> None:
        self.limit_getter = limit_getter
        self.window_getter = window_getter
        self.name = name
        self._limiter = SlidingWindowLimiter(
            limit=max(1, limit_getter()),
            window_seconds=max(1.0, window_getter()),
        )

    def _sync_config(self) -> None:
        limit = max(1, self.limit_getter())
        window = max(1.0, self.window_getter())
        if self._limiter.limit != limit or self._limiter.window != window:
            self._limiter.limit = limit
            self._limiter.window = window

    def check(self, key: str) -> None:
        self._sync_config()
        if not self._limiter.hit(key):
            now = self._limiter._clock()
            events = self._limiter._events.get(key)
            retry_after = int(self._limiter.window)
            if events:
                retry_after = max(1, math.ceil((events[0] + self._limiter.window) - now))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded for {self.name}. Please retry after {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)},
            )

    def reset(self) -> None:
        self._limiter._events.clear()


auth_login_limiter = HttpRateLimiter(
    lambda: settings.rate_limit_auth_login_limit,
    lambda: settings.rate_limit_auth_login_window_seconds,
    name="login",
)

auth_register_limiter = HttpRateLimiter(
    lambda: settings.rate_limit_auth_register_limit,
    lambda: settings.rate_limit_auth_register_window_seconds,
    name="register",
)

chat_limiter = HttpRateLimiter(
    lambda: settings.rate_limit_chat_limit,
    lambda: settings.rate_limit_chat_window_seconds,
    name="chat",
)

tools_execute_limiter = HttpRateLimiter(
    lambda: settings.rate_limit_tools_execute_limit,
    lambda: settings.rate_limit_tools_execute_window_seconds,
    name="tools_execute",
)

monitoring_limiter = HttpRateLimiter(
    lambda: settings.rate_limit_monitoring_limit,
    lambda: settings.rate_limit_monitoring_window_seconds,
    name="monitoring",
)

images_limiter = HttpRateLimiter(
    lambda: settings.rate_limit_images_limit,
    lambda: settings.rate_limit_images_window_seconds,
    name="images",
)


def rate_limit_auth_login(request: Request) -> None:
    ip = get_client_ip(request)
    auth_login_limiter.check(f"auth_login:{ip}")


def rate_limit_auth_register(request: Request) -> None:
    ip = get_client_ip(request)
    auth_register_limiter.check(f"auth_register:{ip}")


def rate_limit_chat(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> None:
    key = f"chat:{current_user.id}" if current_user else f"chat:{get_client_ip(request)}"
    chat_limiter.check(key)


def rate_limit_tools_execute(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> None:
    key = f"tools:{current_user.id}" if current_user else f"tools:{get_client_ip(request)}"
    tools_execute_limiter.check(key)


def rate_limit_monitoring(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> None:
    key = f"monitoring:{current_user.id}" if current_user else f"monitoring:{get_client_ip(request)}"
    monitoring_limiter.check(key)



def rate_limit_images(current_user: User = Depends(get_current_user)) -> None:
    images_limiter.check(f"images:{current_user.id}")
