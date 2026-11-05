# NOVA Remote Agent — Phase 1

Connectivity-only agent. It authenticates to NOVA Cloud over WSS, sends heartbeat messages, reconnects with backoff, and logs locally. It does **not** scan networks, connect to routers, execute commands, or modify configuration.

## Windows 10/11 (priority)

Run PowerShell as Administrator:

```powershell
cd remote_agent
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[windows]"
nova-agent init --server-url https://YOUR-NOVA-HOST --agent-id YOUR-AGENT-UUID
nova-agent install-service
nova-agent start
nova-agent status  # queries Windows Service Control Manager
```

Service name: `NOVARemoteAgent` (display name: NOVA Remote Agent). Config: `%ProgramData%\NOVA\Agent\config.json`. Logs: `%ProgramData%\NOVA\Agent\logs\agent.log`.

Uninstall:

```powershell
nova-agent stop
nova-agent uninstall-service
```

For foreground diagnostics use `nova-agent run`.

## Debian / Ubuntu (foreground)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install .
nova-agent init --server-url https://YOUR-NOVA-HOST --agent-id YOUR-AGENT-UUID --token YOUR-PREPROVISIONED-TOKEN
nova-agent run
```

The `init` command securely prompts for the token with hidden input; do not pass production tokens as command-line arguments.\n\n## Backend provisioning

Set the backend secret `NOVA_AGENT_TOKENS_JSON` to a JSON object mapping the exact UUID to a random token of at least 32 characters. Example shape only:

```json
{"00000000-0000-4000-8000-000000000000":"REPLACE_WITH_RANDOM_SECRET"}
```

Never commit a real token. The backend endpoint is `wss://YOUR-NOVA-HOST/agent/ws`; reverse proxy must support WebSocket upgrade and HTTPS.

Phase 1 currently uses operator-provisioned credentials. Self-service pairing, DB persistence, online status API, and remote command dispatch are Phase 2. Use one backend worker for this in-memory gateway until shared connection state is implemented.
