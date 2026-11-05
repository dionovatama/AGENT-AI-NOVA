import logging, os
from logging.handlers import RotatingFileHandler
from pathlib import Path

def setup_logging():
    if os.name == "nt":
        root = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "NOVA" / "Agent" / "logs"
    else:
        root = Path.home() / ".local" / "state" / "nova-agent"
    root.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(root / "agent.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=[handler])
