"""Windows Service management (install / start / stop / restart / remove / status).

No top-level pywin32 import so the CLI stays importable on any OS; every
function imports lazily. Requires an elevated (Administrator) shell.
"""

from __future__ import annotations

import subprocess

SERVICE_NAME = "NOVARemoteAgent"
_WAIT_SECONDS = 30


def _pywin32():
    try:
        import pywintypes
        import win32service
        import win32serviceutil
    except ImportError:
        raise RuntimeError(
            "pywin32 is required for Windows Service commands: pip install -e \".[windows]\""
        ) from None
    return pywintypes, win32service, win32serviceutil


def _service_class():
    from .windows_service import NovaAgentService
    return NovaAgentService


def install() -> int:
    _, _, util = _pywin32()
    # '--startup auto': start at boot (the legacy install left it on manual).
    util.HandleCommandLine(_service_class(), argv=["nova-agent", "--startup", "auto", "install"])
    # Best effort: restart the process if it crashes. A deliberate stop or a
    # fatal credential error (service reports an error exit) is NOT restarted.
    try:
        subprocess.run(
            ["sc.exe", "failure", SERVICE_NAME, "reset=", "86400",
             "actions=", "restart/60000/restart/60000"],
            check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        print("warning: could not configure service recovery actions")
    return 0


def remove() -> int:
    _, _, util = _pywin32()
    util.HandleCommandLine(_service_class(), argv=["nova-agent", "remove"])
    return 0


def _run(action) -> int:
    pywintypes, _, _ = _pywin32()
    try:
        action()
    except pywintypes.error as exc:
        print(f"error: {exc.strerror or exc} (are you running as Administrator?)")
        return 1
    return 0


def start() -> int:
    _, win32service, util = _pywin32()

    def action() -> None:
        util.StartService(SERVICE_NAME)
        util.WaitForServiceStatus(SERVICE_NAME, win32service.SERVICE_RUNNING, _WAIT_SECONDS)
        print("Service started.")
    return _run(action)


def stop() -> int:
    _, win32service, util = _pywin32()

    def action() -> None:
        util.StopService(SERVICE_NAME)
        util.WaitForServiceStatus(SERVICE_NAME, win32service.SERVICE_STOPPED, _WAIT_SECONDS)
        print("Service stopped.")
    return _run(action)


def restart() -> int:
    _, win32service, util = _pywin32()

    def action() -> None:
        util.RestartService(SERVICE_NAME, waitSeconds=_WAIT_SECONDS)
        util.WaitForServiceStatus(SERVICE_NAME, win32service.SERVICE_RUNNING, _WAIT_SECONDS)
        print("Service restarted.")
    return _run(action)


def status() -> int:
    """Query the Service Control Manager (no pywin32 needed)."""
    result = subprocess.run(["sc.exe", "query", SERVICE_NAME], text=True, capture_output=True)
    print((result.stdout or result.stderr).strip())
    return result.returncode
