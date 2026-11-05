"""
Test inti logika koneksi Remote Agent (Phase A) -- TANPA DB / FastAPI.

Memakai FakeStore + FakeSocket (tests/agents_fakes.py) yang meniru
semantik kondisional store SQL. Sengaja ditulis tanpa fixture pytest
(plain async function) supaya bisa dijalankan pytest-asyncio di proyek
(asyncio_mode=auto) maupun runner stdlib.

Mencakup persyaratan Phase A: validasi UUID, token constant-time, reject
auth invalid, timeout auth, heartbeat timeout, deteksi disconnect,
duplicate connection, disconnect graceful, token tidak bocor ke log,
error tak terduga, TLS, serta skenario multi-worker (kepemilikan koneksi).
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import uuid

from app.agents import tokens
from app.agents.manager import AgentConnectionManager, AgentRuntimeConfig
from app.agents.protocol import CloseCode, parse_agent_id, parse_client_message, ProtocolError
from app.agents.states import AgentStatus, effective_status
from tests.agents_fakes import FakeSocket, FakeStore, auth_frame, until, utc


def make_manager(store=None, **overrides):
    store = store or FakeStore()
    params = dict(
        auth_timeout_seconds=0.3, heartbeat_interval_seconds=0.05,
        heartbeat_timeout_seconds=0.3, heartbeat_min_db_interval_seconds=0.0,
        sweep_interval_seconds=0.05,
    )
    params.update(overrides)
    events: list[dict] = []

    async def audit(**kw):
        events.append(kw)

    manager = AgentConnectionManager(store, AgentRuntimeConfig(**params), audit=audit, worker_id="worker-A")
    manager.events = events
    return manager, store


def start(manager, sock, agent_id) -> asyncio.Task:
    return asyncio.create_task(manager.handle(sock, str(agent_id)))


async def connect(manager, store, token=None, agent=None):
    """Hubungkan agent sampai status online; kembalikan (task, sock, agent_id, token)."""
    agent_id, tok = agent or store.add_agent()
    sock = FakeSocket()
    task = start(manager, sock, agent_id)
    sock.client_send(auth_frame(token or tok))
    await until(lambda: store.row(agent_id)["status"] == "online")
    return task, sock, agent_id, tok


# ---------------------------------------------------------------- happy path

async def test_auth_register_heartbeat_ack_and_graceful_bye():
    manager, store = make_manager()
    task, sock, agent_id, _ = await connect(manager, store)

    registered = sock.sent[0]
    assert registered["type"] == "registered"
    assert registered["agent_id"] == str(agent_id)
    assert registered["heartbeat_timeout_seconds"] == 0.3
    row = store.row(agent_id)
    assert row["os"] == "Windows 11 x64" and row["agent_version"] == "0.1.0"
    assert row["worker_id"] == "worker-A" and row["last_connected_at"] is not None

    sock.client_send({"type": "heartbeat", "seq": 7})
    await until(lambda: len(sock.sent) == 2)
    assert sock.sent[1]["type"] == "heartbeat_ack" and sock.sent[1]["seq"] == 7

    sock.client_send({"type": "bye"})
    await asyncio.wait_for(task, 1)
    assert row["status"] == "offline" and row["connection_id"] is None
    assert sock.closed[0] == CloseCode.NORMAL
    assert len(manager.registry) == 0
    assert [e["action"] for e in manager.events] == ["agent.connected", "agent.disconnected"]


async def test_clean_websocket_close_without_bye_is_offline_abnormal_is_disconnected():
    for code, expected in ((1000, "offline"), (1001, "offline"), (1006, "disconnected")):
        manager, store = make_manager()
        task, sock, agent_id, _ = await connect(manager, store)
        sock.client_close(code)
        await asyncio.wait_for(task, 1)
        assert store.row(agent_id)["status"] == expected, code


# ---------------------------------------------------------------- validasi & auth

async def test_invalid_agent_uuid_rejected_before_accept():
    manager, store = make_manager()
    for bad in ("not-a-uuid", "", "12345678-1234-1234-1234-123456789012",  # bukan v4
                "{" + str(uuid.uuid4()) + "}", str(uuid.uuid4()).replace("-", ""),
                "../../etc/passwd", str(uuid.uuid4()) + "x"):
        sock = FakeSocket()
        await manager.handle(sock, bad)
        assert sock.accepted is False and sock.closed[0] == CloseCode.POLICY, bad
    assert store.calls == []  # DB tidak pernah disentuh
    assert parse_agent_id(str(uuid.uuid4()).upper()) is not None


async def test_wrong_token_unknown_agent_and_inactive_owner_get_identical_rejection():
    manager, store = make_manager()
    good_id, good_token = store.add_agent()
    inactive_id, inactive_token = store.add_agent(owner_active=False)
    cases = [
        (good_id, tokens.generate_agent_token()),       # token salah
        (good_id, "garbage"),                            # format salah
        (uuid.uuid4(), good_token),                      # agent tak dikenal
        (inactive_id, inactive_token),                   # owner nonaktif
    ]
    outcomes = set()
    for agent_id, tok in cases:
        sock = FakeSocket()
        task = start(manager, sock, agent_id)
        sock.client_send(auth_frame(tok))
        await asyncio.wait_for(task, 1)
        outcomes.add(sock.closed)
    assert outcomes == {(CloseCode.AUTH_FAILED, "authentication failed")}
    assert store.row(good_id)["status"] == "offline"          # tidak ada side effect
    assert store.row(good_id)["connection_id"] is None
    assert "claim_connection" not in store.calls


async def test_token_comparison_uses_constant_time_compare_even_for_unknown_agent():
    real = hmac.compare_digest
    seen = []

    def spy(a, b):
        seen.append((a, b))
        return real(a, b)

    tokens.hmac.compare_digest = spy
    try:
        manager, store = make_manager()
        sock = FakeSocket()
        task = start(manager, sock, uuid.uuid4())      # agent tidak ada
        sock.client_send(auth_frame(tokens.generate_agent_token()))
        await asyncio.wait_for(task, 1)
    finally:
        tokens.hmac.compare_digest = real
    assert len(seen) == 1                               # jalur dummy tetap membandingkan


async def test_auth_timeout_closes_4408():
    manager, store = make_manager(auth_timeout_seconds=0.1)
    agent_id, _ = store.add_agent()
    sock = FakeSocket()
    await asyncio.wait_for(manager.handle(sock, str(agent_id)), 1)
    assert sock.accepted and sock.closed[0] == CloseCode.TIMEOUT
    assert store.row(agent_id)["status"] == "offline"


async def test_malformed_oversized_binary_and_wrong_first_message():
    manager, store = make_manager(max_message_bytes=200)
    agent_id, token = store.add_agent()
    from app.agents.protocol import UnsupportedFrame
    cases = [
        ("{not json", CloseCode.PROTOCOL),
        ('{"type":"heartbeat"}', CloseCode.PROTOCOL),                 # bukan auth
        (__import__("json").dumps(auth_frame(token, protocol_version=99)), CloseCode.PROTOCOL),
        (__import__("json").dumps(auth_frame(token, os="x" * 500)), CloseCode.TOO_BIG),
        (UnsupportedFrame(), CloseCode.UNSUPPORTED),
    ]
    for payload, expected in cases:
        sock = FakeSocket()
        task = start(manager, sock, agent_id)
        sock.client_send_raw(payload)
        await asyncio.wait_for(task, 1)
        assert sock.closed[0] == expected, payload
    assert store.row(agent_id)["status"] == "offline"


async def test_tls_required_rejects_insecure_connection_before_accept():
    manager, store = make_manager(require_tls=True)
    agent_id, token = store.add_agent()
    insecure = FakeSocket(secure=False)
    await manager.handle(insecure, str(agent_id))
    assert insecure.accepted is False and insecure.closed[0] == CloseCode.POLICY

    secure = FakeSocket(secure=True)
    task = start(manager, secure, agent_id)
    secure.client_send(auth_frame(token))
    await until(lambda: store.row(agent_id)["status"] == "online")
    secure.client_send({"type": "bye"})
    await asyncio.wait_for(task, 1)


# ---------------------------------------------------------------- heartbeat & deteksi putus

async def test_heartbeat_timeout_marks_disconnected():
    manager, store = make_manager(heartbeat_timeout_seconds=0.15, heartbeat_interval_seconds=0.05)
    task, sock, agent_id, _ = await connect(manager, store)
    await asyncio.wait_for(task, 1)           # tidak ada heartbeat -> server menutup
    assert sock.closed[0] == CloseCode.TIMEOUT
    assert store.row(agent_id)["status"] == "disconnected"
    assert store.row(agent_id)["last_disconnected_at"] is not None


async def test_heartbeats_keep_connection_alive_past_timeout_window():
    manager, store = make_manager(heartbeat_timeout_seconds=0.2, heartbeat_interval_seconds=0.05)
    task, sock, agent_id, _ = await connect(manager, store)
    for _ in range(8):                        # total 0.4s > timeout 0.2s
        sock.client_send({"type": "heartbeat"})
        await asyncio.sleep(0.05)
    assert not task.done() and store.row(agent_id)["status"] == "online"
    sock.client_send({"type": "bye"})
    await asyncio.wait_for(task, 1)


async def test_heartbeat_db_writes_are_throttled_but_still_acked():
    manager, store = make_manager(heartbeat_min_db_interval_seconds=60.0,
                                  heartbeat_timeout_seconds=1.0)
    task, sock, agent_id, _ = await connect(manager, store)
    for i in range(5):
        sock.client_send({"type": "heartbeat", "seq": i})
    await until(lambda: len(sock.sent) == 6)
    assert store.calls.count("record_heartbeat") == 0
    sock.client_send({"type": "bye"})
    await asyncio.wait_for(task, 1)


async def test_invalid_heartbeat_seq_and_unknown_type_are_protocol_errors():
    for bad in ('{"type":"heartbeat","seq":-1}', '{"type":"heartbeat","seq":true}',
                '{"type":"heartbeat","seq":"1"}', '{"type":"auth"}', '{"type":"x"}'):
        try:
            parse_client_message(bad, 1000)
        except ProtocolError:
            continue
        raise AssertionError(f"seharusnya ditolak: {bad}")


# ---------------------------------------------------------------- duplicate & multi-worker

async def test_duplicate_connection_same_worker_new_wins_old_closed_4009():
    manager, store = make_manager(heartbeat_timeout_seconds=1.0)
    agent = store.add_agent()
    task1, sock1, agent_id, tok = await connect(manager, store, agent=agent)
    first_conn = store.row(agent_id)["connection_id"]

    sock2 = FakeSocket()
    task2 = start(manager, sock2, agent_id)
    sock2.client_send(auth_frame(tok))
    await until(lambda: sock1.closed is not None)
    await asyncio.wait_for(task1, 1)          # handler lama sudah selesai & cleanup

    assert sock1.closed[0] == CloseCode.REPLACED
    await until(lambda: store.row(agent_id)["status"] == "online"
                and store.row(agent_id)["connection_id"] != first_conn)
    # cleanup koneksi lama TIDAK boleh menimpa state koneksi baru:
    assert store.row(agent_id)["connection_id"] is not None
    assert manager.registry.get(agent_id).sock is sock2

    sock2.client_send({"type": "bye"})
    await asyncio.wait_for(task2, 1)


async def test_cross_worker_takeover_old_worker_closes_itself_and_never_clobbers():
    """Worker B mengambil alih agent (claim langsung ke store); koneksi di
    worker A harus menyadari lewat heartbeat, menutup diri 4009, dan TIDAK
    menurunkan status ke offline/disconnected."""
    manager_a, store = make_manager(heartbeat_timeout_seconds=1.0)
    task, sock, agent_id, _ = await connect(manager_a, store)

    new_conn = uuid.uuid4()
    await store.claim_connection(
        agent_id, new_conn, "worker-B", "Windows 10 x64", "0.1.0", utc(),
        store.row(agent_id)["token_hash"],
    )
    await store.mark_online(agent_id, new_conn, utc())

    sock.client_send({"type": "heartbeat"})
    await asyncio.wait_for(task, 1)
    assert sock.closed[0] == CloseCode.REPLACED
    row = store.row(agent_id)
    assert row["status"] == "online" and row["connection_id"] == new_conn
    assert row["worker_id"] == "worker-B"
    assert "release_connection" not in store.calls   # worker A tidak menulis apa pun


async def test_deleted_agent_connection_closes_on_next_heartbeat():
    manager, store = make_manager(heartbeat_timeout_seconds=1.0)
    task, sock, agent_id, _ = await connect(manager, store)
    del store.agents[agent_id]
    sock.client_send({"type": "heartbeat"})
    await asyncio.wait_for(task, 1)
    assert sock.closed[0] == CloseCode.REPLACED


async def test_simultaneous_connections_converge_on_exactly_one_owner():
    manager, store = make_manager(heartbeat_timeout_seconds=1.0)
    agent_id, tok = store.add_agent()
    socks = [FakeSocket() for _ in range(5)]
    tasks = [start(manager, s, agent_id) for s in socks]
    for s in socks:
        s.client_send(auth_frame(tok))
    await asyncio.sleep(0.15)
    alive = [s for s in socks if s.closed is None]
    assert len(alive) == 1                       # tepat satu pemenang
    assert store.row(agent_id)["status"] == "online"
    assert manager.registry.get(agent_id).sock is alive[0]
    alive[0].client_send({"type": "bye"})
    await asyncio.wait_for(asyncio.gather(*tasks), 1)


# ---------------------------------------------------------------- sweeper & status efektif

async def test_sweeper_marks_stale_live_agents_and_connected_agent_self_heals():
    manager, store = make_manager(heartbeat_timeout_seconds=0.3, heartbeat_interval_seconds=0.05)
    # worker crash: baris 'online' dengan heartbeat basi, tanpa koneksi hidup
    crashed_id, _ = store.add_agent()
    store.row(crashed_id).update(status="online", connection_id=uuid.uuid4(),
                                 last_heartbeat_at=utc(-100))
    # agent sehat dengan heartbeat segar
    fresh_id, _ = store.add_agent()
    store.row(fresh_id).update(status="online", connection_id=uuid.uuid4(),
                               last_heartbeat_at=utc())
    assert await manager.sweep_once() == 1
    assert store.row(crashed_id)["status"] == "disconnected"
    assert store.row(fresh_id)["status"] == "online"
    assert await manager.sweep_once() == 0       # idempoten

    # koneksi hidup yang sempat tersapu (mis. DB lambat) pulih lewat heartbeat
    task, sock, agent_id, _ = await connect(manager, store)
    store.row(agent_id)["status"] = "disconnected"
    sock.client_send({"type": "heartbeat"})
    await until(lambda: store.row(agent_id)["status"] == "online")
    sock.client_send({"type": "bye"})
    await asyncio.wait_for(task, 1)


async def test_sweeper_loop_runs_in_background_and_stops_on_shutdown():
    manager, store = make_manager()
    agent_id, _ = store.add_agent()
    store.row(agent_id).update(status="connecting", connection_id=uuid.uuid4(),
                               last_heartbeat_at=utc(-100))
    manager.start()
    await until(lambda: store.row(agent_id)["status"] == "disconnected")
    await manager.shutdown()
    assert manager._sweeper is None


def test_effective_status_derives_from_heartbeat_freshness():
    now = utc()
    assert effective_status("online", utc(-5), now, 90) is AgentStatus.ONLINE
    assert effective_status("online", utc(-500), now, 90) is AgentStatus.DISCONNECTED
    assert effective_status("connecting", None, now, 90) is AgentStatus.DISCONNECTED
    assert effective_status("offline", None, now, 90) is AgentStatus.OFFLINE
    assert effective_status("error", utc(-500), now, 90) is AgentStatus.ERROR
    assert effective_status("disconnected", utc(-500), now, 90) is AgentStatus.DISCONNECTED
    assert effective_status("weird", utc(), now, 90) is AgentStatus.ERROR
    naive = utc(-5).replace(tzinfo=None)            # SQLite mengembalikan naive
    assert effective_status("online", naive, now, 90) is AgentStatus.ONLINE


# ---------------------------------------------------------------- error & shutdown

async def test_unexpected_store_error_sets_error_status_without_leaking_or_raising():
    manager, store = make_manager(heartbeat_timeout_seconds=1.0)
    task, sock, agent_id, token = await connect(manager, store)
    store.fail_on.add("record_heartbeat")
    sock.client_send({"type": "heartbeat"})
    await asyncio.wait_for(task, 1)                  # handler tidak melempar
    row = store.row(agent_id)
    assert sock.closed[0] == CloseCode.INTERNAL
    assert row["status"] == "error" and "RuntimeError" in row["last_error"]
    assert token not in row["last_error"]
    assert len(manager.registry) == 0


async def test_store_down_during_auth_closes_1011_and_does_not_raise():
    manager, store = make_manager()
    agent_id, token = store.add_agent()
    store.fail_on.add("get_auth_record")
    sock = FakeSocket()
    task = start(manager, sock, agent_id)
    sock.client_send(auth_frame(token))
    await asyncio.wait_for(task, 1)
    assert sock.closed[0] == CloseCode.INTERNAL


async def test_backend_shutdown_closes_connections_1001_and_marks_disconnected():
    manager, store = make_manager(heartbeat_timeout_seconds=1.0)
    task, sock, agent_id, _ = await connect(manager, store)
    await manager.shutdown()
    await asyncio.wait_for(task, 1)
    assert sock.closed[0] == CloseCode.GOING_AWAY
    # server yang pergi bukan agent yang pamit -> 'disconnected', bukan 'offline'
    assert store.row(agent_id)["status"] == "disconnected"
    assert len(manager.registry) == 0


async def test_disconnect_local_closes_registered_connection():
    manager, store = make_manager(heartbeat_timeout_seconds=1.0)
    task, sock, agent_id, _ = await connect(manager, store)
    assert await manager.disconnect_local(agent_id) is True
    assert await manager.disconnect_local(uuid.uuid4()) is False
    await asyncio.wait_for(task, 1)
    assert sock.closed[0] == CloseCode.REPLACED


# ---------------------------------------------------------------- tidak bocor ke log

async def test_token_never_appears_in_logs_or_repr():
    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = Capture(level=logging.DEBUG)
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        manager, store = make_manager(heartbeat_timeout_seconds=1.0)
        agent_id, good = store.add_agent()
        bad = tokens.generate_agent_token()
        for tok in (bad, good):                      # satu gagal, satu sukses
            sock = FakeSocket()
            task = start(manager, sock, agent_id)
            sock.client_send(auth_frame(tok))
            if tok == good:
                await until(lambda: store.row(agent_id)["status"] == "online")
                store.fail_on.add("record_heartbeat")  # paksa jalur logger.exception
                sock.client_send({"type": "heartbeat"})
            await asyncio.wait_for(task, 1)
        from app.agents.protocol import parse_auth
        auth = parse_auth(__import__("json").dumps(auth_frame(good)), 4096)
        rendered = "\n".join(r.getMessage() for r in records) + repr(auth)
        rendered += "\n".join(
            logging.Formatter().formatException(r.exc_info) for r in records if r.exc_info
        )
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)
    assert records, "harus ada log untuk diperiksa"
    for secret in (bad, good, tokens.hash_agent_token(good)):
        assert secret not in rendered


# ---------------------------------------------------------------- token utils

def test_token_generation_hashing_and_verification():
    a, b = tokens.generate_agent_token(), tokens.generate_agent_token()
    assert a != b and a.startswith("nova_agt_") and len(a) == 52
    assert tokens.is_well_formed_token(a)
    stored = tokens.hash_agent_token(a)
    assert len(stored) == 64 and a not in stored
    assert tokens.verify_agent_token(a, stored) is True
    assert tokens.verify_agent_token(b, stored) is False
    for junk in (None, 123, "", "nova_agt_short", a + "x", "x" * 10_000, b"bytes"):
        assert tokens.verify_agent_token(junk, stored) is False


def test_config_rejects_inconsistent_timeouts():
    for kwargs in (dict(heartbeat_interval_seconds=30, heartbeat_timeout_seconds=30),
                   dict(heartbeat_interval_seconds=30, heartbeat_timeout_seconds=10)):
        try:
            AgentRuntimeConfig(**kwargs)
        except ValueError:
            continue
        raise AssertionError("konfigurasi timeout tidak konsisten harus ditolak")
