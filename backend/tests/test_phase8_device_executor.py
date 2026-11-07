import asyncio
import threading
import time

import pytest

from app.network import device_executor
from app.network.device_executor import acquire_device_slot


@pytest.mark.asyncio
async def test_routeros_executor_serializes_per_device_and_holds_slot_after_timeout():
    active = 0
    maximum = 0
    lock = threading.Lock()

    def slow_call():
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.04)
        with lock:
            active -= 1

    async def one_call():
        slot = await acquire_device_slot("same-router")
        try:
            await slot.run(slow_call, timeout=1)
        finally:
            slot.release()

    await asyncio.gather(*(one_call() for _ in range(4)))
    assert maximum == 1

    timed = await acquire_device_slot("timeout-router")
    with pytest.raises(TimeoutError):
        await timed.run(lambda: time.sleep(0.12), timeout=0.01)
    timed.release()

    started = time.perf_counter()
    next_slot = await acquire_device_slot("timeout-router")
    waited = time.perf_counter() - started
    next_slot.release()
    assert waited >= 0.07



@pytest.mark.asyncio
async def test_routeros_executor_rejects_long_device_queue(monkeypatch):
    monkeypatch.setattr(device_executor, "QUEUE_TIMEOUT_SECONDS", 0.01)
    held = await acquire_device_slot("busy-router")
    try:
        with pytest.raises(TimeoutError, match="device is busy"):
            await acquire_device_slot("busy-router")
    finally:
        held.release()
