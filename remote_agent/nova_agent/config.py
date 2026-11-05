from __future__ import annotations
import json, os, uuid
from dataclasses import dataclass
from pathlib import Path

def config_path() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "NOVA" / "Agent" / "config.json"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "nova-agent" / "config.json"

@dataclass(frozen=True)
class AgentConfig:
    agent_id: str
    token: str
    server_url: str
    heartbeat_interval_seconds: int = 30

    @classmethod
    def load(cls) -> "AgentConfig":
        path = config_path()
        data = json.loads(path.read_text(encoding="utf-8"))
        agent_id = str(uuid.UUID(data["agent_id"]))
        token, url = data["token"], data["server_url"].rstrip("/")
        if not isinstance(token, str) or len(token) < 32:
            raise ValueError("Agent token must be at least 32 characters.")
        if not url.startswith("https://"):
            if not (url.startswith("http://") and os.getenv("NOVA_AGENT_ALLOW_INSECURE") == "1"):
                raise ValueError("HTTPS/WSS is required. HTTP is development-only.")
        return cls(agent_id, token, url, max(10, int(data.get("heartbeat_interval_seconds", 30))))

    @property
    def websocket_url(self) -> str:
        scheme = "wss" if self.server_url.startswith("https://") else "ws"
        return scheme + "://" + self.server_url.split("://", 1)[1] + "/agent/ws"
