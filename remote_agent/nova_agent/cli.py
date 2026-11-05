"""nova-agent command line.

    init               write the config file (token is never echoed or logged)
    run                foreground, with console logging; Ctrl+C = graceful stop
    install-service / uninstall-service / start / stop / restart / status
                       Windows Service management (run as Administrator)
"""

from __future__ import annotations

import argparse
import getpass
import sys

from . import __version__, service_control
from .config import AgentConfig, ConfigError, save_config, validate_server_url

EXIT_USAGE = 2


def _is_windows() -> bool:
    return sys.platform == "win32"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nova-agent", description="NOVA Remote Agent")
    p.add_argument("--version", action="version", version=f"nova-agent {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create or overwrite the agent configuration")
    init.add_argument("--server-url", required=True, help="base URL of the NOVA backend, e.g. https://nova.example.com")
    init.add_argument("--agent-id", required=True, help="agent UUID returned by POST /agents")
    group = init.add_mutually_exclusive_group()
    group.add_argument("--token-stdin", action="store_true", help="read the token from one line of stdin")
    group.add_argument("--token", help="INSECURE: visible in process lists and shell history; prefer the hidden prompt")
    init.add_argument("--allow-insecure", action="store_true",
                      help="development only: permit http:// / ws:// (no TLS)")

    sub.add_parser("run", help="run in the foreground")
    for name, text in (
        ("install-service", "install the Windows Service (auto-start)"),
        ("uninstall-service", "remove the Windows Service"),
        ("start", "start the service"),
        ("stop", "stop the service"),
        ("restart", "stop, then start the service"),
        ("status", "show the service state"),
    ):
        sub.add_parser(name, help=text)
    return p


def _read_token(args: argparse.Namespace) -> str:
    if args.token_stdin:
        return sys.stdin.readline().strip()
    if args.token:
        print("warning: --token exposes the secret to other local users; "
              "prefer the hidden prompt or --token-stdin.", file=sys.stderr)
        return args.token.strip()
    return getpass.getpass("Agent token (input hidden): ").strip()


def _cmd_init(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    token = _read_token(args)
    try:
        # Validate the URL first so a typo does not leave a half-written config.
        validate_server_url(args.server_url, allow_insecure=args.allow_insecure)
        config = AgentConfig.create(args.agent_id, token, args.server_url, args.allow_insecure)
        path = save_config(config)
    except ConfigError as exc:
        parser.error(str(exc))  # exits with status 2; message never contains the token
    print(f"Configuration saved: {path}")
    print(f"Agent ID: {config.agent_id}")
    print(f"Endpoint: {config.websocket_url}")
    return 0


def _cmd_run() -> int:
    from .logging_setup import setup_logging
    from .runner import run_blocking

    setup_logging(console=True)
    reason = run_blocking(AgentConfig.load, handle_signals=True)
    if reason.exit_code:
        print(f"Agent exited: {reason.name}. See the log for details.", file=sys.stderr)
    return reason.exit_code


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "init":
        return _cmd_init(args, parser)
    if args.command == "run":
        return _cmd_run()

    if not _is_windows():
        parser.error("Windows service commands are only supported on Windows")
    actions = {
        "install-service": service_control.install,
        "uninstall-service": service_control.remove,
        "start": service_control.start,
        "stop": service_control.stop,
        "restart": service_control.restart,
        "status": service_control.status,
    }
    try:
        return actions[args.command]()
    except RuntimeError as exc:  # e.g. pywin32 missing
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
