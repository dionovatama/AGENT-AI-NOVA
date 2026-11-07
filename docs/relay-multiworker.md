# Relay multi-worker routing — Phase 8.3

## Current constraint

\`AgentConnectionManager\` keeps the live WebSocket registry, relay channels, pending tunnel sessions and rate-limit state in process memory. PostgreSQL stores Agent ownership/connection claims, but it does **not** transport relay frames between ASGI workers. \`open_relay()\` explicitly requires the live connection to exist in the worker handling the HTTP request.

Therefore, starting multiple workers without a cross-worker transport is not supported: the WebSocket can land on worker A while an HTTP monitoring request lands on worker B, which cannot access worker A's in-memory channel.

## Options and trade-offs

### A. Exactly one ASGI worker (recommended for initial VPS / dozens of Agents)

- Keep one process as the owner of all Agent WebSockets and relay sessions.
- Use asyncio concurrency within that process; do not confuse one worker with one request at a time.
- Simplest operational model, no new infrastructure, lowest latency and easiest failure diagnosis.
- Limitation: one process is a scaling and availability boundary. CPU-heavy work and large thread workloads need explicit limits; vertical scale or a future broker migration is required as load grows.

### B. Sticky routing by \`agent_id\`

- Reverse proxy routes the Agent WebSocket and all HTTP requests that use its relay target to the same worker.
- Requires a reliable way to associate every HTTP request with the correct Agent/worker and maintain affinity through reconnects, proxy restarts and multiple replicas.
- Cookie/IP stickiness is insufficient by itself: Agent WSS and user HTTP requests originate from different clients.
- Still leaves worker-local sessions and complicates failover. Not recommended as the first fix.

### C. Shared broker (Redis Pub/Sub or Streams)

- Workers publish relay open/data/close frames to a shared broker keyed by Agent/session; the worker owning the WSS forwards frames and returns responses.
- Enables multi-worker horizontal scaling and clear worker ownership/routing.
- Adds Redis availability, authentication/TLS, ACL, backpressure, message-size, delivery semantics, cleanup, observability and operational burden. Pub/Sub can lose frames during subscriber disconnect; Streams add persistence/consumer-group complexity.
- **Not implemented.** Requires explicit approval and a protocol/operational design before adding infrastructure.

## Decision

Choose **A** for the initial VPS deployment: one ASGI worker, with async I/O and bounded executor concurrency. Do not deploy Gunicorn with multiple Uvicorn workers or multiple backend replicas behind a load balancer while relay is enabled. Phase 8 adds a startup guard that rejects worker counts above one when detected from \`WEB_CONCURRENCY\`, \`UVICORN_WORKERS\`, \`GUNICORN_CMD_ARGS\`, or command-line \`--workers\` / \`-w\`.

Redis/broker option C is intentionally deferred and needs owner approval before implementation.

## Supported deployment command

From \`backend/\` (inside the activated virtual environment):

\`\`\`bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
\`\`\`

Equivalent Gunicorn form (exactly one worker):

\`\`\`bash
gunicorn app.main:app -k uvicorn.workers.UvicornWorker --workers 1 --bind 0.0.0.0:8000
\`\`\`

Set \`WEB_CONCURRENCY=1\` explicitly in the service environment. The startup guard checks environment and command-line worker declarations and fails fast if it detects more than one worker. Run only one backend replica until shared relay routing exists.
