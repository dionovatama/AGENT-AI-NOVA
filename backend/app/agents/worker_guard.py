"""Fail-fast guard for process-local Remote Agent relay state."""
from __future__ import annotations

import os
import re
import shlex
import sys
from collections.abc import Mapping, Sequence


def _read_worker_flag(args: Sequence[str]) -> int | None:
    for index, item in enumerate(args):
        if item.startswith("--workers="):
            return int(item.split("=", 1)[1])
        if item in {"--workers", "-w"} and index + 1 < len(args):
            return int(args[index + 1])
    return None


def detect_worker_count(
    environ: Mapping[str, str] | None = None,
    argv: Sequence[str] | None = None,
) -> int:
    env = environ if environ is not None else os.environ
    cli = list(argv if argv is not None else sys.argv[1:])

    for key in ("WEB_CONCURRENCY", "UVICORN_WORKERS"):
        value = env.get(key)
        if value:
            try:
                return max(1, int(value))
            except ValueError:
                raise RuntimeError(f"{key} must be a positive integer.") from None

    gunicorn_args = shlex.split(env.get("GUNICORN_CMD_ARGS", ""))
    flag = _read_worker_flag(cli) or _read_worker_flag(gunicorn_args)
    return max(1, flag or 1)


def validate_single_worker_relay(
    environ: Mapping[str, str] | None = None,
    argv: Sequence[str] | None = None,
) -> None:
    workers = detect_worker_count(environ, argv)
    if workers > 1:
        raise RuntimeError(
            "Remote Agent relay state is process-local. Run N.O.V.A with exactly one ASGI worker "
            "(WEB_CONCURRENCY=1 / uvicorn --workers 1). Multi-worker relay is unsupported until "
            "shared broker routing is implemented."
        )
