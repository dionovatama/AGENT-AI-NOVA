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


async def _agent(agent_id: str, token: str, url_template: str, heartbeat_seconds: float, stats: dict):
    backoff = 1.0
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
                stats["reconnects"] += 1 if backoff < 1.0 else 0
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
        await asyncio.sleep(backoff)
        backoff = min(30.0, backoff * 2)


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
        asyncio.create_task(_agent(agent_id, token, url, args.heartbeat_seconds, stats))
        for agent_id, token in selected
    ]
    print(f"Connected simulator tasks: {len(tasks)}. Press Ctrl+C to stop.")
    await STOP.wait()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
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
    }, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
