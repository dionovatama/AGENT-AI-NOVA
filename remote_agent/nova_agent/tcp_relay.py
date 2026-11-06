"""TCP relay connector (Phase 4).

Turns authorized ``OPEN_TUNNEL`` requests into local TCP connections and
forwards bytes both ways as ``DATA`` frames. It never decides *where* to
connect: :class:`~.relay_policy.AllowList` does.

Design notes
  * Opening a session runs in its own task, so a slow connect never stalls the
    heartbeat loop that dispatches relay frames.
  * TCP -> WebSocket: one ``read`` -> one awaited ``send``. While the
    WebSocket is slow we stop reading, so the kernel TCP window applies
    backpressure to the device.
  * WebSocket -> TCP: bounded queue. If the backend outruns the device and the
    queue fills, the session is closed (``error``) instead of buffering
    without limit.
  * Per-session idle timeout, per-Agent concurrent session cap, connect and
    DNS timeouts. All error text sent to the backend is a fixed safe string
    (no addresses, no OS error detail).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from .relay_policy import AllowList, TargetNotAllowed
from .relay_protocol import (
    MAX_RELAY_DATA_BYTES,
    RelayCommand,
    build_tunnel_error,
    build_tunnel_opened,
)

log = logging.getLogger("nova_agent.relay")

Send = Callable[[dict], Awaitable[None]]


@dataclass(frozen=True)
class RelayLimits:
    max_sessions: int = 8
    resolve_timeout: float = 5.0
    connect_timeout: float = 10.0
    idle_timeout: float = 60.0
    inbound_queue: int = 32


@dataclass
class _Session:
    request_id: str
    session_id: str
    target_id: str
    port: int
    task: asyncio.Task | None = None
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    stop_reason: str = "requested"
    notify_backend: bool = True
    inbound: asyncio.Queue | None = None
    last_in_seq: int = -1
    last_activity: float = field(default_factory=time.monotonic)
    bytes_to_device: int = 0
    bytes_from_device: int = 0

    def finish(self, reason: str, *, notify: bool) -> None:
        if not self.stop.is_set():
            self.stop_reason = reason
            self.notify_backend = notify
            self.stop.set()


class TcpRelayManager:
    def __init__(self, allow_list: AllowList, send: Send, limits: RelayLimits | None = None) -> None:
        self._allow = allow_list
        self._send = send
        self._limits = limits or RelayLimits()
        self._sessions: dict[str, _Session] = {}

    @property
    def active_sessions(self) -> int:
        return len(self._sessions)

    # -- backend -> agent -------------------------------------------------

    async def open(self, cmd: RelayCommand) -> None:
        assert cmd.session_id and cmd.request_id and cmd.target_id and cmd.port
        if cmd.session_id in self._sessions:
            await self._error(cmd, "PROTOCOL_ERROR", "session already exists")
            return
        if len(self._sessions) >= self._limits.max_sessions:
            log.warning("relay denied reason=resource_limit target=%s", cmd.target_id)
            await self._error(cmd, "RESOURCE_LIMIT", "too many relay sessions")
            return
        sess = _Session(cmd.request_id, cmd.session_id, cmd.target_id, cmd.port,
                        inbound=asyncio.Queue(maxsize=self._limits.inbound_queue))
        self._sessions[cmd.session_id] = sess
        sess.task = asyncio.create_task(self._run(sess), name=f"nova-relay-{cmd.session_id[:8]}")

    def feed(self, session_id: str, seq: int, data: bytes) -> None:
        """Backend DATA. Unknown session = stale frame, ignored."""
        sess = self._sessions.get(session_id)
        if sess is None or sess.inbound is None:
            return
        if seq <= sess.last_in_seq:
            log.warning("relay closing session=%s reason=bad_sequence", session_id)
            sess.finish("error", notify=True)
            return
        sess.last_in_seq = seq
        try:
            sess.inbound.put_nowait(data)
        except asyncio.QueueFull:
            log.warning("relay closing session=%s reason=inbound_overflow", session_id)
            sess.finish("error", notify=True)

    def close(self, session_id: str, reason: str = "requested") -> None:
        sess = self._sessions.get(session_id)
        if sess is not None:
            sess.finish(reason, notify=False)  # backend asked; no echo

    async def close_all(self) -> None:
        """Agent connection is going away: drop every socket, no frames."""
        tasks = []
        for sess in list(self._sessions.values()):
            sess.finish("agent_disconnect", notify=False)
            if sess.task is not None:
                tasks.append(sess.task)
        if tasks:
            await asyncio.wait(tasks, timeout=5.0)
            for t in tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    # -- one session ------------------------------------------------------

    async def _error(self, cmd: RelayCommand, code: str, message: str) -> None:
        await self._send(build_tunnel_error(
            request_id=cmd.request_id, session_id=cmd.session_id, code=code, message=message))

    async def _run(self, sess: _Session) -> None:
        started = time.monotonic()
        writer: asyncio.StreamWriter | None = None
        try:
            reader, writer = await self._connect(sess)
            if sess.stop.is_set():  # closed while connecting
                return
            await self._send(build_tunnel_opened(
                request_id=sess.request_id, session_id=sess.session_id))
            log.info("relay open session=%s target=%s port=%d",
                     sess.session_id, sess.target_id, sess.port)
            await self._pump(sess, reader, writer)
        except _OpenFailed as exc:
            log.warning("relay denied session=%s target=%s code=%s",
                        sess.session_id, sess.target_id, exc.code)
            try:
                await self._send(build_tunnel_error(
                    request_id=sess.request_id, session_id=sess.session_id,
                    code=exc.code, message=exc.message))
            except Exception:  # noqa: BLE001 -- connection already gone
                pass
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- includes TransportClosed
            log.info("relay session=%s ended: %s", sess.session_id, type(exc).__name__)
            sess.finish("error", notify=False)
        finally:
            self._sessions.pop(sess.session_id, None)
            if writer is not None:
                writer.close()
                try:
                    await asyncio.wait_for(writer.wait_closed(), 2.0)
                except Exception:  # noqa: BLE001
                    pass
            if sess.stop.is_set():
                log.info("relay closed session=%s reason=%s to_device=%d from_device=%d secs=%.1f",
                         sess.session_id, sess.stop_reason, sess.bytes_to_device,
                         sess.bytes_from_device, time.monotonic() - started)
                if sess.notify_backend:
                    try:
                        await self._send({"type": "CLOSE_TUNNEL", "session_id": sess.session_id,
                                          "reason": sess.stop_reason})
                    except Exception:  # noqa: BLE001
                        pass

    async def _connect(self, sess: _Session):
        lim = self._limits
        try:
            _, addrs = await asyncio.wait_for(
                self._allow.authorize(sess.target_id, sess.port), lim.resolve_timeout)
        except TargetNotAllowed:
            raise _OpenFailed("TARGET_NOT_ALLOWED", "target not allowed") from None
        except asyncio.TimeoutError:
            raise _OpenFailed("TIMEOUT", "name resolution timed out") from None
        except OSError:
            raise _OpenFailed("TARGET_UNAVAILABLE", "target could not be resolved") from None

        deadline = time.monotonic() + lim.connect_timeout
        timed_out = False
        for addr in addrs:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            try:
                return await asyncio.wait_for(asyncio.open_connection(addr, sess.port), remaining)
            except asyncio.TimeoutError:
                timed_out = True
                break
            except OSError:
                continue
        if timed_out:
            raise _OpenFailed("TIMEOUT", "connect timed out")
        raise _OpenFailed("CONNECT_FAILED", "could not connect to target")

    async def _pump(self, sess: _Session, reader: asyncio.StreamReader,
                    writer: asyncio.StreamWriter) -> None:
        async def tcp_to_ws() -> None:
            seq = 0
            while True:
                chunk = await reader.read(MAX_RELAY_DATA_BYTES)
                if not chunk:
                    sess.finish("peer_closed", notify=True)
                    return
                sess.last_activity = time.monotonic()
                sess.bytes_from_device += len(chunk)
                await self._send({"type": "DATA", "session_id": sess.session_id, "seq": seq,
                                  "data": base64.b64encode(chunk).decode("ascii")})
                seq += 1

        async def ws_to_tcp() -> None:
            assert sess.inbound is not None
            while True:
                data = await sess.inbound.get()
                writer.write(data)
                await writer.drain()
                sess.last_activity = time.monotonic()
                sess.bytes_to_device += len(data)

        async def watchdog() -> None:
            idle = self._limits.idle_timeout
            while True:
                await asyncio.sleep(min(1.0, idle / 2))
                if time.monotonic() - sess.last_activity > idle:
                    sess.finish("timeout", notify=True)
                    return

        tasks = [asyncio.create_task(c()) for c in (tcp_to_ws, ws_to_tcp, watchdog)]
        stopper = asyncio.create_task(sess.stop.wait())
        try:
            done, _ = await asyncio.wait({*tasks, stopper}, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                if t is not stopper and t.exception() is not None:
                    raise t.exception()  # type: ignore[misc]
            if not sess.stop.is_set():
                sess.finish("peer_closed", notify=True)
        finally:
            for t in (*tasks, stopper):
                t.cancel()
            await asyncio.gather(*tasks, stopper, return_exceptions=True)


class _OpenFailed(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code)
        self.code = code
        self.message = message
