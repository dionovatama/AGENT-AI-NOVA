"""Simulate provisioned DB-backed Remote Agents over WSS (Agent protocol v1)."""
from __future__ import annotations

import asyncio
import json
import os
import signal
import time

import websockets

STOP = asyncio.Event()


def _stop(*_):
    STOP.set()


async def _agent(agent_id: str, token: str, url_template: str, heartbeat_seconds: float, stats: dict, initial_delay: float = 0.0):
    if initial_delay:
        await asyncio.sleep(initial_delay)
    backoff = 1.0
    connected_before = False
    while not STOP.is_set():
        uri = url_template.format(agent_id=agent_id)
        try:
            async with websockets.connect(uri, open_timeout=10, close_timeout=3, max_size=65536) as ws:
                await ws.send(json.dumps({
                    "type": "auth",
                    "protocol_version": 1,
                    "token": token,
                    "os": "NOVA load simulator",
                    "agent_version": "8.4.0",
                    "hostname": f"load-{agent_id[:8]}",
                }))
                registered = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                if registered.get("type") != "registered":
                    stats["auth_failures"] += 1
                    return
                stats["connections"] += 1
                if connected_before:
                    stats["reconnects"] += 1
                connected_before = True
                backoff = 1.0
                interval = max(1.0, float(registered.get("heartbeat_interval_seconds", heartbeat_seconds)))
                seq = 0
                while not STOP.is_set():
                    await asyncio.sleep(interval)
                    started = time.perf_counter()
                    await ws.send(json.dumps({"type": "heartbeat", "seq": seq}))
                    reply = json.loads(await asyncio.wait_for(ws.recv(), timeout=interval * 2))
                    if reply.get("type") != "heartbeat_ack":
                        raise RuntimeError(f"unexpected frame type: {reply.get('type')}")
                    stats["heartbeats"] += 1
                    stats["heartbeat_latency_ms"].append((time.perf_counter() - started) * 1000)
                    seq += 1
                await ws.send(json.dumps({"type": "bye"}))
                return
        except websockets.exceptions.ConnectionClosed as exc:
            if exc.code in (4401, 4429):
                stats["auth_failures"] += 1
                return
            stats["disconnects"] += 1
        except (OSError, asyncio.TimeoutError, RuntimeError):
            stats["disconnects"] += 1

        if STOP.is_set():
            break
        await asyncio.sleep(backoff + (backoff * 0.1))
        backoff = min(30.0, backoff * 2)


async def _sample_backend_process(pid: int, samples: list[dict]):
    try:
        import psutil
    except ImportError:
        return
    try:
        process = psutil.Process(pid)
        process.cpu_percent(interval=None)
        while not STOP.is_set():
            await asyncio.sleep(1)
            samples.append({
                "cpu_percent": process.cpu_percent(interval=None),
                "rss_mb": round(process.memory_info().rss / 1024 / 1024, 2),
            })
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return


async def main():
    raw = os.environ.get("NOVA_LOADTEST_AGENT_TOKENS_JSON", "")
    url = os.environ.get("NOVA_LOADTEST_WSS_URL", "")
    if not raw or not url:
        raise SystemExit("Set NOVA_LOADTEST_AGENT_TOKENS_JSON and NOVA_LOADTEST_WSS_URL.")
    agents = json.loads(raw)
    if not isinstance(agents, dict) or not agents:
        raise SystemExit("NOVA_LOADTEST_AGENT_TOKENS_JSON must be a non-empty {agent_uuid: token} object.")

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=50, choices=(50, 200))
    parser.add_argument("--heartbeat-seconds", type=float, default=30.0)
    parser.add_argument("--backend-pid", type=int, default=int(os.environ.get("NOVA_BACKEND_PID", "0")))
    args = parser.parse_args()
    selected = list(agents.items())[:args.count]
    if len(selected) < args.count:
        raise SystemExit(f"Need {args.count} pre-provisioned Agent tokens; only {len(selected)} supplied.")

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass

    stats = {
        "connections": 0, "reconnects": 0, "disconnects": 0,
        "heartbeats": 0, "auth_failures": 0, "heartbeat_latency_ms": [],
    }
    tasks = [
        asyncio.create_task(_agent(agent_id, token, url, args.heartbeat_seconds, stats, index * 0.05))
        for index, (agent_id, token) in enumerate(selected)
    ]
    process_samples: list[dict] = []
    sampler = asyncio.create_task(_sample_backend_process(args.backend_pid, process_samples)) if args.backend_pid else None
    print(f"Connected simulator tasks: {len(tasks)}. Press Ctrl+C to stop.")
    await STOP.wait()
    # Let connected simulators send the protocol-v1 bye frame before closing.
    await asyncio.gather(*tasks, return_exceptions=True)
    if sampler:
        sampler.cancel()
        await asyncio.gather(sampler, return_exceptions=True)
    values = sorted(stats["heartbeat_latency_ms"])
    def pct(p):
        return round(values[min(len(values)-1, int((len(values)-1)*p))], 2) if values else None
    print(json.dumps({
        "simulated_agents": len(selected),
        "connections": stats["connections"],
        "reconnects": stats["reconnects"],
        "disconnects": stats["disconnects"],
        "heartbeats": stats["heartbeats"],
        "auth_failures": stats["auth_failures"],
        "heartbeat_ack_p50_ms": pct(0.50),
        "heartbeat_ack_p95_ms": pct(0.95),
        "heartbeat_ack_p99_ms": pct(0.99),
        "backend_process_cpu_percent_min_max": [
            min((s["cpu_percent"] for s in process_samples), default=None),
            max((s["cpu_percent"] for s in process_samples), default=None),
        ],
        "backend_process_rss_mb_min_max": [
            min((s["rss_mb"] for s in process_samples), default=None),
            max((s["rss_mb"] for s in process_samples), default=None),
        ],
    }, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
