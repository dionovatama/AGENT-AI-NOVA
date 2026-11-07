"""Run real FastAPI HTTP paths with a mocked slow relay and mocked RouterOS sync call.

Requires a migrated PostgreSQL test database. This script patches only the device
context/relay/RouterOS boundary; it never contacts a physical router or Agent.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import uvicorn

from app.api import mikrotik_monitoring as monitoring
from app.config import settings
from app.database.models import Device, User
from app.database.session import SessionLocal
from app.main import app
from app.network import remote_transport
from app.security.hashing import create_access_token


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * pct))))
    return round(ordered[index], 2)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrency", type=int, default=20, choices=(20, 100))
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--device-count", type=int, default=20)
    parser.add_argument("--relay-delay-ms", type=int, default=100)
    parser.add_argument("--operation-delay-ms", type=int, default=50)
    parser.add_argument("--offline-every", type=int, default=0)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    owner_id = uuid.uuid4()
    device_ids = [uuid.uuid4() for _ in range(max(1, args.device_count))]
    email = f"phase8-load-{owner_id.hex}@example.invalid"
    with SessionLocal() as db:
        db.add(User(id=owner_id, email=email, hashed_password="loadtest-only", is_active=True))
        for index, device_id in enumerate(device_ids):
            db.add(Device(
                id=device_id, owner_id=owner_id, name=f"mock-router-{index}",
                platform="mikrotik", host="192.0.2.1", port=8729,
                connection_type="api-ssl", status="active",
                device_metadata={"username": "mock-operator"},
            ))
        db.commit()

    token = create_access_token(subject=str(owner_id))
    counter = {"calls": 0}

    def mock_monitor_sync(device, password, sock=None):
        counter["calls"] += 1
        if args.offline_every and counter["calls"] % args.offline_every == 0:
            raise ConnectionError("simulated agent offline")
        time.sleep(args.operation_delay_ms / 1000)
        return {
            "resource": {
                "cpu-load": "17", "total-memory": "1073741824", "free-memory": "536870912",
                "total-hdd-space": "1000000000", "free-hdd-space": "500000000",
                "version": "7.15", "board-name": "mock",
            },
            "identity": {"name": "mock-router"},
            "routerboard": {"model": "mock"},
            "interfaces": [{
                "name": "ether1", "running": True, "disabled": False,
                "rx_bps": 100000, "tx_bps": 200000,
            }],
            "neighbors": [], "arp": [], "dhcp_leases": [], "bridge_hosts": [],
        }

    def mock_device_context(device, user, db):
        return SimpleNamespace(device=device, user=user, db=db, credential_plaintext="mock-only")

    @asynccontextmanager
    async def mock_slow_relay(device, ctx):
        await asyncio.sleep(args.relay_delay_ms / 1000)
        yield object()  # sentinel socket; fake RouterOS function never writes to it

    monitoring._monitor_sync = mock_monitor_sync
    monitoring.build_device_context = mock_device_context
    remote_transport.remote_api_socket = mock_slow_relay

    config = uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning", workers=1)
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        if server_task.done():
            await server_task
            raise RuntimeError("mock load-test server failed to start")
        await asyncio.sleep(0.05)

    headers = {"Authorization": f"Bearer {token}"}
    latencies: list[float] = []
    statuses: list[int] = []
    start_cpu = 0.0
    start_rss = 0
    try:
        try:
            import psutil
            process = psutil.Process()
            start_cpu = process.cpu_percent(interval=None)
            start_rss = process.memory_info().rss
        except ImportError:
            process = None

        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{args.port}", timeout=45.0) as client:
            semaphore = asyncio.Semaphore(args.concurrency)

            async def request_one(index: int):
                device_id = device_ids[index % len(device_ids)]
                if index % 2:
                    path = f"/devices/{device_id}/monitoring"
                else:
                    path = f"/devices/{device_id}/monitoring/history?minutes=60"
                async with semaphore:
                    started = time.perf_counter()
                    response = await client.get(path, headers=headers)
                    latencies.append((time.perf_counter() - started) * 1000)
                    statuses.append(response.status_code)

            await asyncio.gather(*(request_one(i) for i in range(args.requests)))

        end_cpu = process.cpu_percent(interval=None) if process else None
        end_rss = process.memory_info().rss if process else None
        failed = sum(1 for status in statuses if status >= 400)
        print(json.dumps({
            "concurrency": args.concurrency,
            "requests": args.requests,
            "device_count": len(device_ids),
            "relay_delay_ms": args.relay_delay_ms,
            "operation_delay_ms": args.operation_delay_ms,
            "p50_ms": _percentile(latencies, 0.50),
            "p95_ms": _percentile(latencies, 0.95),
            "p99_ms": _percentile(latencies, 0.99),
            "error_rate_percent": round(failed * 100 / max(1, len(statuses)), 2),
            "status_counts": {str(code): statuses.count(code) for code in sorted(set(statuses))},
            "process_cpu_percent_before_after": [start_cpu, end_cpu],
            "process_rss_mb_before_after": [
                round(start_rss / 1024 / 1024, 2) if start_rss else None,
                round(end_rss / 1024 / 1024, 2) if end_rss else None,
            ],
            "mock_router_calls": counter["calls"],
        }, indent=2))
    finally:
        server.should_exit = True
        await server_task
        with SessionLocal() as db:
            db.query(Device).filter(Device.id.in_(device_ids)).delete(synchronize_session=False)
            db.query(User).filter(User.id == owner_id).delete(synchronize_session=False)
            db.commit()


if __name__ == "__main__":
    asyncio.run(main())
