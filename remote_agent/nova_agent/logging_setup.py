"""Logging with defense-in-depth token redaction."""

from __future__ import annotations

import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_TOKEN_RE = re.compile(r"nova_agt_[A-Za-z0-9_-]{6,}")
_secrets: set[str] = set()
_HANDLER_TAG = "_nova_agent_handler"


def register_secret(value: str) -> None:
    """Make the formatter replace this exact value wherever it shows up."""
    if isinstance(value, str) and len(value) >= 8:
        _secrets.add(value)


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)  # includes exception tracebacks
        for secret in _secrets:
            text = text.replace(secret, "***")
        return _TOKEN_RE.sub("nova_agt_***", text)


def log_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "NOVA" / "Agent" / "logs"
    return Path.home() / ".local" / "state" / "nova-agent"


def setup_logging(console: bool = False) -> None:
    """Idempotent. File logging always; a console stream for foreground runs.
    If the log directory is not writable the agent still logs to stderr
    instead of failing to start."""
    level_name = os.environ.get("NOVA_AGENT_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, _HANDLER_TAG, False)]:
        root.removeHandler(handler)
        handler.close()

    formatter = RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handlers: list[logging.Handler] = []
    try:
        directory = log_dir()
        directory.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(
            directory / "agent.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"))
    except OSError:
        console = True
    if console:
        handlers.append(logging.StreamHandler(sys.stderr))

    for handler in handlers:
        handler.setFormatter(formatter)
        setattr(handler, _HANDLER_TAG, True)
        root.addHandler(handler)
    root.setLevel(level)
    logging.getLogger("websockets").setLevel(logging.WARNING)
