# Phase 3 — Remote Relay Protocol

**Status:** Protocol contract and state-management foundation implemented.  
**Protocol:** additive extension to Agent protocol v1 (authentication and heartbeat remain unchanged).  
**Scope boundary:** Phase 3 defines and validates relay messages and session lifecycle. Opening local TCP sockets, destination allow-list enforcement, and byte forwarding belong to Phase 4.

## Architecture constraints

- Reuse the existing authenticated `/ws/agent/{agent_id}` connection.
- Do not put credentials in relay messages.
- Identify destinations by registered `target_id` UUID; never accept arbitrary hostnames/IP addresses in relay frames.
- Tenant/owner, Agent, connection, and session ownership must all match before a session can be used.
- Relay session registry is currently process-local. Multi-worker command routing requires a shared broker or explicit worker affinity before production use.
- Keep protocol v1 auth, `registered`, heartbeat, ACK, and `bye` messages unchanged.

## Message envelope

All messages are JSON text frames with a `type` field. UUID values are canonical UUID v4 strings.

| Type | Direction | Required fields | Purpose |
|---|---|---|---|
| `OPEN_TUNNEL` | Backend → Agent | `request_id`, `session_id`, `target_id`, `port` | Ask Agent to open an authorized target/port in Phase 4 |
| `TUNNEL_OPENED` | Agent → Backend | `request_id`, `session_id` | Correlated success response |
| `TUNNEL_ERROR` | Agent → Backend | `request_id`, `session_id`, `code`, `message` | Correlated safe failure |
| `DATA` | Both directions | `session_id`, `seq`, `data` | Base64-encoded byte chunk |
| `CLOSE_TUNNEL` | Both directions | `session_id`, optional `reason` | Close a relay session |

`DATA` is limited to 32 KiB decoded per frame. The relay envelope is limited to 48 KiB, below the Agent connection's 64 KiB message cap. Sequence values are non-negative integers and must be monotonic per direction/session when Phase 4 implements forwarding.

Allowed `TUNNEL_ERROR.code`: `TARGET_NOT_ALLOWED`, `TARGET_UNAVAILABLE`, `CONNECT_FAILED`, `TIMEOUT`, `RESOURCE_LIMIT`, `PROTOCOL_ERROR`, `CANCELLED`.

Allowed close reasons: `requested`, `peer_closed`, `timeout`, `agent_disconnect`, `backend_shutdown`, `error`.

## Session lifecycle

```text
REQUESTED ── TUNNEL_OPENED ──> OPEN ── CLOSE_TUNNEL ──> CLOSED
    │                           │
    ├── TUNNEL_ERROR ──> FAILED │
    └── timeout/disconnect ─────┴─────────────────────> CLOSED
```

- `DATA` is valid only in `OPEN`.
- A session is bound to `(owner_id, agent_id, connection_id, target_id)`.
- A new request must use a unique `request_id` and `session_id`.
- The initial in-process limit is 8 active sessions per Agent; idle timeout default is 60 seconds.
- Disconnect cleanup closes all active sessions for that exact Agent connection.
- Terminal sessions cannot be reopened or reused.

## Phase 3 implementation checklist

- [x] Audit existing Agent protocol v1 and connection loop.
- [x] Define additive relay message types and strict parsers.
- [x] Define message builders and bounded DATA payload.
- [x] Define relay session state model and per-Agent concurrency limit.
- [x] Bind session lookup to owner, Agent, and connection identity.
- [x] Add timeout and disconnect cleanup primitives.
- [x] Add backend and Agent protocol unit tests.
- [ ] Integrate relay dispatch into the live WebSocket loop.
- [ ] Add authenticated backend API/orchestrator entry point for opening sessions.
- [ ] Add shared cross-worker routing or document/enforce single-worker affinity.
- [ ] Add full bidirectional data-path tests once Phase 4 TCP connector exists.

## Explicit Phase 4 prerequisites

Before any TCP socket is opened, implement and test a server-side target registry and Agent-side destination allow-list. Agent must resolve `target_id` from trusted configuration/authorization data; the Agent must not trust arbitrary destination values supplied by the backend. Enforce permitted ports, DNS/IP resolution policy, connection timeout, idle timeout, bounded queues, backpressure, and concurrent socket limits. MikroTik remote access must use API-SSL with certificate validation.

## Compatibility

The extension is additive. Existing protocol-v1 authentication, registration, heartbeat ACK, and graceful shutdown messages are not changed. Existing Agent 0.2.0 remains compatible when no relay command is sent. The new Agent parser rejects unknown server relay messages rather than silently accepting malformed relay data.
