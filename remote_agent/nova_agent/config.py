"""Agent configuration: loading, validation, secure persistence.

Config file: ``%ProgramData%\\NOVA\\Agent\\config.json`` (Windows) or
``$XDG_CONFIG_HOME/nova-agent/config.json``.

File format (unchanged from the legacy agent so existing files still load):
    {"server_url": "https://host", "agent_id": "<uuid v4>", "token": "nova_agt_..."}
Optional: ``"allow_insecure": true`` (development only). The legacy key
``heartbeat_interval_seconds`` is accepted and ignored: since protocol v1 the
server dictates the heartbeat interval in its ``registered`` message.

Nothing in this module puts the token into an exception message, ``repr`` or
log line.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .protocol import parse_agent_id

ALLOW_INSECURE_ENV = "NOVA_AGENT_ALLOW_INSECURE"
MAX_CONFIG_BYTES = 64 * 1024

_TOKEN_RE = re.compile(r"^nova_agt_[A-Za-z0-9_-]{43}$")  # backend app/agents/tokens.py
_LEGACY_HINT = (
    "Agents created before the Phase A protocol used a static token and are not "
    "accepted any more. Create a new agent with POST /agents and run "
    "`nova-agent init` again."
)


class ConfigError(ValueError):
    """Invalid or unreadable configuration. Never contains the token."""


def config_path() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "NOVA" / "Agent" / "config.json"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "nova-agent" / "config.json"


# ---------------------------------------------------------------------------
# Field validators
# ---------------------------------------------------------------------------

def validate_agent_id(value: object) -> str:
    parsed = parse_agent_id(value)
    if parsed is None:
        raise ConfigError(
            "agent_id must be a UUID v4 in canonical form "
            "(xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx). " + _LEGACY_HINT
        )
    return str(parsed)


def validate_token(value: object) -> str:
    if not isinstance(value, str) or _TOKEN_RE.fullmatch(value) is None:
        raise ConfigError(
            "token is not in the NOVA agent token format (nova_agt_ + 43 characters). "
            + _LEGACY_HINT
        )
    return value


def validate_server_url(value: object, *, allow_insecure: bool = False) -> str:
    """Return the normalized base URL (https/http scheme, no trailing slash)."""
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("server_url is required")
    raw = value.strip()
    if any(ch.isspace() or not ch.isprintable() for ch in raw):
        raise ConfigError("server_url contains invalid characters")
    try:
        parts = urlsplit(raw)
        parts.port  # noqa: B018 -- raises ValueError on a bad port
    except ValueError:
        raise ConfigError("server_url is not a valid URL") from None

    scheme = parts.scheme.lower()
    if scheme not in ("https", "wss", "http", "ws"):
        raise ConfigError("server_url must start with https:// (or wss://)")
    if not parts.hostname:
        raise ConfigError("server_url has no host")
    if parts.username is not None or parts.password is not None:
        raise ConfigError("server_url must not contain credentials")
    if parts.query or parts.fragment or "?" in raw or "#" in raw:
        raise ConfigError("server_url must not contain a query string or fragment")

    path = parts.path.rstrip("/")
    if "/ws/agent" in path or path.endswith("/agent/ws"):
        raise ConfigError(
            "server_url must be the base URL of the NOVA backend, not the WebSocket endpoint"
        )

    secure = scheme in ("https", "wss")
    if not secure and not allow_insecure:
        raise ConfigError(
            "HTTPS/WSS is required. Plain HTTP/WS is for development only and needs an "
            f"explicit opt-in ('allow_insecure': true in the config, or {ALLOW_INSECURE_ENV}=1)."
        )
    return f"{'https' if secure else 'http'}://{parts.netloc}{path}"


# ---------------------------------------------------------------------------
# Config object
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AgentConfig:
    agent_id: str
    token: str = field(repr=False)
    server_url: str
    allow_insecure: bool = False

    @classmethod
    def create(cls, agent_id: object, token: object, server_url: object,
               allow_insecure: bool = False) -> "AgentConfig":
        return cls(
            agent_id=validate_agent_id(agent_id),
            token=validate_token(token),
            server_url=validate_server_url(server_url, allow_insecure=allow_insecure),
            allow_insecure=bool(allow_insecure),
        )

    @classmethod
    def from_mapping(cls, data: object, env: dict | None = None) -> "AgentConfig":
        env = os.environ if env is None else env
        if not isinstance(data, dict):
            raise ConfigError("config file must contain a JSON object")
        for key in ("agent_id", "token", "server_url"):
            if key not in data:
                raise ConfigError(f"config is missing '{key}'")
        opt_in = data.get("allow_insecure") is True or env.get(ALLOW_INSECURE_ENV) == "1"
        return cls.create(data["agent_id"], data["token"], data["server_url"], opt_in)

    @classmethod
    def load(cls, path: Path | None = None) -> "AgentConfig":
        path = path or config_path()
        try:
            if path.stat().st_size > MAX_CONFIG_BYTES:
                raise ConfigError("config file is unexpectedly large")
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise ConfigError(f"config not found at {path}; run `nova-agent init`") from None
        except OSError as exc:
            raise ConfigError(f"cannot read config at {path}: {type(exc).__name__}") from None
        try:
            data = json.loads(raw)
        except ValueError:
            raise ConfigError(f"config at {path} is not valid JSON") from None
        return cls.from_mapping(data)

    @property
    def is_insecure(self) -> bool:
        return self.server_url.startswith("http://")

    @property
    def websocket_url(self) -> str:
        """``wss://host[/prefix]/ws/agent/<agent_id>`` -- no token, no query."""
        scheme, rest = self.server_url.split("://", 1)
        return f"{'wss' if scheme == 'https' else 'ws'}://{rest}/ws/agent/{self.agent_id}"


# ---------------------------------------------------------------------------
# Secure persistence
# ---------------------------------------------------------------------------

_WIN_ACL = ["/inheritance:r", "/grant:r", "*S-1-5-18:F", "*S-1-5-32-544:F"]  # SYSTEM, Administrators


def _restrict_windows(path: Path) -> None:
    try:
        subprocess.run(["icacls", str(path), *_WIN_ACL], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        raise ConfigError("could not restrict config file permissions (icacls failed)") from None


def save_config(config: AgentConfig, path: Path | None = None) -> Path:
    """Write the config with owner-only permissions *before* the token is
    written (no window with inherited, world-readable ACLs), then atomically
    replace the target."""
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "server_url": config.server_url,
        "agent_id": config.agent_id,
        "token": config.token,
    }
    if config.allow_insecure:
        payload["allow_insecure"] = True
    data = json.dumps(payload, indent=2).encode("utf-8")

    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = os.open(tmp, flags, 0o600)
    try:
        if os.name == "nt":
            os.close(fd)
            fd = -1
            _restrict_windows(tmp)  # empty file: nothing secret exposed yet
            with open(tmp, "wb") as handle:
                handle.write(data)
        else:
            with os.fdopen(fd, "wb") as handle:
                fd = -1
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        os.replace(tmp, path)
        if os.name == "nt":
            _restrict_windows(path)
        else:
            path.chmod(0o600)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return path
