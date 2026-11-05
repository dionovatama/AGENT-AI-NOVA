"""
Kontrak penyimpanan state Agent.

Semua operasi tulis bersifat KONDISIONAL pada connection_id: hanya
pemilik koneksi saat ini yang boleh mengubah baris. Inilah yang membuat
koneksi lama (yang digantikan, atau milik worker lain) tidak bisa
menimpa state koneksi baru -- tanpa lock terdistribusi/Redis.

Implementasi produksi: app/agents/sql_store.py (PostgreSQL).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class AuthRecord:
    agent_id: uuid.UUID
    owner_id: uuid.UUID
    token_hash: str
    owner_active: bool


@dataclass(frozen=True)
class ClaimResult:
    claimed: bool
    replaced_connection_id: uuid.UUID | None = None
    replaced_worker_id: str | None = None
    # Hanya untuk log server ("not_found" | "token_revoked" | "owner_inactive");
    # TIDAK pernah dikirim ke peer.
    reject_reason: str | None = None


class AgentStore(Protocol):
    async def get_auth_record(self, agent_id: uuid.UUID) -> AuthRecord | None: ...

    async def claim_connection(
        self,
        agent_id: uuid.UUID,
        connection_id: uuid.UUID,
        worker_id: str,
        os: str,
        agent_version: str,
        now: datetime,
        expected_token_hash: str,
    ) -> ClaimResult:
        """Ambil alih kepemilikan koneksi (last-writer-wins): status
        'connecting', connection_id/worker_id baru, heartbeat = now.

        WAJIB atomik terhadap rotate/delete/nonaktif-owner: di dalam SATU
        transaksi dan dengan baris agent terkunci, implementasi harus
        memastikan (a) agent masih ada, (b) token_hash saat ini sama dengan
        `expected_token_hash` (hash yang barusan diverifikasi manager), dan
        (c) owner masih aktif. Jika salah satu gagal -> ClaimResult(False,
        reject_reason=...) tanpa mengubah baris. Tanpa ini, token yang
        di-rotate di antara verifikasi dan claim tetap bisa membuka koneksi."""

    async def mark_online(
        self, agent_id: uuid.UUID, connection_id: uuid.UUID, now: datetime
    ) -> bool:
        """False jika connection_id sudah bukan milik pemanggil."""

    async def record_heartbeat(
        self, agent_id: uuid.UUID, connection_id: uuid.UUID, now: datetime
    ) -> bool:
        """Perbarui last_heartbeat_at. False = bukan pemilik lagi
        (digantikan, token di-rotate, agent dihapus, atau owner dinonaktifkan)."""

    async def release_connection(
        self,
        agent_id: uuid.UUID,
        connection_id: uuid.UUID,
        status: str,
        now: datetime,
        error: str | None = None,
    ) -> bool:
        """Lepas kepemilikan dengan status akhir. No-op (False) jika
        pemanggil bukan pemilik saat ini."""

    async def mark_stale(self, cutoff: datetime, now: datetime) -> int:
        """Sapu baris online/connecting dengan heartbeat < cutoff menjadi
        'disconnected'. Idempoten; aman dijalankan semua worker."""
