"""
Registry koneksi LOKAL (per proses/worker).

Hanya menjawab "socket mana yang dipegang proses ini" -- dipakai untuk
menutup koneksi lama saat duplicate dan untuk graceful shutdown.
BUKAN sumber kebenaran status agent (itu DB + effective_status).
Tidak ada lock: semua mutasi sinkron di satu event loop.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator


@dataclass
class LiveConnection:
    agent_id: uuid.UUID
    connection_id: uuid.UUID
    owner_id: uuid.UUID
    sock: Any
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class LocalConnectionRegistry:
    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, LiveConnection] = {}

    def register(self, conn: LiveConnection) -> LiveConnection | None:
        """Pasang koneksi; kembalikan koneksi lokal sebelumnya (jika ada)."""
        previous = self._connections.get(conn.agent_id)
        self._connections[conn.agent_id] = conn
        return previous

    def unregister(self, agent_id: uuid.UUID, connection_id: uuid.UUID) -> bool:
        """Lepas HANYA jika entri masih milik connection_id tsb."""
        current = self._connections.get(agent_id)
        if current is not None and current.connection_id == connection_id:
            del self._connections[agent_id]
            return True
        return False

    def get(self, agent_id: uuid.UUID) -> LiveConnection | None:
        return self._connections.get(agent_id)

    def all(self) -> list[LiveConnection]:
        return list(self._connections.values())

    def __iter__(self) -> Iterator[LiveConnection]:
        return iter(self.all())

    def __len__(self) -> int:
        return len(self._connections)
