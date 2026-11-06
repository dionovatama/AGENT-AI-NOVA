"""
Agent Connection Manager -- inti logika WebSocket Remote Agent (Phase A).

Modul ini sengaja TIDAK bergantung pada FastAPI/Starlette/SQLAlchemy:
socket dan store disuntikkan (lihat SocketLike dan store.AgentStore).
Hasilnya logika koneksi bisa diuji dengan socket/store palsu, termasuk
skenario race antar-worker.

Alur satu koneksi:

    handshake -> [cek UUID, cek TLS] -> accept
              -> frame 'auth' (timeout) -> verifikasi token constant-time
              -> claim_connection (status 'connecting', ambil alih kepemilikan)
              -> registry lokal (tutup koneksi lokal lama bila ada)
              -> kirim 'registered' -> mark_online ('online')
              -> loop heartbeat (timeout) -> release_connection(status akhir)

Prinsip multi-worker (tanpa Redis):
  * Kepemilikan koneksi = kolom connection_id di DB. Semua tulis state
    kondisional pada connection_id, jadi koneksi lama/worker lain tidak
    bisa menimpa koneksi baru.
  * Heartbeat ditulis ke DB oleh worker pemilik; status dibaca lewat
    effective_status() (kesegaran heartbeat), bukan dict memori worker.
  * Koneksi yang kehilangan kepemilikan (record_heartbeat -> False)
    menutup dirinya sendiri dengan kode 4009.
  * Pengiriman command lintas-worker butuh pub/sub (LISTEN/NOTIFY atau
    Redis) -- sengaja di luar scope Phase A.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Protocol

from app.agents.protocol import (
    CLEAN_CLOSE_CODES,
    CloseCode,
    MessageTooLarge,
    ProtocolError,
    SocketClosed,
    UnsupportedFrame,
    error_message,
    heartbeat_ack_message,
    parse_agent_id,
    parse_auth,
    parse_client_message,
    registered_message,
)
from app.agents.ratelimit import SlidingWindowLimiter
from app.agents.registry import LiveConnection, LocalConnectionRegistry
from app.agents.relay_protocol import (
    RELAY_MESSAGE_TYPES, RelayProtocolError, close_tunnel_message,
    open_tunnel_message, parse_relay_message,
)
from app.agents.relay_channel import RelayChannel, RelayOpenError
from app.agents.relay_sessions import RelaySessionError, RelaySessionRegistry
from app.agents.states import AgentStatus
from app.agents.store import AgentStore
from app.agents.tokens import DUMMY_TOKEN_HASH, verify_agent_token
from app.security.sanitization import sanitize_error_message

logger = logging.getLogger("nova.agents")

AuditSink = Callable[..., Awaitable[None]]


class SocketLike(Protocol):
    """Antarmuka minimum socket. Adapter Starlette: starlette_adapter.py."""

    is_secure: bool
    client_ip: str

    async def accept(self) -> None: ...

    async def receive_text(self, timeout: float) -> str:
        """Raise asyncio.TimeoutError / SocketClosed / UnsupportedFrame."""

    async def send_json(self, payload: dict) -> None:
        """Raise SocketClosed jika socket sudah mati."""

    async def close(self, code: int, reason: str = "") -> None:
        """Tidak pernah raise."""


@dataclass(frozen=True)
class AgentRuntimeConfig:
    auth_timeout_seconds: float = 10.0
    heartbeat_interval_seconds: float = 30.0
    heartbeat_timeout_seconds: float = 90.0
    max_message_bytes: int = 65536
    require_tls: bool = False
    # Batas tulis DB per koneksi: heartbeat yang datang lebih rapat dari ini
    # tetap di-ack tapi tidak menulis DB (anti write-amplification).
    heartbeat_min_db_interval_seconds: float = 5.0
    sweep_interval_seconds: float = 30.0
    # Rate limit autentikasi: per IP, hanya KEGAGALAN yang dihitung (auth
    # salah, timeout, frame rusak). IP yang mencapai batas ditolak SEBELUM
    # accept dan tanpa menyentuh DB. Agent sah yang berhasil auth tidak
    # terpengaruh.
    auth_fail_limit: int = 10
    auth_fail_window_seconds: float = 60.0
    # Batas koneksi yang sudah di-accept tapi belum selesai autentikasi per IP
    # (menahan slow-loris: tiap socket bisa menggantung sampai auth_timeout).
    max_pending_auth_per_ip: int = 20
    # Rate limit pesan per koneksi terautentikasi (heartbeat normal = 1 per
    # 30 dtk; default mengizinkan 20 pesan / 10 dtk).
    max_messages_per_window: int = 20
    message_window_seconds: float = 10.0
    # Relay frames use a separate budget from heartbeat/control frames.
    relay_messages_per_window: int = 200
    relay_message_window_seconds: float = 10.0

    def __post_init__(self) -> None:
        if self.heartbeat_timeout_seconds <= self.heartbeat_interval_seconds:
            raise ValueError(
                "heartbeat_timeout_seconds harus lebih besar dari "
                "heartbeat_interval_seconds"
            )
        if self.auth_timeout_seconds <= 0 or self.max_message_bytes <= 0:
            raise ValueError("auth_timeout_seconds dan max_message_bytes harus > 0")
        if (
            self.auth_fail_limit <= 0 or self.auth_fail_window_seconds <= 0
            or self.max_pending_auth_per_ip <= 0
            or self.max_messages_per_window <= 0 or self.message_window_seconds <= 0
            or self.relay_messages_per_window <= 0
            or self.relay_message_window_seconds <= 0
        ):
            raise ValueError("parameter rate limit harus > 0")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"


@dataclass
class _Session:
    agent_id: uuid.UUID
    owner_id: uuid.UUID
    connection_id: uuid.UUID
    os: str
    agent_version: str


class AgentConnectionManager:
    def __init__(
        self,
        store: AgentStore,
        cfg: AgentRuntimeConfig,
        audit: AuditSink | None = None,
        worker_id: str | None = None,
        clock: Callable[[], datetime] = _utcnow,
        mono_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.store = store
        self.cfg = cfg
        self.worker_id = worker_id or default_worker_id()
        self.registry = LocalConnectionRegistry()
        self.relay_sessions = RelaySessionRegistry(max_per_agent=8, idle_timeout=60.0)
        self.relay_channels: dict[uuid.UUID, RelayChannel] = {}
        self._audit_sink = audit
        self._clock = clock
        self._sweeper: asyncio.Task | None = None
        self._mono = mono_clock
        self.auth_failures = SlidingWindowLimiter(
            cfg.auth_fail_limit, cfg.auth_fail_window_seconds, clock=mono_clock
        )
        self._pending_auth: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    async def handle(self, sock: SocketLike, agent_id_raw: str) -> None:
        """Menangani satu koneksi sampai selesai. Tidak pernah raise
        (kecuali CancelledError, yang sengaja diteruskan)."""
        try:
            await self._handle(sock, agent_id_raw)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 -- jaring pengaman terakhir
            # Tidak ada pesan/frame klien di scope ini, jadi token tidak
            # mungkin ikut tercatat di traceback.
            logger.exception("agent ws: error tak terduga sebelum sesi aktif")
            await sock.close(CloseCode.INTERNAL, "internal error")

    async def _handle(self, sock: SocketLike, agent_id_raw: str) -> None:
        agent_id = parse_agent_id(agent_id_raw)
        if agent_id is None:
            logger.warning("agent ws ditolak: format agent id tidak valid ip=%s", sock.client_ip)
            await sock.close(CloseCode.POLICY, "invalid request")
            return

        if self.cfg.require_tls and not sock.is_secure:
            logger.warning("agent ws ditolak: koneksi non-TLS agent=%s ip=%s", agent_id, sock.client_ip)
            await sock.close(CloseCode.POLICY, "TLS required")
            return

        ip = sock.client_ip
        if self.auth_failures.is_limited(ip):
            logger.warning("agent ws ditolak: terlalu banyak auth gagal ip=%s", ip)
            await sock.close(CloseCode.RATE_LIMITED, "rate limited")
            return
        if self._pending_auth.get(ip, 0) >= self.cfg.max_pending_auth_per_ip:
            logger.warning("agent ws ditolak: terlalu banyak koneksi belum terautentikasi ip=%s", ip)
            await sock.close(CloseCode.RATE_LIMITED, "rate limited")
            return

        await sock.accept()

        self._pending_auth[ip] = self._pending_auth.get(ip, 0) + 1
        try:
            session = await self._authenticate(sock, agent_id)
        finally:
            remaining = self._pending_auth.get(ip, 1) - 1
            if remaining > 0:
                self._pending_auth[ip] = remaining
            else:
                self._pending_auth.pop(ip, None)
        if session is None:
            return
        await self._run_session(sock, session)

    def _auth_failed(self, ip: str) -> None:
        self.auth_failures.hit(ip)

    # ------------------------------------------------------------------
    # Fase 1: autentikasi + registrasi
    # ------------------------------------------------------------------

    async def _authenticate(self, sock: SocketLike, agent_id: uuid.UUID) -> _Session | None:
        ip = sock.client_ip
        try:
            raw = await sock.receive_text(self.cfg.auth_timeout_seconds)
            auth = parse_auth(raw, self.cfg.max_message_bytes)
        except asyncio.TimeoutError:
            logger.info("agent auth timeout agent=%s ip=%s", agent_id, ip)
            self._auth_failed(ip)
            await sock.close(CloseCode.TIMEOUT, "authentication timeout")
            return None
        except SocketClosed:
            return None
        except UnsupportedFrame:
            self._auth_failed(ip)
            await sock.close(CloseCode.UNSUPPORTED, "text frames only")
            return None
        except MessageTooLarge:
            self._auth_failed(ip)
            await sock.close(CloseCode.TOO_BIG, "message too large")
            return None
        except ProtocolError:
            logger.info("agent auth malformed agent=%s ip=%s", agent_id, ip)
            self._auth_failed(ip)
            await sock.close(CloseCode.PROTOCOL, "invalid authentication message")
            return None

        record = await self.store.get_auth_record(agent_id)

        # Selalu jalankan perbandingan constant-time, juga saat agent tidak
        # ada (pakai hash dummy), supaya timing tidak membocorkan keberadaan.
        stored_hash = record.token_hash if record is not None else DUMMY_TOKEN_HASH
        token_ok = verify_agent_token(auth.token, stored_hash)

        if record is None or not token_ok or not record.owner_active:
            reason = (
                "unknown_agent" if record is None
                else "bad_token" if not token_ok
                else "owner_inactive"
            )
            # Alasan hanya masuk log server; peer menerima pesan seragam.
            logger.warning("agent auth gagal agent=%s reason=%s ip=%s", agent_id, reason, ip)
            self._auth_failed(ip)
            await sock.close(CloseCode.AUTH_FAILED, "authentication failed")
            return None

        # Token lolos verifikasi di atas, tapi itu terjadi SEBELUM claim. Antara
        # keduanya REST bisa me-rotate token / menghapus agent / menonaktifkan
        # owner. Karena itu hash yang baru diverifikasi dikirim ke store, yang
        # memvalidasi ulang secara atomik di dalam transaksi claim; token yang
        # sudah dicabut tidak akan pernah menghasilkan koneksi.
        connection_id = uuid.uuid4()
        claim = await self.store.claim_connection(
            agent_id, connection_id, self.worker_id, auth.os, auth.agent_version,
            self._clock(), stored_hash, hostname=auth.hostname,
        )
        if not claim.claimed:
            logger.warning(
                "agent claim ditolak agent=%s reason=%s ip=%s",
                agent_id, claim.reject_reason or "unknown", ip,
            )
            self._auth_failed(ip)
            await sock.close(CloseCode.AUTH_FAILED, "authentication failed")
            return None

        session = _Session(agent_id, record.owner_id, connection_id, auth.os, auth.agent_version)

        # Duplicate di worker yang sama: koneksi baru menang, yang lama ditutup.
        # (Duplicate lintas-worker ditangani lewat connection_id di DB.)
        previous = self.registry.register(
            LiveConnection(agent_id, connection_id, record.owner_id, sock)
        )
        if previous is not None:
            logger.info("agent duplicate: koneksi lokal lama digantikan agent=%s", agent_id)
            await previous.sock.close(CloseCode.REPLACED, "replaced by a newer connection")
        if claim.replaced_connection_id is not None:
            logger.info(
                "agent mengambil alih koneksi sebelumnya agent=%s replaced_worker=%s",
                agent_id, claim.replaced_worker_id,
            )
        return session

    # ------------------------------------------------------------------
    # Fase 2: sesi aktif
    # ------------------------------------------------------------------

    async def _run_session(self, sock: SocketLike, s: _Session) -> None:
        cfg = self.cfg
        final_status = AgentStatus.DISCONNECTED
        final_error: str | None = None
        disconnect_reason = "connection_lost"
        superseded = False
        connected_audited = False

        try:
            await sock.send_json(
                registered_message(
                    s.agent_id, s.connection_id,
                    cfg.heartbeat_interval_seconds, cfg.heartbeat_timeout_seconds,
                    self._clock(),
                )
            )
            if not await self.store.mark_online(s.agent_id, s.connection_id, self._clock()):
                superseded = True
                disconnect_reason = "superseded"
                await sock.close(CloseCode.REPLACED, "connection superseded")
                return

            logger.info(
                "agent online agent=%s conn=%s worker=%s os=%s version=%s",
                s.agent_id, s.connection_id, self.worker_id, s.os, s.agent_version,
            )
            await self._audit("agent.connected", "SUCCESS", s, {"os": s.os, "agent_version": s.agent_version})
            connected_audited = True

            last_db_write = time.monotonic()
            msg_limiter = SlidingWindowLimiter(
                cfg.max_messages_per_window, cfg.message_window_seconds, clock=self._mono
            )
            relay_limiter = SlidingWindowLimiter(
                cfg.relay_messages_per_window,
                cfg.relay_message_window_seconds,
                clock=self._mono,
            )
            while True:
                try:
                    raw = await sock.receive_text(cfg.heartbeat_timeout_seconds)
                except asyncio.TimeoutError:
                    disconnect_reason = "heartbeat_timeout"
                    logger.warning("agent heartbeat timeout agent=%s conn=%s", s.agent_id, s.connection_id)
                    await sock.close(CloseCode.TIMEOUT, "heartbeat timeout")
                    return

                msg = parse_client_message(raw, cfg.max_message_bytes)

                if msg.type in RELAY_MESSAGE_TYPES:
                    if not relay_limiter.hit("relay"):
                        disconnect_reason = "relay_rate_limited"
                        logger.warning(
                            "agent relay flood agent=%s conn=%s ip=%s",
                            s.agent_id, s.connection_id, sock.client_ip,
                        )
                        await sock.close(CloseCode.RATE_LIMITED, "relay rate limited")
                        return
                    await self._handle_relay_message(raw, s)
                    continue

                if not msg_limiter.hit("msg"):
                    disconnect_reason = "message_rate_limited"
                    logger.warning(
                        "agent message flood agent=%s conn=%s ip=%s",
                        s.agent_id, s.connection_id, sock.client_ip,
                    )
                    await sock.close(CloseCode.RATE_LIMITED, "rate limited")
                    return

                if msg.type == "bye":
                    final_status = AgentStatus.OFFLINE
                    disconnect_reason = "bye"
                    await sock.close(CloseCode.NORMAL, "bye")
                    return

                # heartbeat
                now_mono = time.monotonic()
                if now_mono - last_db_write >= cfg.heartbeat_min_db_interval_seconds:
                    if not await self.store.record_heartbeat(s.agent_id, s.connection_id, self._clock()):
                        superseded = True
                        disconnect_reason = "superseded"
                        logger.info("agent kehilangan kepemilikan koneksi agent=%s conn=%s", s.agent_id, s.connection_id)
                        await sock.close(CloseCode.REPLACED, "connection superseded")
                        return
                    last_db_write = now_mono
                await sock.send_json(heartbeat_ack_message(msg.seq, self._clock()))

        except SocketClosed as exc:
            if exc.code in CLEAN_CLOSE_CODES:
                final_status = AgentStatus.OFFLINE
                disconnect_reason = "clean_close"
            else:
                disconnect_reason = f"socket_closed_{exc.code}"
        except UnsupportedFrame:
            disconnect_reason = "unsupported_frame"
            await sock.close(CloseCode.UNSUPPORTED, "text frames only")
        except MessageTooLarge:
            disconnect_reason = "message_too_large"
            await sock.close(CloseCode.TOO_BIG, "message too large")
        except ProtocolError as exc:
            disconnect_reason = "protocol_error"
            try:
                await sock.send_json(error_message("protocol_error", str(exc)))
            except SocketClosed:
                pass
            await sock.close(CloseCode.PROTOCOL, "protocol error")
        except asyncio.CancelledError:
            disconnect_reason = "server_cancelled"
            raise
        except Exception as exc:  # noqa: BLE001
            final_status = AgentStatus.ERROR
            disconnect_reason = "backend_error"
            final_error = (
                f"{type(exc).__name__}: {sanitize_error_message(str(exc)) or ''}"
            )[:200]
            logger.exception("agent session error agent=%s conn=%s", s.agent_id, s.connection_id)
            await sock.close(CloseCode.INTERNAL, "internal error")
        finally:
            self.relay_sessions.cleanup_connection(agent_id=s.agent_id, connection_id=s.connection_id)
            self._end_channels_for_connection(s.agent_id, s.connection_id)
            self.registry.unregister(s.agent_id, s.connection_id)
            if not superseded:
                try:
                    await asyncio.shield(
                        self.store.release_connection(
                            s.agent_id, s.connection_id, final_status.value,
                            self._clock(), final_error,
                        )
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("agent release gagal agent=%s conn=%s", s.agent_id, s.connection_id)
            if connected_audited:
                await self._audit(
                    "agent.disconnected",
                    "SUCCESS" if final_status != AgentStatus.ERROR else "FAILED",
                    s,
                    {"reason": disconnect_reason, "final_status": final_status.value},
                    error=final_error,
                )
            logger.info(
                "agent keluar agent=%s conn=%s reason=%s status=%s",
                s.agent_id, s.connection_id, disconnect_reason,
                "superseded" if superseded else final_status.value,
            )

    async def _handle_relay_message(self, raw: str, s: _Session) -> None:
        """Dispatch Agent->Backend relay frames through the existing single reader."""
        try:
            msg = parse_relay_message(raw, direction="agent_to_server")
            common = {"agent_id": s.agent_id, "owner_id": s.owner_id, "connection_id": s.connection_id}
            if msg.type == "TUNNEL_OPENED":
                session = self.relay_sessions.get(uuid.UUID(msg.session_id), **common)
                if session.request_id != uuid.UUID(msg.request_id):
                    raise RelayProtocolError("relay request/session mismatch")
                self.relay_sessions.mark_open(uuid.UUID(msg.session_id), **common)
                channel = self.relay_channels.get(uuid.UUID(msg.session_id))
                if channel is not None:
                    channel._resolve_open()
            elif msg.type == "TUNNEL_ERROR":
                session = self.relay_sessions.get(uuid.UUID(msg.session_id), **common)
                if session.request_id != uuid.UUID(msg.request_id):
                    raise RelayProtocolError("relay request/session mismatch")
                self.relay_sessions.fail(
                    uuid.UUID(msg.session_id),
                    code=msg.code or "PROTOCOL_ERROR",
                    **common,
                )
                channel = self.relay_channels.pop(uuid.UUID(msg.session_id), None)
                if channel is not None:
                    channel._fail_open(msg.code or "PROTOCOL_ERROR", msg.message or "")
            elif msg.type == "DATA":
                try:
                    self.relay_sessions.touch(uuid.UUID(msg.session_id), **common)
                    channel = self.relay_channels.get(uuid.UUID(msg.session_id))
                    if channel is not None and not channel._feed(msg.data or b""):
                        logger.warning("relay inbound overflow agent=%s session=%s", s.agent_id, msg.session_id)
                        await self._close_channel(channel, "error")
                except RelaySessionError as exc:
                    if "not found" in str(exc) or "not open" in str(exc):
                        logger.debug(
                            "ignoring stale relay DATA agent=%s session=%s",
                            s.agent_id, msg.session_id,
                        )
                        return
                    raise
            elif msg.type == "CLOSE_TUNNEL":
                try:
                    self.relay_sessions.close(uuid.UUID(msg.session_id), **common)
                    channel = self.relay_channels.pop(uuid.UUID(msg.session_id), None)
                    if channel is not None:
                        channel._end(msg.reason or "peer_closed")
                except RelaySessionError as exc:
                    if "not found" in str(exc) or "invalid relay state" in str(exc):
                        logger.debug(
                            "ignoring stale relay CLOSE_TUNNEL agent=%s session=%s",
                            s.agent_id, msg.session_id,
                        )
                        return
                    raise
            logger.debug("relay frame agent=%s type=%s session=%s", s.agent_id, msg.type, msg.session_id)
        except (RelayProtocolError, RelaySessionError, ValueError) as exc:
            logger.warning("invalid relay frame agent=%s: %s", s.agent_id, exc)
            await self._audit("agent.relay.protocol_error", "FAILED", s, {"reason": "invalid_relay_frame"}, error=str(exc)[:160])
            raise ProtocolError("invalid relay frame")

    async def open_relay_tunnel(
        self, *, agent_id: uuid.UUID, owner_id: uuid.UUID, connection_id: uuid.UUID,
        target_id: uuid.UUID, port: int,
    ) -> dict[str, Any]:
        """Create an owned relay session and send OPEN_TUNNEL on the live Agent socket."""
        live = self.registry.get(agent_id)
        if live is None or live.connection_id != connection_id or live.owner_id != owner_id:
            raise RelaySessionError("agent connection not found")
        session = self.relay_sessions.create(
            agent_id=agent_id, owner_id=owner_id, connection_id=connection_id,
            target_id=target_id, port=port,
        )
        payload = open_tunnel_message(
            request_id=session.request_id, session_id=session.session_id,
            target_id=target_id, port=port,
        )
        try:
            await live.sock.send_json(payload)
        except Exception:
            self.relay_sessions.fail(
                session.session_id, agent_id=agent_id, owner_id=owner_id,
                connection_id=connection_id, code="CONNECT_FAILED",
            )
            raise
        return payload

    async def open_relay_channel(
        self, *, agent_id: uuid.UUID, owner_id: uuid.UUID, connection_id: uuid.UUID,
        target_id: uuid.UUID, port: int, open_timeout: float = 15.0,
    ) -> RelayChannel:
        """Open a relay session and return a byte channel once the Agent confirms.

        Raises RelaySessionError (no live connection / limit) or RelayOpenError
        (Agent refused: TARGET_NOT_ALLOWED, CONNECT_FAILED, TIMEOUT, ...).
        """
        live = self.registry.get(agent_id)
        if live is None or live.connection_id != connection_id or live.owner_id != owner_id:
            raise RelaySessionError("agent connection not found")
        session = self.relay_sessions.create(
            agent_id=agent_id, owner_id=owner_id, connection_id=connection_id,
            target_id=target_id, port=port,
        )
        common = {"agent_id": agent_id, "owner_id": owner_id, "connection_id": connection_id}

        async def send_frame(frame: dict) -> None:
            await live.sock.send_json(frame)

        channel = RelayChannel(
            session_id=session.session_id, agent_id=agent_id, owner_id=owner_id,
            connection_id=connection_id, send_frame=send_frame, on_close=self._close_channel,
        )
        self.relay_channels[session.session_id] = channel
        try:
            await live.sock.send_json(open_tunnel_message(
                request_id=session.request_id, session_id=session.session_id,
                target_id=target_id, port=port,
            ))
            await channel.wait_open(open_timeout)
        except BaseException as exc:
            self.relay_channels.pop(session.session_id, None)
            channel._end("error")
            # Agent refusal: the TUNNEL_ERROR handler already failed the session.
            # Timeout / send failure / cancel: fail it here and tell the Agent.
            refused = isinstance(exc, RelayOpenError) and exc.code != "TIMEOUT"
            if not refused:
                try:
                    self.relay_sessions.fail(
                        session.session_id,
                        code="TIMEOUT" if isinstance(exc, RelayOpenError) else "CONNECT_FAILED",
                        **common,
                    )
                    await live.sock.send_json(
                        close_tunnel_message(session_id=session.session_id, reason="timeout"))
                except Exception:  # noqa: BLE001 -- best-effort cleanup
                    pass
            raise
        return channel

    async def _close_channel(self, channel: RelayChannel, reason: str) -> None:
        """Backend-initiated close: notify the Agent, then free everything."""
        if channel.closed:
            return
        self.relay_channels.pop(channel.session_id, None)
        common = {"agent_id": channel.agent_id, "owner_id": channel.owner_id,
                  "connection_id": channel.connection_id}
        try:
            self.relay_sessions.close(channel.session_id, **common)
        except RelaySessionError:
            pass
        channel._end(reason)
        live = self.registry.get(channel.agent_id)
        if live is not None and live.connection_id == channel.connection_id:
            try:
                await live.sock.send_json(close_tunnel_message(
                    session_id=channel.session_id,
                    reason=reason if reason in {"requested", "timeout", "error", "backend_shutdown"} else "requested",
                ))
            except Exception:  # noqa: BLE001 -- socket already gone
                pass

    def _end_channels_for_connection(self, agent_id: uuid.UUID, connection_id: uuid.UUID) -> None:
        for sid, ch in list(self.relay_channels.items()):
            if ch.agent_id == agent_id and ch.connection_id == connection_id:
                self.relay_channels.pop(sid, None)
                ch._end("agent_disconnect")

    # ------------------------------------------------------------------
    # Audit (best effort -- tidak boleh menjatuhkan koneksi)
    # ------------------------------------------------------------------

    async def _audit(
        self, action: str, result_status: str, s: _Session, metadata: dict[str, Any],
        error: str | None = None,
    ) -> None:
        if self._audit_sink is None:
            return
        try:
            await self._audit_sink(
                action=action,
                result_status=result_status,
                owner_id=s.owner_id,
                agent_id=s.agent_id,
                metadata={"connection_id": str(s.connection_id), "worker_id": self.worker_id, **metadata},
                error=error,
            )
        except Exception:  # noqa: BLE001
            logger.warning("audit agent gagal action=%s", action, exc_info=True)

    # ------------------------------------------------------------------
    # Sweeper + lifecycle
    # ------------------------------------------------------------------

    async def sweep_once(self) -> int:
        now = self._clock()
        cutoff = datetime.fromtimestamp(
            now.timestamp() - self.cfg.heartbeat_timeout_seconds, tz=timezone.utc
        )
        self.auth_failures.prune()
        relay_expired = self.relay_sessions.expire_idle()
        if relay_expired:
            logger.warning("agent relay sweeper: %d idle relay session -> closed", relay_expired)
        swept = await self.store.mark_stale(cutoff, now)
        if swept:
            logger.warning("agent sweeper: %d agent heartbeat basi -> disconnected", swept)
        return swept

    async def _sweeper_loop(self) -> None:
        while True:
            try:
                await self.sweep_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("agent sweeper iterasi gagal")
            await asyncio.sleep(self.cfg.sweep_interval_seconds)

    def start(self) -> None:
        if self._sweeper is None or self._sweeper.done():
            self._sweeper = asyncio.create_task(self._sweeper_loop())

    async def disconnect_local(
        self, agent_id: uuid.UUID, code: int = CloseCode.REPLACED,
        reason: str = "connection revoked",
    ) -> bool:
        """Tutup koneksi agent yang dipegang proses ini (dipakai REST saat
        agent dihapus/token di-rotate). Koneksi di worker lain baru tertutup
        pada heartbeat berikutnya -- tanpa pub/sub itu batas terbaiknya."""
        live = self.registry.get(agent_id)
        if live is None:
            return False
        await live.sock.close(code, reason)
        return True

    async def shutdown(self) -> None:
        """Graceful shutdown backend: hentikan sweeper, tutup semua koneksi
        lokal dengan 1001, tandai 'disconnected' (agent tidak pamit, jadi
        BUKAN 'offline') supaya agent reconnect begitu backend naik lagi."""
        if self._sweeper is not None:
            self._sweeper.cancel()
            try:
                await self._sweeper
            except asyncio.CancelledError:
                pass
            self._sweeper = None

        for live in self.registry.all():
            await live.sock.close(CloseCode.GOING_AWAY, "server shutting down")
            try:
                await asyncio.wait_for(
                    self.store.release_connection(
                        live.agent_id, live.connection_id,
                        AgentStatus.DISCONNECTED.value, self._clock(),
                    ),
                    timeout=5.0,
                )
            except Exception:  # noqa: BLE001
                logger.warning("release saat shutdown gagal agent=%s", live.agent_id, exc_info=True)
            self.registry.unregister(live.agent_id, live.connection_id)
