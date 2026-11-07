"""Bounded executor for synchronous librouteros calls.

At most 16 RouterOS operations run concurrently across the process and one per
device. Requests wait on semaphores rather than accumulating in the default
asyncio thread-pool queue. A timed-out/cancelled request keeps its slot until
the underlying thread actually exits.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Callable

GLOBAL_LIMIT = 16
PER_DEVICE_LIMIT = 1
OPERATION_TIMEOUT_SECONDS = 30.0
QUEUE_TIMEOUT_SECONDS = 5.0

_executor = ThreadPoolExecutor(max_workers=GLOBAL_LIMIT, thread_name_prefix="nova-routeros")
_global_slots = asyncio.Semaphore(GLOBAL_LIMIT)
_device_slots: dict[str, asyncio.Semaphore] = {}


class DeviceExecutionSlot:
    def __init__(self, global_slot: asyncio.Semaphore, device_slot: asyncio.Semaphore):
        self._global_slot = global_slot
        self._device_slot = device_slot
        self._future: asyncio.Future | None = None
        self._released = False
        self._release_deferred = False

    async def run(self, fn: Callable[..., Any], *args: Any,
                  timeout: float = OPERATION_TIMEOUT_SECONDS) -> Any:
        loop = asyncio.get_running_loop()
        self._future = loop.run_in_executor(_executor, partial(fn, *args))
        try:
            return await asyncio.wait_for(asyncio.shield(self._future), timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError("RouterOS operation exceeded its execution timeout.") from None

    def _release_now(self) -> None:
        if self._released:
            return
        self._released = True
        self._device_slot.release()
        self._global_slot.release()

    def release(self) -> None:
        if self._released or self._release_deferred:
            return
        if self._future is not None and not self._future.done():
            self._release_deferred = True
            self._future.add_done_callback(lambda _: self._release_now())
        else:
            self._release_now()


async def acquire_device_slot(device_id: object) -> DeviceExecutionSlot:
    key = str(device_id)
    device_slot = _device_slots.setdefault(key, asyncio.Semaphore(PER_DEVICE_LIMIT))
    try:
        await asyncio.wait_for(_global_slots.acquire(), timeout=QUEUE_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        raise TimeoutError("RouterOS executor is at global capacity; retry shortly.") from None
    try:
        await asyncio.wait_for(device_slot.acquire(), timeout=QUEUE_TIMEOUT_SECONDS)
    except BaseException:
        _global_slots.release()
        if isinstance(_, asyncio.TimeoutError):
            raise TimeoutError("RouterOS device is busy; retry shortly.") from None
        raise
    return DeviceExecutionSlot(_global_slots, device_slot)
