"""
Implementasi AgentStore di atas PostgreSQL (SQLAlchemy sync + to_thread,
konsisten dengan pola tools/mikrotik.py: library sync dibungkus
asyncio.to_thread agar event loop WebSocket tidak terblokir).

Setiap operasi tulis = SATU statement UPDATE ... WHERE connection_id = :cid
(atomik di level DB), kecuali claim_connection yang memakai
SELECT ... FOR UPDATE agar bisa melaporkan koneksi yang digantikan.
Tidak membutuhkan Redis atau lock terdistribusi.

Test terhadap PostgreSQL sungguhan: tests/test_agents_api.py (perlu DB aktif).
"""

from __future__ import annotations

import asyncio
import hmac
import uuid
from datetime import datetime

from sqlalchemy import or_, select, update

from app.agents.states import AgentStatus
from app.agents.store import AuthRecord, ClaimResult
from app.database.models import Agent, User
from app.database.session import SessionLocal

_LIVE = (AgentStatus.CONNECTING.value, AgentStatus.ONLINE.value)


class SqlAgentStore:
    # ---- async facade ----
    async def get_auth_record(self, agent_id: uuid.UUID) -> AuthRecord | None:
        return await asyncio.to_thread(self._get_auth_record, agent_id)

    async def claim_connection(
        self, agent_id, connection_id, worker_id, os, agent_version, now, expected_token_hash,
        hostname=None,
    ) -> ClaimResult:
        return await asyncio.to_thread(
            self._claim_connection, agent_id, connection_id, worker_id, os, agent_version, now,
            expected_token_hash, hostname,
        )

    async def mark_online(self, agent_id, connection_id, now) -> bool:
        return await asyncio.to_thread(self._mark_online, agent_id, connection_id, now)

    async def record_heartbeat(self, agent_id, connection_id, now) -> bool:
        return await asyncio.to_thread(self._record_heartbeat, agent_id, connection_id, now)

    async def release_connection(self, agent_id, connection_id, status, now, error=None) -> bool:
        return await asyncio.to_thread(self._release, agent_id, connection_id, status, now, error)

    async def mark_stale(self, cutoff: datetime, now: datetime) -> int:
        return await asyncio.to_thread(self._mark_stale, cutoff, now)

    # ---- sync implementation ----
    @staticmethod
    def _get_auth_record(agent_id: uuid.UUID) -> AuthRecord | None:
        with SessionLocal() as db:
            row = db.execute(
                select(Agent.id, Agent.owner_id, Agent.token_hash, User.is_active)
                .join(User, User.id == Agent.owner_id)
                .where(Agent.id == agent_id)
            ).first()
        if row is None:
            return None
        return AuthRecord(row[0], row[1], row[2], bool(row[3]))

    @staticmethod
    def _claim_connection(
        agent_id, connection_id, worker_id, os, agent_version, now, expected_token_hash,
        hostname=None,
    ) -> ClaimResult:
        # Validasi ulang ATOMIK: baris agent dikunci (FOR UPDATE) lalu token_hash
        # dan status owner dibaca di dalam transaksi yang sama dengan penulisan
        # claim. REST rotate/delete mengambil lock baris yang sama, jadi salah
        # satu pasti terjadi lebih dulu secara utuh:
        #   - rotate commit duluan -> hash berubah -> claim ditolak;
        #   - claim commit duluan  -> rotate meng-NULL-kan connection_id -> koneksi
        #     ini kehilangan kepemilikan di heartbeat/tulis berikutnya.
        with SessionLocal() as db:
            row = db.execute(
                select(Agent, User.is_active)
                .join(User, User.id == Agent.owner_id)
                .where(Agent.id == agent_id)
                .with_for_update(of=Agent)
                .execution_options(populate_existing=True)
            ).first()
            if row is None:
                return ClaimResult(False, reject_reason="not_found")
            agent, owner_active = row
            if not hmac.compare_digest(
                agent.token_hash.encode("ascii", "ignore"),
                expected_token_hash.encode("ascii", "ignore"),
            ):
                return ClaimResult(False, reject_reason="token_revoked")
            if not owner_active:
                return ClaimResult(False, reject_reason="owner_inactive")
            replaced_cid, replaced_wid = (
                (agent.connection_id, agent.worker_id) if agent.status in _LIVE else (None, None)
            )
            agent.status = AgentStatus.CONNECTING.value
            agent.connection_id = connection_id
            agent.worker_id = worker_id[:100]
            agent.os = os
            agent.hostname = hostname[:255] if hostname else None
            agent.agent_version = agent_version
            agent.last_heartbeat_at = now
            agent.last_connected_at = now
            agent.last_error = None
            agent.updated_at = now
            db.commit()
        return ClaimResult(True, replaced_cid, replaced_wid)

    @staticmethod
    def _mark_online(agent_id, connection_id, now) -> bool:
        with SessionLocal() as db:
            result = db.execute(
                update(Agent)
                .where(Agent.id == agent_id, Agent.connection_id == connection_id)
                .values(status=AgentStatus.ONLINE.value, updated_at=now)
            )
            db.commit()
            return result.rowcount == 1

    @staticmethod
    def _record_heartbeat(agent_id, connection_id, now) -> bool:
        # Juga memulihkan 'online' jika sweeper sempat menandai 'disconnected'
        # padahal koneksi ini sebenarnya hidup (self-heal).
        with SessionLocal() as db:
            result = db.execute(
                update(Agent)
                .where(
                    Agent.id == agent_id,
                    Agent.connection_id == connection_id,
                    # Owner yang dinonaktifkan kehilangan koneksi pada heartbeat berikutnya.
                    Agent.owner_id.in_(select(User.id).where(User.is_active.is_(True))),
                )
                .values(
                    status=AgentStatus.ONLINE.value,
                    last_heartbeat_at=now,
                    updated_at=now,
                )
            )
            db.commit()
            return result.rowcount == 1

    @staticmethod
    def _release(agent_id, connection_id, status, now, error) -> bool:
        with SessionLocal() as db:
            result = db.execute(
                update(Agent)
                .where(Agent.id == agent_id, Agent.connection_id == connection_id)
                .values(
                    status=status,
                    connection_id=None,
                    worker_id=None,
                    last_disconnected_at=now,
                    last_error=(error[:500] if error else None),
                    updated_at=now,
                )
            )
            db.commit()
            return result.rowcount == 1

    @staticmethod
    def _mark_stale(cutoff: datetime, now: datetime) -> int:
        with SessionLocal() as db:
            result = db.execute(
                update(Agent)
                .where(
                    Agent.status.in_(_LIVE),
                    or_(Agent.last_heartbeat_at.is_(None), Agent.last_heartbeat_at < cutoff),
                )
                .values(
                    status=AgentStatus.DISCONNECTED.value,
                    last_disconnected_at=now,
                    updated_at=now,
                )
            )
            db.commit()
            return result.rowcount or 0
