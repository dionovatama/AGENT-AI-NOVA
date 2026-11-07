# N.O.V.A Security Audit — Phase 8.1

**Audit basis:** source inspection of branch `chatbot` before Phase 8 changes. Work branch: `feat/phase8-hardening` (created from `chatbot`). This document records observed code, not claims from older phase documents.

## Scope and evidence limitations

Inspected: `backend/app/main.py`, `app/config.py`, all API router modules registered by `main.py` (auth, chat, conversations, network, monitoring, tools, devices/credentials/audit, configurations, generators, images, legacy agent WS, DB-backed agents WS and relay targets), selected agent/relay/TLS modules, MikroTik and Linux execution paths, security dependencies/audit/sanitization, frontend auth/API, requirements and package manifests.

The requested root documents `PHASE2..PHASE6*.md` were not all present at the paths checked. `PHASE5_MIKROTIK_REMOTE.md` exists and was read. It says local MikroTik API-SSL `CERT_NONE` is a known development gap and that pin update was not implemented; current code has since added a PATCH route, but that route is not yet safe enough (see H-04). Do not treat missing documents as proof that a phase was never completed.

Not executed in this audit environment: `pytest`, `pip-audit`, `npm audit`, live router/Agent tests, deployment/VPS tests. No dependency vulnerability count is asserted.

## Executive summary

The current code has meaningful controls: JWT dependencies on most HTTP APIs, owner-scoped device/credential/conversation/agent/target/topology/monitoring queries, Tool Manager policy enforcement, a category allowlist for LLM tool calls, and certificate pin verification on the Agent relay path.

It is **not production-ready for an internet-exposed multi-user deployment yet**. Major gaps include missing production startup validation, hardcoded localhost CORS, unpinned local API-SSL, optional SSH host-key verification, unauthenticated-by-Origin WebSocket acceptance, missing rate limits on key endpoints, unsafe pin rotation semantics, and process-local relay state without a multi-worker guard.

## HTTP endpoint inventory

All listed routes are registered in `backend/app/main.py`. Unless stated otherwise, HTTP handlers use `Depends(get_current_user)` (JWT Bearer) and Pydantic request models.

| Router / endpoint | Auth | Tenant / resource ownership observed | Input validation | Rate limit |
|---|---|---|---|---|
| `POST /auth/register` | No | Creates new user; email uniqueness lookup | EmailStr; password 8..128 | **None** |
| `POST /auth/login` | No | User lookup by email | EmailStr; password has no explicit max length | **None** |
| `GET /auth/me` | JWT | Current user from JWT | JWT subject parsed as UUID | None |
| `POST /chat/completions` | JWT | Direct configuration device lookup filters owner_id; nested create_configuration checks owner | message 1..8000, enum category, UUID device_id; configuration parsing has domain checks | **None** |
| `POST /chat/documents/completions` | JWT (verify in handler) | No device mutation expected | multipart file/message; no global request/file size cap observed | **None** |
| `POST /conversations`, `GET /conversations` | JWT | owner_id filter | title 1..160; list limit 1..100 | None |
| `GET/POST /conversations/{id}/messages`, `PATCH/DELETE /conversations/{id}` | JWT | Conversation checked by (id, owner_id) before child message query/mutation | UUID; role enum; content 1..30000; metadata arbitrary JSON | **None** |
| `GET /network/topology` | JWT | Agent, Device, RelayTarget queries filter owner_id | No request body | None |
| `POST /network/devices/{id}/refresh` | JWT | Device lookup filters id + owner_id | UUID | **None** |
| `GET /network/manual-topology` | JWT | Nodes, links, devices and targets owner-scoped | No request body | None |
| `POST/PATCH/DELETE /network/manual-topology/nodes[/{id}]` | JWT | Owner-scoped node/device/target checks | Pydantic bounds for names, kind, coordinates | None |
| `POST/DELETE /network/manual-topology/links[/{id}]` | JWT | Both nodes and link owner-scoped | UUIDs, label/kind bounds, self-link rejected | None |
| `GET /devices`, `GET/DELETE/PATCH /devices/{id}` | JWT | Device queries filter id + owner_id | UUID and Device schemas; patch checks credential owner | None |
| `POST /devices` | JWT | Credential reference checked by id + owner_id; owner assigned from JWT | Device schema | None |
| `GET/POST/DELETE /credentials[/{id}]` | JWT | All credential queries owner-scoped; encryption at rest | Credential schemas | None |
| `GET /audit-logs` | JWT | AuditLog.user_id filter | No request body | None |
| `GET /devices/{id}/monitoring`, `GET /devices/{id}/monitoring/history` | JWT | Device lookup owner-scoped; history sample query tied to owned device | UUID, bounded minutes/interface validation | **None** |
| `GET /tools/list`, `POST /tools/execute` | JWT | Tool Manager resolves requested device under authenticated owner (verify in manager tests) | ToolRequest schema, allowlist/schema/policy checks | **None** |
| `POST /configurations` and configuration lifecycle routes | JWT | Create path checks Device.id + owner_id; lifecycle handlers require owner-scoped Configuration | ChangeSet/schema/semantic validation | None |
| `GET /mikrotik-config-generator/generate` (POST) | JWT | No tenant resource | Pydantic bounds and domain validation | None |
| `POST /linux-config-generator/generate` | JWT | No tenant resource | Literal modules, port bounds, hostname validation | None |
| `POST /images/generate` | JWT | User identity used for per-user in-memory limiter | Prompt 1..2000 | In-memory 10/min/user (not shared across workers) |
| `POST /agents`, `GET /agents`, `GET /agents/{id}`, rotate/disconnect/delete | JWT | Agent queries filter id + owner_id; row lock for rotate/delete | UUID, Agent schema | None |
| `POST/GET/PATCH/DELETE /agents/{agent_id}/targets[/{target_id}]` | JWT | Agent and target filter owner_id; optional device checked owner_id | Relay target schemas and ports | None |

**Notes:** The chat document handler's exact file-size behavior and all configuration lifecycle handlers require further test/source-level review. `/health` is intentionally public and returns only service/environment status.

## WebSocket endpoint inventory

| Endpoint | Authentication | Ownership / validation | Rate limit / Origin |
|---|---|---|---|
| `/ws/agent/{agent_id}` (DB-backed Agent) | Agent token handshake in AgentConnectionManager; production TLS can be required via config | UUID agent identity and DB token/connection claim; owner is tied to Agent record | Per-process auth-failure/pending/message limit exists; explicit Origin policy not observed |
| `/agent/ws` (legacy static-token gateway) | Pre-provisioned static token from `NOVA_AGENT_TOKENS_JSON` using constant-time compare | UUID + token map; no DB tenant owner model | No rate limiter or Origin policy observed; state is process-local |

WebSocket handshake is accepted before authentication on the legacy endpoint; the DB-backed endpoint delegates to the manager. Neither route has a visible explicit Origin allow/deny policy in the inspected handlers. Browser Origin is not an authentication substitute, but a deliberate policy is still required.

## Findings

Severity uses: Critical = immediate exploitable compromise; High = unsafe for stated public multi-tenant production; Medium = defense-in-depth / availability / privacy gap; Low = hygiene or operational recommendation.

| ID | Severity | Finding / evidence | Status at audit |
|---|---|---|---|
| H-01 | **High** | Production startup does not validate JWT secret strength/length, mandatory Agent TLS, or CORS origins. `main.py` directly builds app; `config.py` has no production validators. `agent_require_tls=None` resolves secure by default in wiring, but explicit false can override. | Open |
| H-02 | **High** | CORS is hardcoded to localhost origins in `main.py`, not deployment configuration. Public deployment would either reject the real frontend or encourage unsafe ad-hoc changes. | Open |
| H-03 | **High** | Local MikroTik `api-ssl` sets `ssl.CERT_NONE` with no certificate pin. `backend/app/tools/mikrotik.py::_connect`. Relay TLS is pinned, but local path is not. | Open |
| H-04 | **High** | PATCH relay-target pin endpoint replaces/clears pin without explicit confirmation/expected-old-pin precondition. Audit records only `tls_pinned` boolean, not truncated old/new fingerprints. `FINGERPRINT_MISMATCH.observed` is held by exception but current remote transport drops it instead of exposing a controlled operator-only flow. | Open |
| H-05 | **High** | SSH host-key verification is disabled by default and `known_hosts=None` when `linux_ssh_host_key_checking` is false. Seen in `app/tools/linux.py` and `network/adapters/linux.py`. No production startup/connect guard was observed. | Open |
| H-06 | **High** | No rate limiting on login/register/chat/tools execution/device monitoring; only Agent connection/message limiter and image-generation per-process limiter exist. Password login brute force and expensive endpoints are exposed. | Open |
| H-07 | **High** | Relay channel/registry/session/limiter are process-local. `relay_service.py` explicitly says Agent connection must be live in THIS worker; no worker affinity or broker. Multi-worker requests can fail intermittently. | Open |
| H-08 | **High** | Error details may expose device/SSH/RouterOS/provider exception strings. Examples: MikroTik `_connection_error_message` and TrapError paths include raw exception; configuration creation returns `{exc}` in 502; Linux legacy tools return raw AsyncSSH exception. Sanitization coverage is not uniformly applied at every response boundary. | Open |
| M-01 | **Medium** | No global request-body size middleware/config was observed. Chat document uploads accept multipart UploadFile; file size limits need enforcement before parsing/extraction. | Open |
| M-02 | **Medium** | No common security headers middleware observed (`nosniff`, frame-ancestors/X-Frame-Options, Referrer-Policy). | Open |
| M-03 | **Medium** | Legacy `/agent/ws` gateway remains process-local and does not use the DB-backed owner-scoped Agent lifecycle; should be disabled/retired before public multi-tenant deployment if no longer required. | Open |
| M-04 | **Medium** | Prompt-injection boundary: tool schemas are category allowlisted, READ-only, and executed through ToolManager; however device output/log/neighbor/DHCP values are returned as tool results to the LLM without an explicit universal untrusted-data wrapper visible in the inspected tool-calling path. | Open |
| M-05 | **Medium** | Rate limit state is per-process for Agent and image generation; it is not a global quota under multiple workers/restarts. | Open |
| M-06 | **Medium** | SQLAlchemy engine uses `pool_pre_ping=True` but leaves pool_size/max_overflow/pool_timeout at SQLAlchemy defaults. | Open |
| L-01 | **Low** | Frontend stores JWT in localStorage (`frontend/lib/auth.ts`), increasing token exposure under XSS; migrate to Secure, HttpOnly, SameSite cookie/BFF design. | Open |
| L-02 | **Low** | Agent API response exposes owner_id (not secret, but unnecessary to browser clients). | Open |
| L-03 | **Low** | Dependency audit has not yet been run in this environment. | Not assessed |

## Positive controls verified

- `get_current_user` validates Bearer JWT, UUID subject, active user.
- Device and credential endpoints filter owner_id; credential secret is encrypted at rest and response schema avoids plaintext secret.
- Conversation messages are only queried after parent conversation ownership check.
- Monitoring endpoint resolves Device by id + owner_id; history is scoped through that owned device.
- Relay service checks RelayTarget and Agent by owner_id and validates allowed port.
- Agent REST endpoints use owner-scoped queries; rotate/delete use row locking.
- Network topology/manual nodes/links and audit-log listing are owner-scoped in inspected handlers.
- LLM tool-calling uses category allowlist, excludes non-READ/HIGH risk/internal-only tools, limits iterations/calls, and routes execution through ToolManager.
- Relay TLS performs SHA-256 pin comparison before application data can flow; mismatch closes the channel.
- Agent tokens are hashed in DB; plaintext returned only on provisioning/rotation response.
- Audit metadata/error pass through sanitization before persistence.

## Prompt-injection assessment

The inspected tool-calling bridge has strong *action authorization* boundaries: model-proposed tool names are checked against a category allowlist, schema, READ permission and risk, then rechecked before ToolManager execution. Device selection for model-invoked MikroTik tools is resolved from the authenticated owner, not supplied by the model.

However, device-derived values (interface comments, DHCP hostnames, neighbor identity, log lines, process names, etc.) are data controlled by a potentially hostile remote system. The tool-result JSON is appended to the model conversation as `role=tool`; the inspected code does not add a universal explicit untrusted-data wrapper or a rule to never follow instructions embedded in those values. This is a defense-in-depth gap; it does not bypass ToolManager policy by itself, but can influence model output and future tool proposals.

## Older phase document discrepancy

`PHASE5_MIKROTIK_REMOTE.md` says no update-pin endpoint exists and instructs deleting/recreating a target. Current branch has `PATCH /agents/{agent_id}/targets/{target_id}` and frontend `updateRelayTargetPin()`. The implementation does not require a confirmation token/expected old pin and audits only a boolean, so the document is stale and the new endpoint is incomplete from a security perspective.

## Next actions by phase

- **8.1:** turn all High findings into regression-tested fixes; retain Medium/Low recommendations here.
- **8.2:** production-only guards for local API-SSL pinning and SSH known_hosts; safe explicit pin rotation and operator-only mismatch details.
- **8.3:** document process-local relay design and fail startup when multiple workers are configured while relay is enabled. No Redis/broker will be added without approval.
- **8.4:** add mocked load harness and record only measured results; do not claim hardware/VPS results not executed.
- **8.5:** add regression tests for every fix and run full tests/audits where an executable environment is available.
