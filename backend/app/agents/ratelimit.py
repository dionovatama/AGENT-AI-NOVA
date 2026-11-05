"""
Rate limiter sliding-window in-memory untuk jalur Remote Agent (Phase A).

Dipakai untuk dua hal (lihat manager.py):
  * kegagalan autentikasi per alamat IP (brute force / pemborosan lookup DB);
  * jumlah pesan per koneksi (flood setelah autentikasi).

BATAS YANG PERLU DIKETAHUI: state ada di memori PER PROSES. Dengan N worker,
batas efektif per IP adalah sampai N x limit. Itu cukup untuk meredam
brute force (token 256 bit, tidak bisa ditebak) dan flood sederhana tanpa
Redis; batas global yang presisi memerlukan penyimpanan bersama (di luar
scope Phase A). Alamat IP hanya bermakna jika uvicorn dijalankan dengan
--proxy-headers di belakang reverse proxy tepercaya (lihat README).

Stdlib saja; jam disuntikkan agar bisa diuji tanpa sleep.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Callable, Hashable


class SlidingWindowLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 10_000,
    ) -> None:
        if limit <= 0 or window_seconds <= 0 or max_keys <= 0:
            raise ValueError("limit, window_seconds, dan max_keys harus > 0")
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._max_keys = max_keys
        self._events: dict[Hashable, deque[float]] = {}

    def _trim(self, key: Hashable, now: float) -> deque[float] | None:
        events = self._events.get(key)
        if events is None:
            return None
        cutoff = now - self.window
        while events and events[0] <= cutoff:
            events.popleft()
        if not events:
            del self._events[key]
            return None
        return events

    def count(self, key: Hashable) -> int:
        events = self._trim(key, self._clock())
        return len(events) if events else 0

    def is_limited(self, key: Hashable) -> bool:
        """True jika `key` sudah mencapai batas di jendela saat ini."""
        return self.count(key) >= self.limit

    def hit(self, key: Hashable) -> bool:
        """Catat satu kejadian. True = masih dalam batas, False = melampaui."""
        now = self._clock()
        events = self._trim(key, now)
        if events is None:
            if len(self._events) >= self._max_keys:
                self.prune()
            if len(self._events) >= self._max_keys:
                # Tabel penuh oleh key aktif (serangan terdistribusi): perlakukan
                # key baru sebagai terbatas daripada membiarkan memori tumbuh.
                return False
            events = self._events.setdefault(key, deque())
        events.append(now)
        return len(events) <= self.limit

    def prune(self) -> int:
        """Buang key yang jendelanya sudah kosong. Mengembalikan jumlah dibuang."""
        now = self._clock()
        before = len(self._events)
        for key in list(self._events):
            self._trim(key, now)
        return before - len(self._events)

    def __len__(self) -> int:
        return len(self._events)
