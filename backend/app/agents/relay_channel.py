"""Backend-side byte channel for one relay session (Phase 4/5 bridge).

A caller (e.g. the MikroTik relay transport in Phase 5) opens a channel with
``AgentConnectionManager.open_relay_channel`` and then simply does
``await ch.send(bytes)`` / ``await ch.recv()``. Framing, sequence numbers,
the 32 KiB DATA limit and the Agent protocol stay hidden here.

Backpressure:
  * send  -> awaits the WebSocket write, so a slow Agent slows the caller.
  * recv  -> bounded queue. If the caller stops reading and the queue fills,
    the manager closes the session instead of buffering without limit.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Awaitable, Callable

from app.agents.relay_protocol import MAX_RELAY_DATA_BYTES, close_tunnel_message, data_message

SendFrame = Callable[[dict], Awaitable[None]]
OnClose = Callable[["RelayChannel", str], Awaitable[None]]


class RelayOpenError(Exception):
    """Agent refused or failed to open the tunnel. ``code`` is a TUNNEL_ERROR code."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.message = message


class RelayChannelClosed(Exception):
    """The channel is closed (by either side)."""


class RelayChannel:
    def __init__(self, *, session_id: uuid.UUID, agent_id: uuid.UUID, owner_id: uuid.UUID,
                 connection_id: uuid.UUID, send_frame: SendFrame, on_close: OnClose,
                 max_queue: int = 64) -> None:
        self.session_id = session_id
        self.agent_id = agent_id
        self.owner_id = owner_id
        self.connection_id = connection_id
        self._send_frame = send_frame
        self._on_close = on_close
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=max_queue)
        self._opened: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._seq = 0
        self._closed = False
        self.close_reason: str | None = None

    @property
    def closed(self) -> bool:
        return self._closed

    # -- caller side ------------------------------------------------------

    async def wait_open(self, timeout: float) -> None:
        try:
            await asyncio.wait_for(asyncio.shield(self._opened), timeout)
        except asyncio.TimeoutError:
            raise RelayOpenError("TIMEOUT", "agent did not answer in time") from None

    async def send(self, data: bytes) -> None:
        if self._closed:
            raise RelayChannelClosed()
        for i in range(0, len(data), MAX_RELAY_DATA_BYTES):
            if self._closed:
                raise RelayChannelClosed()
            chunk = data[i:i + MAX_RELAY_DATA_BYTES]
            await self._send_frame(data_message(session_id=self.session_id, seq=self._seq, data=chunk))
            self._seq += 1

    async def recv(self) -> bytes | None:
        """Next chunk from the device, or ``None`` once the channel ended."""
        item = await self._queue.get()
        if item is None:
            self._queue.put_nowait(None)  # keep EOF sticky for later recv() calls
        return item

    async def close(self, reason: str = "requested") -> None:
        if self._closed:
            return
        await self._on_close(self, reason)

    # -- manager side -----------------------------------------------------

    def _resolve_open(self) -> None:
        if not self._opened.done():
            self._opened.set_result(None)

    def _fail_open(self, code: str, message: str = "") -> None:
        if not self._opened.done():
            self._opened.set_exception(RelayOpenError(code, message))
            self._opened.exception()  # mark retrieved: no "never retrieved" log noise
        self._end("error")

    def _feed(self, data: bytes) -> bool:
        """False when the inbound queue is full (caller too slow)."""
        if self._closed:
            return True
        try:
            self._queue.put_nowait(data)
            return True
        except asyncio.QueueFull:
            return False

    def _end(self, reason: str) -> None:
        if self._closed:
            return
        self._closed = True
        self.close_reason = reason
        if not self._opened.done():
            self._opened.set_exception(RelayOpenError("CANCELLED", "closed before open"))
            self._opened.exception()
        # EOF marker must always fit, even if the queue is full.
        while True:
            try:
                self._queue.put_nowait(None)
                break
            except asyncio.QueueFull:
                try:
                    self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
