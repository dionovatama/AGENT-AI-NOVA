"""
Test keamanan Remote Agent (Phase A) -- tanpa DB / FastAPI.

Mencakup:
  * race rotasi token: token yang dicabut TIDAK BOLEH membuka koneksi walau
    sudah lolos verifikasi sebelum rotasi (revalidasi atomik saat claim);
  * koneksi yang sudah ada kehilangan kepemilikan setelah rotate / owner nonaktif;
  * rate limiting autentikasi (per IP) dan pesan (per koneksi);
  * SlidingWindowLimiter.

Plain async function (tanpa fixture), sama seperti test_agents_core.py.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from app.agents.manager import AgentConnectionManager, AgentRuntimeConfig
from app.agents.protocol import CloseCode
from app.agents.ratelimit import SlidingWindowLimiter
from tests.agents_fakes import FakeSocket, FakeStore, auth_frame, until
from tests.test_agents_core import connect, make_manager, start


class Clock:
    """Jam monotonik palsu untuk limiter."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


# ---------------------------------------------------------------- rotation race

async def test_token_rotated_between_verification_and_claim_never_connects():
    manager, store = make_manager()
    agent_id, old_token = store.add_agent()
    # Rotasi ter-commit tepat setelah token terverifikasi, sebelum claim.
    store.hooks["claim_connection"] = lambda: store.rotate_token(agent_id)

    sock = FakeSocket()
    task = start(manager, sock, agent_id)
    sock.client_send(auth_frame(old_token))
    await asyncio.wait_for(task, 2)

    assert sock.closed is not None and sock.closed[0] == CloseCode.AUTH_FAILED
    assert not any(m.get("type") == "registered" for m in sock.sent)
    row = store.row(agent_id)
    assert row["connection_id"] is None and row["status"] == "offline"
    assert len(manager.registry) == 0
    assert "mark_online" not in store.calls
    assert not [e for e in manager.events if e["action"] == "agent.connected"]


async def test_rotated_token_cannot_connect_but_new_token_can():
    manager, store = make_manager()
    agent_id, old_token = store.add_agent()
    new_token = store.rotate_token(agent_id)

    stale = FakeSocket()
    t1 = start(manager, stale, agent_id)
    stale.client_send(auth_frame(old_token))
    await asyncio.wait_for(t1, 2)
    assert stale.closed[0] == CloseCode.AUTH_FAILED

    task, sock, _, _ = await connect(manager, store, token=new_token, agent=(agent_id, new_token))
    assert store.row(agent_id)["status"] == "online"
    sock.client_close(1000)
    await asyncio.wait_for(task, 2)


async def test_owner_deactivated_between_verification_and_claim_never_connects():
    manager, store = make_manager()
    agent_id, token = store.add_agent()

    def deactivate():
        store.row(agent_id)["owner_active"] = False

    store.hooks["claim_connection"] = deactivate
    sock = FakeSocket()
    task = start(manager, sock, agent_id)
    sock.client_send(auth_frame(token))
    await asyncio.wait_for(task, 2)

    assert sock.closed[0] == CloseCode.AUTH_FAILED
    assert store.row(agent_id)["connection_id"] is None
    assert len(manager.registry) == 0


async def test_agent_deleted_between_verification_and_claim_never_connects():
    manager, store = make_manager()
    agent_id, token = store.add_agent()
    store.hooks["claim_connection"] = lambda: store.agents.pop(agent_id)

    sock = FakeSocket()
    task = start(manager, sock, agent_id)
    sock.client_send(auth_frame(token))
    await asyncio.wait_for(task, 2)
    assert sock.closed[0] == CloseCode.AUTH_FAILED
    assert len(manager.registry) == 0


async def test_rejection_is_identical_for_revoked_token_and_wrong_token():
    manager, store = make_manager()
    agent_id, token = store.add_agent()
    store.hooks["claim_connection"] = lambda: store.rotate_token(agent_id)
    revoked = FakeSocket()
    t1 = start(manager, revoked, agent_id)
    revoked.client_send(auth_frame(token))
    await asyncio.wait_for(t1, 2)

    other_id, _ = store.add_agent()
    wrong = FakeSocket()
    t2 = start(manager, wrong, other_id)
    wrong.client_send(auth_frame("nova_agt_" + "A" * 43))
    await asyncio.wait_for(t2, 2)

    assert revoked.closed == wrong.closed == (CloseCode.AUTH_FAILED, "authentication failed")


async def test_live_connection_is_dropped_after_token_rotation():
    manager, store = make_manager()
    task, sock, agent_id, _ = await connect(manager, store)
    store.rotate_token(agent_id)  # REST rotate: kepemilikan koneksi direset

    sock.client_send({"type": "heartbeat"})
    await asyncio.wait_for(task, 2)
    assert sock.closed[0] == CloseCode.REPLACED
    assert store.row(agent_id)["connection_id"] is None


async def test_live_connection_is_dropped_when_owner_deactivated():
    manager, store = make_manager()
    task, sock, agent_id, _ = await connect(manager, store)
    store.row(agent_id)["owner_active"] = False

    sock.client_send({"type": "heartbeat"})
    await asyncio.wait_for(task, 2)
    assert sock.closed[0] == CloseCode.REPLACED


async def test_claim_receives_the_hash_that_was_verified():
    """Manager harus meneruskan hash yang diverifikasi (bukan membaca ulang)."""
    manager, store = make_manager()
    agent_id, token = store.add_agent()
    seen: list[str] = []
    original = store.claim_connection

    async def spy(*args, **kwargs):
        seen.append(args[-1] if args else kwargs["expected_token_hash"])
        return await original(*args, **kwargs)

    store.claim_connection = spy  # type: ignore[method-assign]
    task, sock, _, _ = await connect(manager, store, agent=(agent_id, token))
    assert seen == [store.row(agent_id)["token_hash"]]
    sock.client_close(1000)
    await asyncio.wait_for(task, 2)


# ---------------------------------------------------------------- rate limiting

def _manager_with_clock(**overrides):
    clock = Clock()
    store = FakeStore()
    params = dict(
        auth_timeout_seconds=0.3, heartbeat_interval_seconds=0.05,
        heartbeat_timeout_seconds=0.3, heartbeat_min_db_interval_seconds=0.0,
        sweep_interval_seconds=0.05, auth_fail_limit=3, auth_fail_window_seconds=60.0,
    )
    params.update(overrides)
    manager = AgentConnectionManager(
        store, AgentRuntimeConfig(**params), worker_id="worker-A", mono_clock=clock
    )
    return manager, store, clock


async def _failed_attempt(manager, agent_id, ip="203.0.113.9"):
    sock = FakeSocket(ip=ip)
    task = start(manager, sock, agent_id)
    sock.client_send(auth_frame("nova_agt_" + "B" * 43))
    await asyncio.wait_for(task, 2)
    return sock


async def test_repeated_auth_failures_block_ip_before_accept_and_db_lookup():
    manager, store, clock = _manager_with_clock()
    agent_id, token = store.add_agent()
    for _ in range(3):
        s = await _failed_attempt(manager, agent_id)
        assert s.closed[0] == CloseCode.AUTH_FAILED

    lookups_before = store.calls.count("get_auth_record")
    blocked = FakeSocket(ip="203.0.113.9")
    await asyncio.wait_for(start(manager, blocked, agent_id), 2)
    assert blocked.closed == (CloseCode.RATE_LIMITED, "rate limited")
    assert blocked.accepted is False
    assert store.calls.count("get_auth_record") == lookups_before  # DB tidak disentuh

    # Bahkan token yang BENAR dari IP terblokir ditolak.
    good = FakeSocket(ip="203.0.113.9")
    t = start(manager, good, agent_id)
    good.client_send(auth_frame(token))
    await asyncio.wait_for(t, 2)
    assert good.closed[0] == CloseCode.RATE_LIMITED and good.accepted is False


async def test_block_is_per_ip_and_expires_with_the_window():
    manager, store, clock = _manager_with_clock()
    agent_id, token = store.add_agent()
    for _ in range(3):
        await _failed_attempt(manager, agent_id)

    other_ip = FakeSocket(ip="198.51.100.4")
    t = start(manager, other_ip, agent_id)
    other_ip.client_send(auth_frame(token))
    await until(lambda: store.row(agent_id)["status"] == "online")
    other_ip.client_close(1000)
    await asyncio.wait_for(t, 2)

    clock.advance(61)  # jendela berlalu
    again = FakeSocket(ip="203.0.113.9")
    t = start(manager, again, agent_id)
    again.client_send(auth_frame(token))
    await until(lambda: store.row(agent_id)["status"] == "online")
    assert again.closed is None
    again.client_close(1000)
    await asyncio.wait_for(t, 2)


async def test_successful_auth_does_not_count_toward_failure_limit():
    manager, store, clock = _manager_with_clock()
    agent_id, token = store.add_agent()
    for _ in range(6):  # > limit, semuanya sukses
        sock = FakeSocket(ip="203.0.113.9")
        t = start(manager, sock, agent_id)
        sock.client_send(auth_frame(token))
        await until(lambda: store.row(agent_id)["status"] == "online")
        sock.client_close(1000)
        await asyncio.wait_for(t, 2)
    assert manager.auth_failures.count("203.0.113.9") == 0


async def test_auth_timeout_and_malformed_frames_count_as_failures():
    manager, store, clock = _manager_with_clock(auth_fail_limit=2)
    agent_id, _ = store.add_agent()

    silent = FakeSocket(ip="203.0.113.9")
    await asyncio.wait_for(start(manager, silent, agent_id), 2)
    assert silent.closed[0] == CloseCode.TIMEOUT

    junk = FakeSocket(ip="203.0.113.9")
    t = start(manager, junk, agent_id)
    junk.client_send_raw("not json")
    await asyncio.wait_for(t, 2)
    assert junk.closed[0] == CloseCode.PROTOCOL

    blocked = FakeSocket(ip="203.0.113.9")
    await asyncio.wait_for(start(manager, blocked, agent_id), 2)
    assert blocked.closed[0] == CloseCode.RATE_LIMITED


async def test_pending_unauthenticated_connections_per_ip_are_capped():
    manager, store, clock = _manager_with_clock(
        max_pending_auth_per_ip=2, auth_timeout_seconds=5.0
    )
    agent_id, token = store.add_agent()
    held = [FakeSocket(ip="203.0.113.9") for _ in range(2)]
    tasks = [start(manager, s, agent_id) for s in held]  # menggantung menunggu auth
    await until(lambda: all(s.accepted for s in held))

    third = FakeSocket(ip="203.0.113.9")
    await asyncio.wait_for(start(manager, third, agent_id), 2)
    assert third.closed[0] == CloseCode.RATE_LIMITED and third.accepted is False

    # IP lain tidak terpengaruh.
    other = FakeSocket(ip="198.51.100.4")
    t = start(manager, other, agent_id)
    other.client_send(auth_frame(token))
    await until(lambda: store.row(agent_id)["status"] == "online")
    other.client_close(1000)
    await asyncio.wait_for(t, 2)

    # Slot dilepas setelah koneksi pending selesai.
    for s in held:
        s.client_close(1000)
    await asyncio.gather(*tasks)
    assert manager._pending_auth == {}


async def test_message_flood_closes_connection_with_rate_limited_and_marks_disconnected():
    manager, store, clock = _manager_with_clock(
        max_messages_per_window=5, message_window_seconds=10.0, heartbeat_timeout_seconds=5.0
    )
    agent_id, token = store.add_agent()
    sock = FakeSocket()
    task = start(manager, sock, agent_id)
    sock.client_send(auth_frame(token))
    await until(lambda: store.row(agent_id)["status"] == "online")

    for _ in range(6):
        sock.client_send({"type": "heartbeat"})
    await asyncio.wait_for(task, 2)

    assert sock.closed[0] == CloseCode.RATE_LIMITED
    assert store.row(agent_id)["status"] == "disconnected"
    assert store.row(agent_id)["connection_id"] is None
    acks = [m for m in sock.sent if m["type"] == "heartbeat_ack"]
    assert len(acks) <= 5


async def test_normal_heartbeat_cadence_is_not_rate_limited():
    manager, store, clock = _manager_with_clock(
        max_messages_per_window=5, message_window_seconds=10.0, heartbeat_timeout_seconds=5.0
    )
    agent_id, token = store.add_agent()
    sock = FakeSocket()
    task = start(manager, sock, agent_id)
    sock.client_send(auth_frame(token))
    await until(lambda: store.row(agent_id)["status"] == "online")

    for _ in range(12):  # 1 pesan per jendela -> selalu di bawah batas
        sock.client_send({"type": "heartbeat"})
        await until(lambda n=len(sock.sent): len(sock.sent) > n)
        clock.advance(11)
    assert sock.closed is None
    sock.client_close(1000)
    await asyncio.wait_for(task, 2)


async def test_rate_limit_logs_never_contain_the_token():
    manager, store, clock = _manager_with_clock(auth_fail_limit=1)
    agent_id, _ = store.add_agent()
    secret = "nova_agt_" + "Z" * 43

    class Collect(logging.Handler):
        def __init__(self) -> None:
            super().__init__(logging.DEBUG)
            self.lines: list[str] = []

        def emit(self, record: logging.LogRecord) -> None:
            self.lines.append(record.getMessage())

    handler = Collect()
    log = logging.getLogger("nova.agents")
    log.addHandler(handler)
    old_level = log.level
    log.setLevel(logging.DEBUG)
    try:
        sock = FakeSocket(ip="203.0.113.9")
        t = start(manager, sock, agent_id)
        sock.client_send(auth_frame(secret))
        await asyncio.wait_for(t, 2)
        blocked = FakeSocket(ip="203.0.113.9")
        await asyncio.wait_for(start(manager, blocked, agent_id), 2)
    finally:
        log.removeHandler(handler)
        log.setLevel(old_level)
    assert handler.lines, "expected log output to be captured"
    assert secret not in "\n".join(handler.lines)


# ---------------------------------------------------------------- limiter unit

def test_sliding_window_limiter_basics():
    clock = Clock()
    lim = SlidingWindowLimiter(3, 10.0, clock=clock)
    assert [lim.hit("a") for _ in range(4)] == [True, True, True, False]
    assert lim.is_limited("a") and not lim.is_limited("b")
    clock.advance(10.1)
    assert lim.count("a") == 0 and not lim.is_limited("a")
    assert lim.hit("a") is True


def test_sliding_window_limiter_is_bounded_in_memory():
    clock = Clock()
    lim = SlidingWindowLimiter(1, 10.0, clock=clock, max_keys=3)
    for k in ("a", "b", "c"):
        assert lim.hit(k) is True
    assert lim.hit("d") is False and len(lim) == 3  # tabel penuh -> tidak tumbuh
    clock.advance(11)
    assert lim.hit("d") is True  # entri basi dipangkas
    assert len(lim) == 1


def test_sliding_window_limiter_prune_and_validation():
    clock = Clock()
    lim = SlidingWindowLimiter(2, 5.0, clock=clock)
    lim.hit("x"); lim.hit("y")
    clock.advance(6)
    assert lim.prune() == 2 and len(lim) == 0
    with pytest.raises(ValueError):
        SlidingWindowLimiter(0, 5.0)


def test_runtime_config_rejects_nonpositive_rate_limits():
    with pytest.raises(ValueError):
        AgentRuntimeConfig(auth_fail_limit=0)
    with pytest.raises(ValueError):
        AgentRuntimeConfig(max_messages_per_window=0)
