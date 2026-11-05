# Phase 2 — Agent Pairing & Management UI

## Implemented

- Dashboard route: `/agent` (Remote Agents), linked from the console sidebar.
- `POST /agents`: create an agent and display the one-time token.
- `GET /agents`: list the authenticated user's agents; dashboard refreshes every 10 seconds.
- `POST /agents/{id}/rotate-token`: revoke the old token and display the new one-time token.
- `POST /agents/{id}/disconnect`: close the current WebSocket session without revoking the token.
- `DELETE /agents/{id}`: remove the agent and revoke its identity.
- Agent hostname is sent as optional protocol-v1 metadata and stored in `agents.hostname`.
  Older agents that do not send `hostname` remain compatible.

## Database migration

After deploying the code, back up PostgreSQL and run:

```bash
cd backend
alembic upgrade head
```

This applies `d4e5f6071829_add_agent_hostname.py`. The migration only adds a nullable
`agents.hostname` column; it does not modify credentials or existing Agent tokens.

## Provisioning flow

1. In NOVA, open **Remote Agents** and select **Add Agent**.
2. Name the host/site. NOVA returns the Agent ID and token once.
3. Install the `remote_agent` package on a trusted host.
4. Run the generated `nova-agent init` command. The token is entered through the
   hidden prompt on Windows, or supplied via stdin on Linux.
5. Start the Agent service/process. The dashboard will show hostname, OS, version,
   last connection, heartbeat time, and effective status.

Set `NEXT_PUBLIC_NOVA_API_BASE_URL` to the externally reachable backend base URL
(with any reverse-proxy path prefix) before building the frontend. The default
`http://localhost:8000` is suitable only for local development.

## Disconnect semantics

**Disconnect** closes the active WebSocket session. The Remote Agent is designed
to reconnect automatically, so it may return online after its reconnect delay.
To keep it offline, stop the service/process on the Agent host. To revoke its
credentials, use **Rotate** or **Delete**. This distinction is shown in the UI.

## Security properties

- REST endpoints are protected by the existing JWT dependency and owner-scoped queries.
- Token plaintext is returned only by create/rotate and is not persisted in the database.
- `token_hash` is never part of REST response schemas.
- Disconnect, rotate, and delete operations write audit events.
- The optional hostname field is printable and capped at 255 characters.
