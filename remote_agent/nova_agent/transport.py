"""WebSocket transport. The ONLY module that imports ``websockets``.

The client talks to the small ``Transport`` interface below, so the protocol
logic can be tested with an in-memory fake. This adapter translates library
exceptions into the agent's own:

    TransportClosed(code)   peer closed / socket died (code 1006 if no frame)
    HandshakeRejected(http) the HTTP upgrade was refused. The backend closes
                            *before* ``accept`` for a bad UUID, missing TLS and
                            IP rate limiting, and Starlette turns that into an
                            HTTP 403 -- so the 1008/4429 close code is never
                            visible to the agent for those cases.
    ConnectFailed           DNS / TCP / TLS / timeout
    ProtocolViolation       binary frame
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from .protocol import MAX_MESSAGE_BYTES, ProtocolViolation


class TransportClosed(Exception):
    def __init__(self, code: int = 1006, reason: str = "") -> None:
        super().__init__(f"connection closed (code {code})")
        self.code = code
        self.reason = reason


class HandshakeRejected(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"handshake rejected (HTTP {status})")
        self.status = status


class ConnectFailed(Exception):
    pass


class Transport(Protocol):
    async def send(self, text: str) -> None: ...
    async def recv(self) -> str: ...
    async def close(self, code: int = 1000, reason: str = "") -> None: ...


def require_websockets() -> None:
    try:
        import websockets  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "The 'websockets' package is not installed. Install the agent with "
            "`pip install -e .` (requires websockets>=13.1,<16)."
        ) from None


class WebsocketsTransport:
    def __init__(self, ws) -> None:
        self._ws = ws

    @staticmethod
    def _closed(exc) -> TransportClosed:
        rcvd = getattr(exc, "rcvd", None)
        code = getattr(rcvd, "code", None)
        reason = getattr(rcvd, "reason", "") or ""
        return TransportClosed(code if isinstance(code, int) else 1006, reason)

    async def send(self, text: str) -> None:
        from websockets.exceptions import ConnectionClosed
        try:
            await self._ws.send(text)
        except ConnectionClosed as exc:
            raise self._closed(exc) from None

    async def recv(self) -> str:
        from websockets.exceptions import ConnectionClosed
        try:
            message = await self._ws.recv()
        except ConnectionClosed as exc:
            raise self._closed(exc) from None
        if not isinstance(message, str):
            raise ProtocolViolation("binary frames are not supported")
        return message

    async def close(self, code: int = 1000, reason: str = "") -> None:
        try:
            await self._ws.close(code, reason[:100])
        except Exception:  # noqa: BLE001 -- already closed / dead socket
            pass


async def connect_websocket(
    url: str,
    *,
    open_timeout: float = 15.0,
    close_timeout: float = 5.0,
    ping_interval: float = 20.0,
    ping_timeout: float = 20.0,
) -> WebsocketsTransport:
    """Open a WebSocket. ``wss://`` URLs are verified against the system trust
    store by the library's default TLS context. The URL carries no token."""
    require_websockets()
    from websockets.asyncio.client import connect
    from websockets.exceptions import InvalidHandshake, InvalidStatus, InvalidURI

    try:
        ws = await connect(
            url,
            open_timeout=open_timeout,
            close_timeout=close_timeout,
            ping_interval=ping_interval,
            ping_timeout=ping_timeout,
            max_size=MAX_MESSAGE_BYTES,
        )
    except InvalidStatus as exc:
        raise HandshakeRejected(int(exc.response.status_code)) from None
    except (OSError, asyncio.TimeoutError, InvalidHandshake, InvalidURI) as exc:
        raise ConnectFailed(type(exc).__name__) from None
    return WebsocketsTransport(ws)
