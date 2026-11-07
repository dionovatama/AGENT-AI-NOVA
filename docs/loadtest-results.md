# Phase 8.4 — Load and reliability tests

These scripts are development-only and do not touch a physical router. The HTTP harness patches the RouterOS sync boundary and relay context inside a local FastAPI process, while retaining the real auth, monitoring/history routes, PostgreSQL sample persistence, and bounded RouterOS executor. It requires the backend test database to be migrated.

## Install

From backend:

    python -m pip install -r loadtest/requirements-dev.txt
    alembic upgrade head

The dependencies are intentionally separate from production requirements.txt.

## HTTP monitoring/history load

Run 20 and 100 concurrent requests with a mocked relay delay:

    python loadtest/run_mocked_http_load.py --concurrency 20 --requests 200 --device-count 20 --relay-delay-ms 100 --operation-delay-ms 50
    python loadtest/run_mocked_http_load.py --concurrency 100 --requests 500 --device-count 50 --relay-delay-ms 250 --operation-delay-ms 100

The script reports p50/p95/p99, HTTP error rate/status counts, mock RouterOS call count, and process CPU/RSS. It seeds and removes its own test user/devices. The relay and RouterOS boundaries are patched; no real Agent or router is contacted.

To simulate an Agent going offline mid-request, add --offline-every 7. Those monitoring requests should fail with 502 and request latency should remain bounded by the mocked relay/operation and executor behavior.

## Agent WSS heartbeat load

Pre-provision test Agents through the normal owner-authenticated POST /agents endpoint. Put their one-time plaintext tokens in a local environment variable (never a committed file):

    export NOVA_LOADTEST_WSS_URL='wss://127.0.0.1:8000/ws/agent/{agent_id}'
    export NOVA_LOADTEST_AGENT_TOKENS_JSON='{"<agent-uuid>":"<one-time-agent-token>"}'
    python loadtest/simulate_agents.py --count 50
    python loadtest/simulate_agents.py --count 200

The simulator uses Agent protocol v1 auth/heartbeat/bye frames and reconnects with exponential backoff after transient disconnects. For restart testing, start the simulator, restart the backend once, and verify connections recover without manually restarting the simulator. Authentication failures and rate-limit close codes are not aggressively retried.

## Graceful shutdown

Send SIGTERM to the backend while simulator sessions are active. The backend's existing Agent manager shutdown sends close code 1001; the simulator then reconnects after the backend returns. Observe server logs for relay/session cleanup and ensure no pending task warnings.

## Database pool / thread executor

The backend now exposes DB_POOL_SIZE (default 10), DB_MAX_OVERFLOW (20), and DB_POOL_TIMEOUT_SECONDS (30). The synchronous RouterOS executor has a 16-thread global cap, one active operation per device, a 5-second queue wait timeout, and a 30-second operation timeout. A timed-out thread retains its capacity slot until it actually exits, so cancellation does not create unbounded hidden work.

## Results recorded from this environment

**Not run.** This execution environment has GitHub source-edit access but no checked-out runnable backend, PostgreSQL test database, or local WSS server. No numerical performance results are claimed.

| Scenario | Target | Actual result |
|---|---:|---|
| Agent heartbeat simulation | 50 WSS Agents | Not run — no runnable backend/WSS environment |
| Agent heartbeat simulation | 200 WSS Agents | Not run — no runnable backend/WSS environment |
| Monitoring/history HTTP | 20 concurrent | Not run — no PostgreSQL test database |
| Monitoring/history HTTP | 100 concurrent | Not run — no PostgreSQL test database |
| Slow mocked relay / RouterOS | 100–250 ms relay + 50–100 ms executor delay | Harness added; not run |
| Backend restart / reconnect | Agent reconnects with backoff | Simulator added; not run |
| Agent offline mid-request | Fast bounded failure | Mock fault mode added; not run |
| Graceful shutdown | Close 1001, no orphaned task | Procedure documented; not run |

Run the commands above in the deployment-like test environment and append measured output here before treating load validation as complete.
