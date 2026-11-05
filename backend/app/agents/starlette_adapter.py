"""
Adapter Starlette WebSocket -> SocketLike (lihat manager.SocketLike).

STATUS: tipis dan belum dijalankan di sandbox pengembangan (tanpa
starlette); dicakup oleh tests/test_agents_api.py.
"""

from __future__ import annotations

import asyncio
import json

from starlette.websockets import WebSocket, WebSocketState

from app.agents.protocol import SocketClosed, UnsupportedFrame


class StarletteSocket:
    def __init__(self, ws: WebSocket) -> None:
        self._ws = ws

    @property
    def is_secure(self) -> bool:
        # Di belakang reverse proxy, scheme 'wss' hanya muncul jika uvicorn
        # dijalankan dengan --proxy-headers dan --forwarded-allow-ips yang
        # tepat (lihat app/agents/README.md).
        return self._ws.url.scheme == "wss"

    @property
    def client_ip(self) -> str:
        return self._ws.client.host if self._ws.client else "unknown"

    async def accept(self) -> None:
        await self._ws.accept()

    async def receive_text(self, timeout: float) -> str:
        message = await asyncio.wait_for(self._ws.receive(), timeout)
        if message["type"] == "websocket.disconnect":
            raise SocketClosed(message.get("code", 1006), message.get("reason") or "")
        text = message.get("text")
        if text is None:
            raise UnsupportedFrame()
        return text

    async def send_json(self, payload: dict) -> None:
        if self._ws.application_state != WebSocketState.CONNECTED:
            raise SocketClosed(1006)
        try:
            await self._ws.send_text(json.dumps(payload))
        except Exception as exc:  # noqa: BLE001 -- RuntimeError / disconnect
            raise SocketClosed(1006) from exc

    async def close(self, code: int, reason: str = "") -> None:
        try:
            await self._ws.close(code=code, reason=reason[:120])
        except Exception:  # noqa: BLE001 -- sudah tertutup; tidak perlu dilaporkan
            pass
