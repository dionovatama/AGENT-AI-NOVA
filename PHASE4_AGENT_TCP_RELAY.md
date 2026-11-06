# Phase 4 — Remote Agent TCP Relay

Scope: Agent side. The Agent opens local TCP connections for authorized `OPEN_TUNNEL`
requests and forwards bytes as `DATA` frames. Protocol (Phase 3) is unchanged.

## Allow-list (trusted, local)

The backend sends only `target_id` + `port`. The Agent maps `target_id` to a host from
`relay_targets` in its own `config.json`:

```json
"relay_targets": [
  {"target_id": "<uuid v4>", "host": "192.168.88.1", "ports": [8729]}
]
```

- Unknown `target_id` or port not listed -> `TUNNEL_ERROR TARGET_NOT_ALLOWED`.
- Always refused: unspecified, multicast, link-local (169.254/16, fe80::/10), reserved.
- Loopback refused unless the target sets `"allow_loopback": true` (dev/test only).
- Hostnames are resolved by the Agent; if ANY address is refused, the target is refused.
- The Agent dials the validated IP (no second DNS lookup).
- No `relay_targets` configured -> relay disabled; `OPEN_TUNNEL` returns `TARGET_UNAVAILABLE` (old behavior).

## Limits (`RelayLimits` defaults)

8 sessions per Agent, 5 s DNS, 10 s connect, 60 s idle, inbound queue 32 frames
(overflow closes the session), DATA <= 32 KiB, DATA `seq` from backend must increase.
Error text sent to the backend is fixed and safe (no IPs, no OS errors).

## Audit

Local log lines: `relay open|denied|closed` with session, target_id, port, byte counts, reason.

## Backend side (target registry + relay entry point)

- Table `relay_targets` (migration `e5f607182930`, run `alembic upgrade head`): `id` is the `target_id`
  sent in `OPEN_TUNNEL`; owner, agent, optional device, host, ports.
- REST (owner-scoped, foreign ids -> 404):
  `POST|GET /agents/{agent_id}/targets`, `DELETE /agents/{agent_id}/targets/{target_id}`.
  The create/get response has `agent_config`: paste it into the Agent's `relay_targets`.
  Host rules: loopback, link-local, multicast, unspecified, reserved are refused at registration.
- `app/agents/relay_service.open_relay(db, owner_id=, target_id=, port=)` -> `RelayChannel`
  (`send(bytes)`, `recv()`, `close()`). Checks owner, port, Agent online, live connection on THIS worker.
  Audit events: `relay.open`, `agent.target.created|deleted`.
- `AgentConnectionManager.open_relay_channel` does the OPEN_TUNNEL handshake, DATA both ways
  (32 KiB chunks, bounded inbound queue, overflow closes the session), close, and cleanup on disconnect.

## Still open

- [ ] Multi-worker routing: relay is process-local (single worker, or affinity, until a broker exists).
- [ ] Ship Agent-side relay audit events to the backend audit log.
- [ ] Phase 5: MikroTik adapter over `RelayChannel` (API-SSL with real certificate validation).
- [ ] Real Windows/Linux Agent test with a MikroTik in the lab.
