"""
Test integrasi Remote Agent (Phase A): REST + WebSocket + SqlAgentStore.

Butuh PostgreSQL aktif dan tabel 'agents' (alembic upgrade head), sama
seperti test_devices.py -- memakai SessionLocal dan TestClient langsung.
Logika koneksi murni sudah dicakup tests/test_agents_core.py tanpa DB;
file ini membuktikan lapisan nyatanya (SQL, adapter Starlette, router).

Catatan: test mengasumsikan TLS tidak diwajibkan. Jika .env Anda
APP_ENV=production, set AGENT_REQUIRE_TLS=false hanya untuk test.
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from starlette.websockets import WebSocketDisconnect

from app.agents.sql_store import SqlAgentStore
from app.agents.tokens import generate_agent_token, hash_agent_token
from app.agents.wiring import agent_manager
from app.database.models import Agent, User
from app.database.session import SessionLocal
from app.main import app
from app.security.hashing import create_access_token

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_agent_rate_limits():
    """agent_manager adalah singleton proses dan TestClient selalu datang dari IP
    yang sama; tanpa reset, kegagalan auth antar-test saling memblokir."""
    agent_manager.auth_failures._events.clear()
    agent_manager._pending_auth.clear()
    yield
    agent_manager.auth_failures._events.clear()
    agent_manager._pending_auth.clear()


def _user(label: str) -> dict[str, str]:
    uid = uuid.uuid4()
    with SessionLocal() as db:
        db.add(User(id=uid, email=f"{label}-{uid.hex[:8]}@example.com",
                    hashed_password="placeholder_hash", is_active=True))
        db.commit()
    return {"Authorization": f"Bearer {create_access_token(subject=str(uid))}"}


def _create_agent(headers, name=None) -> dict:
    res = client.post("/agents", headers=headers, json={"name": name or f"pc-{uuid.uuid4().hex[:6]}"})
    assert res.status_code == 201, res.text
    return res.json()


def _auth(token: str) -> dict:
    return {"type": "auth", "protocol_version": 1, "token": token,
            "os": "Windows 11 x64", "agent_version": "0.1.0"}


def _status(headers, agent_id) -> str:
    return client.get(f"/agents/{agent_id}", headers=headers).json()["status"]


def _wait_status(headers, agent_id, expected, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _status(headers, agent_id) == expected:
            return
        time.sleep(0.05)
    raise AssertionError(f"status tidak menjadi {expected!r}, sekarang {_status(headers, agent_id)!r}")


# ------------------------------------------------------------------ REST

def test_create_agent_returns_token_once_and_never_exposes_hash():
    h = _user("owner")
    created = _create_agent(h)
    assert created["token"].startswith("nova_agt_")
    assert created["status"] == "offline"
    assert created["connect_path"] == f"/ws/agent/{created['id']}"

    for body in (client.get(f"/agents/{created['id']}", headers=h).text,
                 client.get("/agents", headers=h).text):
        assert created["token"] not in body and "token_hash" not in body

    with SessionLocal() as db:
        stored = db.get(Agent, uuid.UUID(created["id"]))
        assert stored.token_hash != created["token"] and len(stored.token_hash) == 64


def test_agent_rest_is_owner_scoped_and_requires_auth():
    a, b = _user("a"), _user("b")
    created = _create_agent(a, "private-pc")
    assert client.get(f"/agents/{created['id']}", headers=b).status_code == 404
    assert client.delete(f"/agents/{created['id']}", headers=b).status_code == 404
    assert client.post(f"/agents/{created['id']}/rotate-token", headers=b).status_code == 404
    assert created["id"] not in client.get("/agents", headers=b).text
    assert client.get("/agents").status_code == 401
    assert client.post("/agents", headers=a, json={"name": "private-pc"}).status_code == 409


# ------------------------------------------------------------------ WebSocket

def test_agent_connects_heartbeats_and_goes_offline_on_bye():
    h = _user("ws")
    agent = _create_agent(h)
    with client.websocket_connect(agent["connect_path"]) as ws:
        ws.send_json(_auth(agent["token"]))
        registered = ws.receive_json()
        assert registered["type"] == "registered" and registered["agent_id"] == agent["id"]
        _wait_status(h, agent["id"], "online")

        ws.send_json({"type": "heartbeat", "seq": 1})
        ack = ws.receive_json()
        assert ack["type"] == "heartbeat_ack" and ack["seq"] == 1

        info = client.get(f"/agents/{agent['id']}", headers=h).json()
        assert info["os"] == "Windows 11 x64" and info["agent_version"] == "0.1.0"
        assert info["last_heartbeat_at"] and info["last_connected_at"]

        ws.send_json({"type": "bye"})
    _wait_status(h, agent["id"], "offline")


def test_wrong_token_and_unknown_agent_are_rejected_identically():
    h = _user("rej")
    agent = _create_agent(h)
    for path, token in ((agent["connect_path"], "nova_agt_" + "A" * 43),
                        (f"/ws/agent/{uuid.uuid4()}", agent["token"])):
        with client.websocket_connect(path) as ws:
            ws.send_json(_auth(token))
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == 4401
    assert _status(h, agent["id"]) == "offline"


def test_invalid_agent_uuid_never_reaches_handler():
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/agent/not-a-uuid"):
            pass


def test_duplicate_connection_replaces_the_old_one():
    h = _user("dup")
    agent = _create_agent(h)
    with client.websocket_connect(agent["connect_path"]) as first:
        first.send_json(_auth(agent["token"]))
        first.receive_json()
        _wait_status(h, agent["id"], "online")
        with client.websocket_connect(agent["connect_path"]) as second:
            second.send_json(_auth(agent["token"]))
            assert second.receive_json()["type"] == "registered"
            with pytest.raises(WebSocketDisconnect) as exc:
                first.receive_json()
            assert exc.value.code == 4009
            time.sleep(0.2)  # beri waktu cleanup koneksi lama
            assert _status(h, agent["id"]) == "online"  # tidak tertimpa cleanup lama
            second.send_json({"type": "bye"})


def test_rotate_token_invalidates_old_token_and_drops_live_connection():
    h = _user("rot")
    agent = _create_agent(h)
    with client.websocket_connect(agent["connect_path"]) as ws:
        ws.send_json(_auth(agent["token"]))
        ws.receive_json()
        rotated = client.post(f"/agents/{agent['id']}/rotate-token", headers=h).json()
        assert rotated["token"] != agent["token"]
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4009

    with client.websocket_connect(agent["connect_path"]) as ws:
        ws.send_json(_auth(agent["token"]))               # token lama
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401
    with client.websocket_connect(agent["connect_path"]) as ws:
        ws.send_json(_auth(rotated["token"]))             # token baru
        assert ws.receive_json()["type"] == "registered"
        ws.send_json({"type": "bye"})


def test_delete_agent_drops_connection_and_removes_record():
    h = _user("del")
    agent = _create_agent(h)
    with client.websocket_connect(agent["connect_path"]) as ws:
        ws.send_json(_auth(agent["token"]))
        ws.receive_json()
        assert client.delete(f"/agents/{agent['id']}", headers=h).status_code == 204
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    assert client.get(f"/agents/{agent['id']}", headers=h).status_code == 404


# ------------------------------------------------------------------ status efektif & sweeper

def test_stale_online_row_is_reported_disconnected_even_before_sweeper_runs():
    h = _user("stale")
    agent = _create_agent(h)
    with SessionLocal() as db:
        row = db.get(Agent, uuid.UUID(agent["id"]))
        row.status = "online"
        row.connection_id = uuid.uuid4()
        row.last_heartbeat_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
    assert _status(h, agent["id"]) == "disconnected"      # worker crash tidak menipu pembaca


def test_sweeper_marks_only_stale_live_rows():
    h = _user("sweep")
    stale, fresh = _create_agent(h), _create_agent(h)
    with SessionLocal() as db:
        for info, age in ((stale, timedelta(hours=1)), (fresh, timedelta(seconds=1))):
            row = db.get(Agent, uuid.UUID(info["id"]))
            row.status, row.connection_id = "online", uuid.uuid4()
            row.last_heartbeat_at = datetime.now(timezone.utc) - age
        db.commit()
    assert asyncio.run(agent_manager.sweep_once()) >= 1
    with SessionLocal() as db:
        assert db.get(Agent, uuid.UUID(stale["id"])).status == "disconnected"
        assert db.get(Agent, uuid.UUID(fresh["id"])).status == "online"


# ------------------------------------------------------------------ kontrak SqlAgentStore

def test_sql_store_conditional_writes_follow_connection_ownership():
    """Kontrak yang sama dengan FakeStore: hanya pemilik connection_id
    yang boleh menulis; pemilik lama tidak bisa menimpa pemilik baru."""
    h = _user("contract")
    agent = _create_agent(h)
    agent_id = uuid.UUID(agent["id"])
    store, now = SqlAgentStore(), datetime.now(timezone.utc)
    conn_a, conn_b = uuid.uuid4(), uuid.uuid4()
    th = hash_agent_token(agent["token"])

    async def scenario():
        assert (await store.claim_connection(agent_id, conn_a, "w1", "Windows 10 x64", "0.1.0", now, th)).claimed
        assert await store.mark_online(agent_id, conn_a, now)
        second = await store.claim_connection(agent_id, conn_b, "w2", "Windows 11 x64", "0.2.0", now, th)
        assert second.claimed and second.replaced_connection_id == conn_a and second.replaced_worker_id == "w1"

        # pemilik lama ditolak di semua jalur tulis
        assert not await store.mark_online(agent_id, conn_a, now)
        assert not await store.record_heartbeat(agent_id, conn_a, now)
        assert not await store.release_connection(agent_id, conn_a, "disconnected", now)

        assert await store.record_heartbeat(agent_id, conn_b, now)
        assert await store.release_connection(agent_id, conn_b, "offline", now)
        assert not await store.release_connection(agent_id, conn_b, "offline", now)  # idempoten
        assert await store.get_auth_record(uuid.uuid4()) is None

    asyncio.run(scenario())
    with SessionLocal() as db:
        row = db.get(Agent, agent_id)
        assert row.status == "offline" and row.connection_id is None
        assert row.os == "Windows 11 x64" and row.agent_version == "0.2.0"


# ------------------------------------------------------------------ keamanan: claim atomik & ownership

def _owner_id(agent: dict) -> uuid.UUID:
    return uuid.UUID(agent["owner_id"])


def test_sql_store_claim_rejects_revoked_hash_and_leaves_row_untouched():
    h = _user("revoked")
    agent = _create_agent(h)
    agent_id = uuid.UUID(agent["id"])
    old_hash = hash_agent_token(agent["token"])
    assert client.post(f"/agents/{agent['id']}/rotate-token", headers=h).status_code == 200

    result = asyncio.run(SqlAgentStore().claim_connection(
        agent_id, uuid.uuid4(), "w1", "Windows 10 x64", "0.1.0", datetime.now(timezone.utc), old_hash,
    ))
    assert not result.claimed and result.reject_reason == "token_revoked"
    with SessionLocal() as db:
        row = db.get(Agent, agent_id)
        assert row.connection_id is None and row.status == "offline" and row.os is None


def test_sql_store_claim_is_atomic_with_a_concurrent_rotation():
    """Deterministik: transaksi 'rotate' memegang lock baris, claim (diverifikasi
    terhadap hash LAMA) dimulai dan harus MENUNGGU lock, lalu menolak setelah
    rotate commit. Tanpa revalidasi dalam transaksi claim, claim ini sukses."""
    h = _user("atomic")
    agent = _create_agent(h)
    agent_id = uuid.UUID(agent["id"])
    old_hash = hash_agent_token(agent["token"])
    outcome: dict = {}

    def claim():
        outcome["result"] = asyncio.run(SqlAgentStore().claim_connection(
            agent_id, uuid.uuid4(), "w1", "Windows 10 x64", "0.1.0",
            datetime.now(timezone.utc), old_hash,
        ))

    with SessionLocal() as rotator:
        rotator.execute(select(Agent).where(Agent.id == agent_id).with_for_update()).first()
        worker = threading.Thread(target=claim)
        worker.start()
        time.sleep(0.5)
        assert worker.is_alive(), "claim harus menunggu lock baris yang dipegang rotate"
        rotator.execute(
            update(Agent).where(Agent.id == agent_id).values(
                token_hash=hash_agent_token(generate_agent_token()),
                connection_id=None, worker_id=None, status="offline",
            )
        )
        rotator.commit()
    worker.join(10)
    assert not worker.is_alive()

    assert not outcome["result"].claimed and outcome["result"].reject_reason == "token_revoked"
    with SessionLocal() as db:
        row = db.get(Agent, agent_id)
        assert row.connection_id is None and row.status == "offline"


def test_sql_store_claim_and_heartbeat_reject_inactive_owner():
    h = _user("inactive")
    agent = _create_agent(h)
    agent_id = uuid.UUID(agent["id"])
    th = hash_agent_token(agent["token"])
    store, now, conn = SqlAgentStore(), datetime.now(timezone.utc), uuid.uuid4()

    async def scenario():
        assert (await store.claim_connection(agent_id, conn, "w1", "Windows 10 x64", "0.1.0", now, th)).claimed
        assert await store.record_heartbeat(agent_id, conn, now)
        with SessionLocal() as db:
            db.get(User, _owner_id(agent)).is_active = False
            db.commit()
        assert not await store.record_heartbeat(agent_id, conn, now)
        denied = await store.claim_connection(agent_id, uuid.uuid4(), "w1", "Windows 10 x64", "0.1.0", now, th)
        assert not denied.claimed and denied.reject_reason == "owner_inactive"

    asyncio.run(scenario())


def test_revoked_token_over_real_websocket_never_registers_and_row_stays_unclaimed():
    h = _user("wsrevoked")
    agent = _create_agent(h)
    assert client.post(f"/agents/{agent['id']}/rotate-token", headers=h).status_code == 200
    with client.websocket_connect(agent["connect_path"]) as ws:
        ws.send_json(_auth(agent["token"]))
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401
    with SessionLocal() as db:
        assert db.get(Agent, uuid.UUID(agent["id"])).connection_id is None


def test_rotate_and_delete_are_owner_scoped_and_do_not_leak_existence():
    a, b = _user("own-a"), _user("own-b")
    created = _create_agent(a)
    missing = uuid.uuid4()
    for method, path in (("get", f"/agents/{created['id']}"), ("get", f"/agents/{missing}"),
                         ("post", f"/agents/{created['id']}/rotate-token"),
                         ("post", f"/agents/{missing}/rotate-token"),
                         ("delete", f"/agents/{created['id']}"), ("delete", f"/agents/{missing}")):
        res = getattr(client, method)(path, headers=b)
        assert res.status_code == 404 and res.json() == {"detail": "Agent not found."}, (method, path)
    # agent milik A tidak berubah oleh percobaan B
    with SessionLocal() as db:
        assert hash_agent_token(created["token"]) == db.get(Agent, uuid.UUID(created["id"])).token_hash


def test_ip_blocked_after_repeated_auth_failures_over_real_websocket():
    h = _user("flood")
    agent = _create_agent(h)
    for _ in range(agent_manager.cfg.auth_fail_limit):
        with client.websocket_connect(agent["connect_path"]) as ws:
            ws.send_json(_auth("nova_agt_" + "A" * 43))
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == 4401
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(agent["connect_path"]):
            pass
    assert exc.value.code == 4429
