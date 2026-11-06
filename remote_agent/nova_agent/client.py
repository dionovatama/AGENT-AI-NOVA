"""NOVA Remote Agent connection client (protocol v1, Phase A).

Lifecycle of one session:

    connect -> send auth -> wait 'registered' (validated) -> heartbeat loop
    (seq 1, 2, 3 ...; every ack must echo the seq) -> ended by: stop request
    (bye + close 1000), server close code, protocol violation, ack timeout.

``run()`` repeats sessions until stopped or until the server says retrying is
pointless (see ``decide_close``). Everything network related is injectable
(connector, sleeper, rng) so behaviour is testable with a mock WebSocket.
"""

from __future__ import annotations

import asyncio
import enum
import json
import logging
import platform
import random
import sys
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from . import __version__
from .config import AgentConfig
from .logging_setup import register_secret
from .relay_protocol import RelayProtocolViolation, build_tunnel_error, parse_server_relay_message
from .protocol import (
    BYE_MESSAGE,
    CloseCode,
    HeartbeatMismatch,
    ProtocolViolation,
    Registered,
    ServerError,
    build_auth_message,
    build_heartbeat_message,
    decode_message,
    normalize_os_name,
    parse_registered,
    raise_if_error,
    validate_heartbeat_ack,
)
from .transport import (
    ConnectFailed,
    HandshakeRejected,
    Transport,
    TransportClosed,
    connect_websocket,
)

log = logging.getLogger("nova_agent")

Connector = Callable[[str], Awaitable[Transport]]
Sleeper = Callable[[float], Awaitable[bool]]

BACKOFF_BASE = 2.0
BACKOFF_CAP = 60.0
BACKOFF_JITTER = 0.25          # up to +25% on top of the exponential delay
SLOW_BASE = 120.0              # floor for "do not hammer" outcomes (4429, 4009, 4400, ...)
SLOW_CAP = 900.0
STABLE_SESSION_SECONDS = 600.0  # a session this long resets the repeat counters
MAX_IGNORED_MESSAGES = 100


class ExitReason(enum.Enum):
    STOPPED = 0
    INTERNAL_ERROR = 1
    CONFIG_ERROR = 2
    AUTH_FAILED = 3
    CREDENTIAL_CONFLICT = 4
    PROTOCOL_REJECTED = 5

    @property
    def exit_code(self) -> int:
        return self.value


def describe_os() -> str:
    system = platform.system() or "unknown"
    release = platform.release()
    if system == "Windows" and release == "10":
        try:
            if sys.getwindowsversion().build >= 22000:  # type: ignore[attr-defined]
                release = "11"
        except Exception:  # noqa: BLE001
            pass
    machine = {"AMD64": "x64", "x86_64": "x64", "ARM64": "arm64", "aarch64": "arm64"}.get(
        platform.machine(), platform.machine())
    return normalize_os_name(f"{system} {release} {machine}")


# ---------------------------------------------------------------------------
# Reconnect policy
# ---------------------------------------------------------------------------

class Backoff:
    """Exponential backoff with additive jitter. ``reset()`` after a healthy session."""

    def __init__(self, base: float = BACKOFF_BASE, cap: float = BACKOFF_CAP,
                 jitter: float = BACKOFF_JITTER, rng: Callable[[], float] = random.random) -> None:
        self._base, self._cap, self._jitter, self._rng = base, cap, jitter, rng
        self._attempt = 0

    def next(self) -> float:
        delay = min(self._cap, self._base * (2 ** min(self._attempt, 30)))
        self._attempt += 1
        return delay + delay * self._jitter * self._rng()

    def reset(self) -> None:
        self._attempt = 0


@dataclass(frozen=True)
class Decision:
    label: str
    slow: bool = False
    fatal: ExitReason | None = None


# Consecutive occurrences (without a stable session in between) after which
# the agent gives up instead of retrying slowly.
REPEAT_LIMITS: dict[int, tuple[int, ExitReason]] = {
    CloseCode.REPLACED: (3, ExitReason.CREDENTIAL_CONFLICT),
    CloseCode.PROTOCOL: (5, ExitReason.PROTOCOL_REJECTED),
}


def decide_close(code: int) -> Decision:
    """Policy for a close code received from the backend (see backend protocol.py)."""
    if code == CloseCode.AUTH_FAILED:
        return Decision("authentication failed (4401)", fatal=ExitReason.AUTH_FAILED)
    if code == CloseCode.REPLACED:
        return Decision("replaced by another connection or credentials revoked (4009)", slow=True)
    if code == CloseCode.RATE_LIMITED:
        return Decision("rate limited by server (4429)", slow=True)
    if code == CloseCode.PROTOCOL:
        return Decision("server reported protocol error (4400)", slow=True)
    if code in (CloseCode.POLICY, CloseCode.UNSUPPORTED, CloseCode.TOO_BIG):
        return Decision(f"request rejected by policy (close {code})", slow=True)
    if code == CloseCode.TIMEOUT:
        return Decision("server timeout (4408)")
    if code == CloseCode.INTERNAL:
        return Decision("server internal error (1011)")
    if code in (CloseCode.NORMAL, CloseCode.GOING_AWAY):
        return Decision(f"server closed the connection ({code})")
    return Decision(f"connection lost (close {code})")


@dataclass
class SessionOutcome:
    kind: str  # "stopped" | "closed" | "failed" | "rejected"
    close_code: int | None = None
    http_status: int | None = None
    detail: str = ""
    registered: bool = False
    healthy: bool = False  # at least one validated heartbeat_ack
    duration: float = 0.0


# ---------------------------------------------------------------------------
# Internal control-flow exceptions
# ---------------------------------------------------------------------------

class _Stopped(Exception):
    pass


class _Timeout(Exception):
    pass


@dataclass
class _SessionState:
    registered: bool = False
    healthy: bool = False
    peer_closed: bool = False
    relay_sessions: set[str] | None = None

    def __post_init__(self) -> None:
        if self.relay_sessions is None:
            self.relay_sessions = set()


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class AgentClient:
    def __init__(
        self,
        config: AgentConfig,
        *,
        connector: Connector | None = None,
        sleeper: Sleeper | None = None,
        rng: Callable[[], float] = random.random,
        os_name: str | None = None,
        register_timeout: float = 10.0,
        min_heartbeat_interval: float = 5.0,
        min_ack_timeout: float = 5.0,
        bye_timeout: float = 5.0,
        close_timeout: float = 5.0,
    ) -> None:
        self.config = config
        register_secret(config.token)
        self._connector: Connector = connector or connect_websocket
        self._sleeper: Sleeper = sleeper or self._interruptible_sleep
        self._os_name = os_name or describe_os()
        self._register_timeout = register_timeout
        self._min_interval = min_heartbeat_interval
        self._min_ack_timeout = min_ack_timeout
        self._bye_timeout = bye_timeout
        self._close_timeout = close_timeout
        self._backoff = Backoff(rng=rng)
        self._stop = asyncio.Event()
        self._slow_streak = 0
        self._repeats: dict[int, int] = {}

    # -- public -----------------------------------------------------------

    def request_stop(self) -> None:
        """Ask the client to shut down gracefully. Must be called from the
        event loop thread (use ``loop.call_soon_threadsafe`` otherwise)."""
        self._stop.set()

    stop = request_stop  # backwards compatible name

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    async def run(self) -> ExitReason:
        if self.config.is_insecure:
            log.warning("Using an insecure ws:// connection (development opt-in)")
        log.info("NOVA Remote Agent %s starting (protocol v1)", __version__)
        while not self._stop.is_set():
            outcome = await self._attempt()
            if outcome.kind == "stopped" or self._stop.is_set():
                break
            fatal, delay = self._plan_next(outcome)
            if fatal is not None:
                return fatal
            if await self._sleeper(delay):
                break
        log.info("NOVA Remote Agent stopped")
        return ExitReason.STOPPED

    # -- policy -----------------------------------------------------------

    def _classify(self, outcome: SessionOutcome) -> Decision:
        if outcome.kind == "rejected":
            return Decision(f"server rejected the handshake (HTTP {outcome.http_status})", slow=True)
        if outcome.kind == "closed" and outcome.close_code is not None:
            return decide_close(outcome.close_code)
        return Decision(outcome.detail or "connection failed")

    def _plan_next(self, outcome: SessionOutcome) -> tuple[ExitReason | None, float]:
        if outcome.healthy:
            self._backoff.reset()
            self._slow_streak = 0
        if outcome.duration >= STABLE_SESSION_SECONDS:
            self._repeats.clear()

        decision = self._classify(outcome)
        if decision.fatal is not None:
            log.error(
                "%s. Not reconnecting: fix the credentials (re-run `nova-agent init` with a "
                "valid token), then restart the agent.", decision.label)
            return decision.fatal, 0.0

        code = outcome.close_code if outcome.kind == "closed" else None
        if code in REPEAT_LIMITS:
            limit, reason = REPEAT_LIMITS[code]
            self._repeats[code] = self._repeats.get(code, 0) + 1
            if self._repeats[code] >= limit:
                log.error(
                    "%s occurred %d times in a row. Not reconnecting: another agent instance "
                    "may be using the same credentials, or the agent is incompatible with the server.",
                    decision.label, self._repeats[code])
                return reason, 0.0

        delay = self._backoff.next()
        if decision.slow:
            self._slow_streak += 1
            delay = max(delay, min(SLOW_BASE * (2 ** (self._slow_streak - 1)), SLOW_CAP))
        else:
            self._slow_streak = 0
        log.warning("%s; reconnecting in %.0fs", decision.label, delay)
        return None, delay

    async def _interruptible_sleep(self, delay: float) -> bool:
        """Sleep, waking early on stop. True means 'stop requested'."""
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=delay)
            return True
        except asyncio.TimeoutError:
            return False

    # -- one attempt ------------------------------------------------------

    async def _attempt(self) -> SessionOutcome:
        started = time.monotonic()
        try:
            return await self._session()
        except asyncio.CancelledError:
            raise
        except _Stopped:
            return SessionOutcome("stopped", duration=time.monotonic() - started)
        except HandshakeRejected as exc:
            return SessionOutcome("rejected", http_status=exc.status,
                                  duration=time.monotonic() - started)
        except ConnectFailed as exc:
            return SessionOutcome("failed", detail=f"connection failed ({exc})",
                                  duration=time.monotonic() - started)
        except Exception as exc:  # noqa: BLE001 -- never let the loop die
            return SessionOutcome("failed", detail=f"unexpected error ({type(exc).__name__})",
                                  duration=time.monotonic() - started)

    async def _connect(self) -> Transport:
        """Open the transport, but give up immediately if stop is requested."""
        if self._stop.is_set():
            raise _Stopped
        log.info("Connecting to NOVA backend")
        connect_task = asyncio.ensure_future(self._connector(self.config.websocket_url))
        stop_task = asyncio.ensure_future(self._stop.wait())
        try:
            await asyncio.wait({connect_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        except BaseException:
            connect_task.cancel()
            stop_task.cancel()
            await asyncio.gather(connect_task, stop_task, return_exceptions=True)
            raise
        if not stop_task.done():
            stop_task.cancel()
        await asyncio.gather(stop_task, return_exceptions=True)
        if not connect_task.done():
            connect_task.cancel()
            await asyncio.gather(connect_task, return_exceptions=True)
            raise _Stopped
        transport = connect_task.result()  # may raise ConnectFailed/HandshakeRejected
        if self._stop.is_set():
            await self._quiet_close(transport, CloseCode.NORMAL, "client stopping")
            raise _Stopped
        return transport

    async def _session(self) -> SessionOutcome:
        started = time.monotonic()
        transport = await self._connect()
        queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        reader = asyncio.create_task(self._reader(transport, queue), name="nova-agent-reader")
        st = _SessionState()
        stopped = False
        close_code, close_reason = CloseCode.NORMAL, "client closing"
        outcome: SessionOutcome

        try:
            await transport.send(build_auth_message(
                self.config.token, self._os_name, __version__, platform.node()))
            registered = await self._handshake(queue)
            st.registered = True
            log.info("Registered with NOVA backend (connection %s)", registered.connection_id)
            await self._heartbeat_loop(transport, queue, registered, st)
            raise AssertionError("heartbeat loop returned")  # pragma: no cover
        except _Stopped:
            stopped = True
            outcome = SessionOutcome("stopped")
        except TransportClosed as exc:
            st.peer_closed = True
            outcome = SessionOutcome("closed", close_code=exc.code)
        except ServerError as exc:
            # The server explains itself, then closes with the code that
            # carries the reconnect policy (e.g. 4400). Wait briefly for it.
            code = await self._drain_for_close(queue)
            st.peer_closed = code is not None
            log.warning("Server reported error '%s'", exc.code)
            outcome = (SessionOutcome("closed", close_code=code, detail=str(exc))
                       if code is not None else SessionOutcome("failed", detail=str(exc)))
            close_code, close_reason = CloseCode.PROTOCOL_ERROR, "server error"
        except (ProtocolViolation, HeartbeatMismatch) as exc:
            close_code, close_reason = CloseCode.PROTOCOL_ERROR, "protocol violation"
            outcome = SessionOutcome("failed", detail=f"protocol violation ({exc})")
        except _Timeout as exc:
            close_code, close_reason = CloseCode.TIMEOUT, "timeout"
            outcome = SessionOutcome("failed", detail=str(exc))
        finally:
            await self._teardown(
                transport, reader,
                send_bye=(stopped and st.registered and not st.peer_closed),
                code=close_code, reason=close_reason,
            )

        outcome.registered = st.registered
        outcome.healthy = st.healthy
        outcome.duration = time.monotonic() - started
        return outcome

    # -- session pieces ---------------------------------------------------

    async def _reader(self, transport: Transport, queue: asyncio.Queue) -> None:
        """Single reader task: frames (str/bytes) or one terminal exception."""
        try:
            while True:
                await queue.put(await transport.recv())
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            await queue.put(exc)

    async def _next(self, queue: asyncio.Queue, timeout: float | None):
        """('msg', frame) or ('timeout', None). Raises _Stopped, or the
        reader's terminal exception (TransportClosed, ProtocolViolation...)."""
        if self._stop.is_set():
            raise _Stopped
        getter = asyncio.ensure_future(queue.get())
        stopper = asyncio.ensure_future(self._stop.wait())
        try:
            done, _ = await asyncio.wait({getter, stopper}, timeout=timeout,
                                         return_when=asyncio.FIRST_COMPLETED)
        finally:
            pending = [t for t in (getter, stopper) if not t.done()]
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        if getter in done:
            item = getter.result()
            if isinstance(item, BaseException):
                raise item
            return "msg", item
        if stopper in done:
            raise _Stopped
        return "timeout", None

    async def _handshake(self, queue: asyncio.Queue) -> Registered:
        kind, raw = await self._next(queue, self._register_timeout)
        if kind == "timeout":
            raise _Timeout("registration timeout")
        return parse_registered(raw, self.config.agent_id)

    async def _dispatch_relay_message(self, transport: Transport, raw: object, st: _SessionState) -> None:
        try:
            msg = parse_server_relay_message(raw)
        except RelayProtocolViolation:
            # Relay dispatch shares the single reader with normal protocol
            # messages. Preserve the pre-relay behavior for server error and
            # unsupported informational frames.
            self._check_unsolicited(raw)
            return
        if msg.type == "OPEN_TUNNEL":
            st.relay_sessions.add(msg.session_id)
            await transport.send(json.dumps(build_tunnel_error(
                request_id=msg.request_id,
                session_id=msg.session_id,
                code="TARGET_UNAVAILABLE",
                message="TCP connector is not enabled on this Agent",
            ), separators=(",", ":")))
            st.relay_sessions.discard(msg.session_id)
            return
        if msg.session_id not in st.relay_sessions:
            log.debug("Ignoring stale relay frame type=%s session=%s", msg.type, msg.session_id)
            return
        if msg.type == "CLOSE_TUNNEL":
            st.relay_sessions.discard(msg.session_id)
            return
        if msg.type == "DATA":
            raise ProtocolViolation("relay DATA received without TCP connector")

    def _check_unsolicited(self, raw: object) -> None:
        data = decode_message(raw)
        raise_if_error(data)
        if data["type"] == "heartbeat_ack":
            raise ProtocolViolation("unexpected heartbeat_ack")
        log.debug("Ignoring unsupported server message")

    async def _heartbeat_loop(self, transport: Transport, queue: asyncio.Queue,
                              reg: Registered, st: _SessionState) -> None:
        # Cadence comes from the server. Never faster than min_interval unless
        # that would exceed half the server's own timeout.
        interval = max(reg.heartbeat_interval, min(self._min_interval, reg.heartbeat_timeout / 2))
        ack_timeout = max(reg.heartbeat_timeout - interval, self._min_ack_timeout)
        seq = 0
        next_due = time.monotonic()
        while True:
            while (remaining := next_due - time.monotonic()) > 0:
                kind, raw = await self._next(queue, remaining)
                if kind == "msg":
                    await self._dispatch_relay_message(transport, raw, st)

            seq += 1
            await transport.send(build_heartbeat_message(seq))
            sent_at = time.monotonic()
            deadline = sent_at + ack_timeout
            ignored = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _Timeout("heartbeat ack timeout")
                kind, raw = await self._next(queue, remaining)
                if kind == "timeout":
                    raise _Timeout("heartbeat ack timeout")
                data = decode_message(raw)
                raise_if_error(data)
                if data["type"] == "heartbeat_ack":
                    validate_heartbeat_ack(data, seq)
                    break
                ignored += 1
                if data["type"] in {"OPEN_TUNNEL", "DATA", "CLOSE_TUNNEL"}:
                    await self._dispatch_relay_message(transport, raw, st)
                    continue
                if ignored > MAX_IGNORED_MESSAGES:
                    raise ProtocolViolation("too many unexpected messages")
            if not st.healthy:
                st.healthy = True
                log.info("Heartbeat established (interval %.0fs)", interval)
            next_due = sent_at + interval

    async def _drain_for_close(self, queue: asyncio.Queue, timeout: float = 2.0) -> int | None:
        deadline = time.monotonic() + timeout
        try:
            while (remaining := deadline - time.monotonic()) > 0:
                kind, _ = await self._next(queue, remaining)
                if kind == "timeout":
                    break
        except TransportClosed as exc:
            return exc.code
        except (_Stopped, Exception):  # noqa: BLE001
            return None
        return None

    async def _quiet_close(self, transport: Transport, code: int, reason: str) -> None:
        try:
            await asyncio.wait_for(transport.close(code, reason), self._close_timeout)
        except Exception:  # noqa: BLE001
            pass

    async def _teardown(self, transport: Transport, reader: asyncio.Task, *,
                        send_bye: bool, code: int, reason: str) -> None:
        """Heartbeat is already stopped (loop exited). Say bye if the socket
        is alive, close normally, and leave no task behind."""
        if send_bye:
            try:
                await asyncio.wait_for(transport.send(BYE_MESSAGE), self._bye_timeout)
                code, reason = CloseCode.NORMAL, "bye"
            except Exception:  # noqa: BLE001 -- peer already gone / slow
                pass
        await self._quiet_close(transport, code, reason)
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)
