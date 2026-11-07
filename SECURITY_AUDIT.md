# NOVA Security Audit — Phase 8.1

**Repository:** `dionovatama/AGENT-AI-NOVA`  
**Audited ref:** `phase7-monitoring-history`  
**Audited commit:** `70d6a4b08c7e4232854e41a1b54de9bd7a993e2b`  
**Audit date:** 2026-11-07  
**Method:** Static source review through repository files. Runtime tests, dependency audits, and live infrastructure tests have not yet been executed.

> This is an evidence-based baseline, not a production security certification. Items marked Open must not be interpreted as fixed.

## Executive summary

The branch has useful security foundations: JWT-protected user APIs, owner-scoped CRUD in the main device/credential/agent paths, encrypted credential storage, one-time Agent tokens stored as hashes, strict relay target IDs, and pinned TLS on the Remote Agent relay path.

The source does **not** yet justify public multi-tenant production deployment. The most important gaps found are:

1. Production startup does not enforce a strong JWT secret, mandatory Agent WSS, production CORS origins, or strict SSH host-key verification.
2. Direct/local MikroTik API-SSL uses `CERT_NONE` without certificate pinning.
3. Relay target pin replacement is a normal PATCH without an explicit confirmation challenge; the response serializes the full fingerprint.
4. HTTP rate limiting is not present on login/register, chat, tool execution, or monitoring. The existing Agent limiter is process-local.
5. Relay channel/session routing is process-local. Database-backed Agent connection ownership does not make relay frames routable across workers.
6. Error handling still forwards some exception text from device and AI provider paths.
7. JWT access tokens are stored in browser `localStorage`, exposing them to JavaScript executing in the origin.
8. The ASGI app has no observed global request-body cap or baseline security-header middleware.

## Severity and disposition

| ID | Severity | Finding | Evidence | Status |
|---|---|---|---|---|
| SEC-01 | High | No production startup validation for JWT secret strength, Agent TLS requirement, CORS origin, or SSH host-key policy | `backend/app/config.py`, `backend/app/main.py`, `backend/app/agents/wiring.py` | In Progress (Startup/JWT/TLS/CORS fixed) |
| SEC-02 | High | Direct/local MikroTik API-SSL disables certificate verification and has no pin | `backend/app/tools/mikrotik.py::_connect` | Open |
| SEC-03 | High | Linux SSH host-key checking defaults off; known_hosts path is optional | `backend/app/config.py`, `backend/app/tools/linux.py`, `backend/app/network/adapters/linux.py` | Open |
| SEC-04 | High | No HTTP rate-limit/lockout found on auth, chat, tool execution, or monitoring routes | `backend/app/api/auth.py`, `chat.py`, `tools.py`, `mikrotik_monitoring.py` | Fixed |
| SEC-05 | High | Relay target pin can be overwritten/cleared via PATCH without explicit confirmation; full fingerprint is returned by target response | `backend/app/api/agent_targets.py::_to_response/update_target_pin` | Open |
| SEC-06 | High | Relay channels, session registry, and Agent rate-limit state are process-local; cross-worker relay commands cannot reach the socket owner | `backend/app/agents/manager.py`, `relay_service.py`, `ratelimit.py`; PHASE3/4/5 docs | Open |
| SEC-07 | High | Several error paths interpolate raw exception strings into HTTP responses/logs; sanitizer is not a universal boundary | `backend/app/api/configurations.py`, `chat.py`, `mikrotik.py`, `mikrotik_monitoring.py` | Fixed |
| SEC-08 | Medium | CORS is hardcoded to localhost origins; there is no deployment-configured allowlist | `backend/app/main.py` | Fixed |
| SEC-09 | Medium | No global security headers or explicit request-body size middleware observed | `backend/app/main.py` | Open |
| SEC-10 | Medium | JWT is persisted in localStorage and attached as Bearer by frontend code | `frontend/lib/auth.ts`, `frontend/lib/api.ts` | Open |
| SEC-11 | Medium | Relay target API exposes full SHA-256 fingerprint in response; fingerprint is not a password but should be treated as trust metadata and operator-only | `backend/app/api/agent_targets.py::_to_response` | Open |
| SEC-12 | Medium | Legacy `/agent/ws` static-token WebSocket has independent process-local connection registry and no shared routing | `backend/app/api/agent.py` | Open |
| SEC-13 | Medium | Prompt-injection handling is explicit for uploaded documents, but device/neighbor/DHCP/log values must be checked at every LLM prompt construction boundary | `backend/app/api/chat.py`; AI prompt call sites require follow-up review | Partially reviewed |
| SEC-14 | Low | Agent limiter is per process; effective thresholds multiply with worker count | `backend/app/agents/ratelimit.py` | Documented |
| SEC-15 | Low | Frontend API defaults to localhost when deployment env is missing | `frontend/lib/api.ts` | Open |

## Endpoint inventory

Legend: **Auth** = JWT/current-user dependency; **Owner** = query/resource ownership is enforced in the reviewed code; **Validation** = request schema/path/query validation observed; **Limit** = explicit endpoint HTTP rate limit observed. "Not found" means no explicit limiter in the reviewed endpoint code; infrastructure-level reverse-proxy limits were not verified.

| Router / endpoint | Auth | Owner / tenant boundary | Input validation | Rate limit | Notes |
|---|---|---|---|---|---|
| `POST /auth/register` | No | N/A | EmailStr, password 8–128 | No | Registration abuse/credential stuffing protection absent |
| `POST /auth/login` | No | N/A | EmailStr; password unbounded schema | No | Brute-force protection absent |
| `GET /auth/me` | Yes | User loaded from JWT subject | JWT UUID + active check | No | |
| `POST /chat/completions` | Yes | Device selection is owner-scoped; no arbitrary device ID from model | Pydantic request; message 1–8000 | No | Expensive LLM call path |
| `POST /chat/documents/completions` | Yes | No tenant resource lookup | Extension allowlist, 8 MiB file cap, 4,000-char instruction cap, extraction cap | No | Explicit untrusted-document boundary; reverse-proxy body cap still needed |
| `GET /conversations` | Yes | Owner-scoped | Query-free | No | |
| `POST /conversations` | Yes | Owner derived from JWT | Pydantic schema | No | |
| `GET /conversations/{id}` | Yes | Owner-scoped in conversation lookup | UUID path | No | |
| `GET /conversations/{id}/messages` | Yes | Parent conversation owner-scoped | UUID path | No | |
| `POST /conversations/{id}/messages` | Yes | Parent conversation owner-scoped | Message schema | No | |
| `PATCH /conversations/{id}` | Yes | Owner-scoped | UUID + schema | No | |
| `DELETE /conversations/{id}` | Yes | Owner-scoped | UUID path | No | |
| `GET /devices`, `POST /devices` | Yes | List/create scoped; referenced credential checked against owner | Pydantic schemas | No | |
| `GET/PATCH/DELETE /devices/{id}` | Yes | Device query includes owner_id; patched credential checked against owner | UUID + schema | No | |
| `GET/POST /credentials` | Yes | List/create scoped; encryption before persistence | Pydantic schemas | No | |
| `GET/DELETE /credentials/{id}` | Yes | Credential query includes owner_id | UUID path | No | |
| `GET /audit-logs` | Yes | Filtered by current user_id | No user-controlled filter | No | |
| `GET /tools/list` | Yes | User auth; static allowlist | No body | No | |
| `POST /tools/execute` | Yes | Tool Manager resolves device context; needs regression coverage per tool | ToolRequest schema, allowlist and permission checks in manager | No | Expensive/device action endpoint |
| `POST /configurations` | Yes | Device query includes owner_id | ChangeSet schema + semantic policy validation | No | Raw adapter exception appears in log/response path |
| `GET /configurations` | Yes | owner_id filter | No body | No | |
| `GET /configurations/{id}` | Yes | Configuration query includes owner_id; subsequent Device lookup is by id only after owned config | UUID | No | Follow-up lookup should retain owner predicate as defense in depth |
| `POST /configurations/{id}/approve` | Yes | Orchestrator ownership must be regression-tested | UUID + state machine | No | |
| `POST /configurations/{id}/apply` | Yes | Orchestrator ownership must be regression-tested | UUID + state machine | No | High-impact network operation |
| `POST /configurations/{id}/rollback` | Yes | Orchestrator ownership must be regression-tested | UUID + state machine | No | High-impact network operation |
| `GET /devices/{id}/monitoring` | Yes | Device query includes owner_id and platform | UUID | No | Monitoring fan-out can exhaust thread resources |
| `GET /devices/{id}/monitoring/history` | Yes | Device query includes owner_id; samples are associated through owned device | UUID + query validation | No | |
| `GET /network/topology` | Yes | Must verify all related Agent/Device/target queries are owner-scoped in implementation tests | No body | No | |
| `POST /network/devices/{id}/refresh` | Yes | Device owner-scoped per Phase 6 implementation; verify actual query | UUID | Existing 5-second throttle documented | |
| `GET/POST /network/manual-topology` resources | Yes | Must verify node/link parent and device ownership on every mutation | UUID + Pydantic schemas | No | Review individual queries and foreign-key ownership |
| `PATCH/DELETE /network/manual-topology/nodes/{id}` | Yes | Must verify owner-scoped node lookup | UUID + schema | No | |
| `POST/DELETE /network/manual-topology/links/{id}` | Yes | Must verify both endpoint nodes share owner | UUID + schema | No | |
| `GET/POST /agents` | Yes for REST | List/create scoped to owner | Pydantic schemas | No | Token plaintext only create/rotate |
| `GET /agents/{id}` | Yes | `_get_owned_agent` | UUID | No | |
| `POST /agents/{id}/rotate-token` | Yes | `_get_owned_agent` with row lock | UUID | No | |
| `POST /agents/{id}/disconnect` | Yes | `_get_owned_agent` with row lock | UUID | No | |
| `DELETE /agents/{id}` | Yes | `_get_owned_agent` with row lock | UUID | No | |
| `WS /ws/agent/{agent_id}` | Agent token, not user JWT | Agent ID resolved through DB; token hash verification and connection claim | UUID parse + protocol parser + max frame | Agent per-process IP/message limiter | TLS default enforced in production by wiring, but no startup fail-closed assertion |
| `POST/GET /agents/{id}/targets` | Yes | Agent owner-scoped; device owner checked on create | Pydantic schema | No | Target host/port policy needs regression tests |
| `PATCH /agents/{id}/targets/{target_id}` | Yes | Agent + target owner-scoped | Fingerprint schema | No | No explicit confirmation challenge |
| `DELETE /agents/{id}/targets/{target_id}` | Yes | Agent + target owner-scoped | UUID paths | No | |
| `WS /agent/ws` (legacy) | Static Agent token in first frame | Token map only; no user tenant principal | JSON type/UUID/token checks | No explicit limiter | Separate legacy protocol and process-local registry |
| `POST /mikrotik-config-generator/generate` | Router-level auth must be verified | No tenant resource lookup expected | Pydantic generator schema | No | Offline artifact generation |
| `POST /linux-config-generator/generate` and legacy Linux generator routes | Router-level auth must be verified | No tenant resource lookup expected | Pydantic generator schema | No | Offline artifact generation |
| `POST /images/generate` | Router-level auth must be verified | User auth expected; no device ownership | Prompt/schema validation must be checked | No | External provider cost-abuse risk |
| `GET /health` | No | N/A | No input | No | Public health endpoint returns service/environment |

### Tenant-isolation observations

Positive evidence:
- Device, credential, audit-log, Agent, relay-target, and configuration primary lookups generally include owner identity.
- `POST /devices` and `PATCH /devices/{id}` verify referenced credential ownership.
- `POST /agents/{id}/targets` checks Agent ownership and referenced Device ownership.
- Remote relay resolution filters both `device_id` and `owner_id`; relay never silently falls back to direct connection once a target is selected.

Follow-up requirements:
- Add parameterized two-user tests for every resource endpoint, especially topology nodes/links, metric history, configuration state transitions, and relay target pin changes.
- Add owner predicate to the secondary Device lookup in `GET /configurations/{id}` even though the parent Configuration is already owner-scoped.
- Audit all network topology joins and metric-sample queries at SQL level; this static pass did not prove every join is tenant-constrained.

## Specific control review

### Startup and environment

- `Settings` currently has no production validator for JWT secret entropy/length, Agent TLS, CORS, or SSH host-key policy.
- `agent_require_tls=None` resolves to true in production in `build_runtime_config()`, but there is no explicit refusal when an override disables it.
- CORS in `main.py` is hardcoded to two localhost origins.
- SQLAlchemy engine uses `pool_pre_ping=True` only; pool sizing/timeouts are implicit defaults.
- No explicit global body-size middleware was found in `main.py`.

### TLS / SSH

- Relay TLS uses `CERT_NONE` only as the certificate-chain mechanism, then compares SHA-256 DER fingerprint before application bytes. This path is pinned and fail-closed.
- Direct local API-SSL in `mikrotik.py::_connect` sets `CERT_NONE` and has no pin. Production must reject this unless a device pin or explicit audited opt-in exists.
- SSH host-key checking defaults false and known_hosts path defaults null. Production must require strict host key verification.
- Pin mismatch includes an observed fingerprint in `RelayTlsError.observed`; it must remain an operator-only field and never enter LLM context or generic API errors.

### Secret hygiene and error handling

- Credential encryption uses AES-GCM and owner/credential AAD; credential API response schemas should be checked to ensure encrypted ciphertext, nonce, and key IDs are not exposed.
- Sanitizer redacts sensitive metadata keys, JWT-like values, private keys, and DB URLs, but arbitrary password/fingerprint text embedded in exception messages is not comprehensively removed.
- `mikrotik.py::_connection_error_message` includes raw exception text.
- `configurations.py` logs raw adapter exceptions and returns exception text in some 502/400 paths.
- `chat.py` forwards OpenRouter exception text in 502 details.
- Monitoring endpoint exception paths require a complete pass; any raw `{exc}` detail must be replaced with a stable public error code/message and a sanitized internal log.
- Full certificate fingerprints must not be logged or sent to an LLM. Store only the pin in protected DB fields and show it only to authorized operators when needed.

### Prompt injection and tool execution

- Uploaded document analysis explicitly marks extracted content as untrusted data and instructs the model not to follow embedded instructions.
- Device-derived strings (identity, interface comments, neighbor identity, DHCP hostnames, ARP/bridge data, logs) are untrusted observations. They must be serialized as bounded data and never interpolated as system/developer instructions.
- LLM tool calls must continue through Tool Manager validation, allowlist, permission/risk checks, user/device ownership resolution, confirmation, timeout, audit, and post-check. Model output must never supply a raw destination host or credential.

### Frontend token handling

- `frontend/lib/auth.ts` stores the access JWT in localStorage; all API requests read it and attach it as Bearer.
- This is vulnerable to token theft if arbitrary JavaScript executes in the origin. A production migration to HttpOnly, Secure, SameSite cookies plus CSRF protection is recommended. Do not switch auth transport without updating backend CORS/CSRF and frontend session flows together.

### Headers and request limits

Required before production:
- `X-Content-Type-Options: nosniff`
- CSP with at least `frame-ancestors 'none'` (or a narrowly defined trusted embedding policy); `X-Frame-Options: DENY` as legacy fallback
- `Referrer-Policy: strict-origin-when-cross-origin`
- Explicit maximum body size at reverse proxy and/or ASGI layer; document a separate larger limit for document upload if needed.
- WebSocket origin policy for browser-facing sockets. Agent WSS should authenticate the Agent token and require TLS; do not use browser Origin as the sole Agent authentication control.

## Dependency audit status

| Tool | Status | Result |
|---|---|---|
| `pip-audit` | Not run | Requires dependency installation and network vulnerability database access |
| `npm audit` | Not run | Requires npm registry access |
| `pytest` | Not run | No repository checkout/runtime dependencies available in this audit environment |
| Frontend build/lint | Not run | No local checkout/runtime dependencies available |

No dependency vulnerability result is claimed.

## Required Phase 8.1 remediation order

1. Add production startup validators and production CORS configuration.
2. Require SSH host-key verification in production.
3. Block direct API-SSL without pin in production, with development compatibility preserved.
4. Add explicit confirmation + audit semantics for pin replacement; ensure mismatch never auto-accepts.
5. Add bounded HTTP rate limiting for auth, chat, tool execution, and monitoring. Document per-process limitation until shared storage is approved.
6. Sanitize public error responses and logs at exception boundaries.
7. Add security headers and body-size enforcement.
8. Add tenant-isolation regression matrix and production configuration tests.
9. Run `pip-audit`, `npm audit`, and full tests in a network-enabled checkout.

## Deployment note

Until SEC-01 through SEC-07 are fixed and regression-tested, do not expose this branch as a public multi-tenant service. The current audit is a static baseline and does not certify a VPS deployment.
