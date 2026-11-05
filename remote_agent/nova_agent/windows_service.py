"""Windows Service host (pywin32). Imported only on Windows.

SvcDoRun runs the agent through ``runner.run_blocking`` (the same code path as
``nova-agent run``); SvcStop only flips a thread-safe StopHandle, so the agent
sends ``bye``, closes the socket and tears the event loop down before the
service reports STOPPED. Lost internet never ends the service: the client
retries forever with backoff. Only a deliberate stop or an unrecoverable
credential problem (4401, repeated 4009/4400, bad config) ends it, and those
are logged and reported with a non-zero service exit code.
"""

from __future__ import annotations

import logging

import servicemanager
import win32service
import win32serviceutil
import winerror

from .client import ExitReason
from .config import AgentConfig
from .logging_setup import setup_logging
from .runner import StopHandle, run_blocking


class NovaAgentService(win32serviceutil.ServiceFramework):
    _svc_name_ = "NOVARemoteAgent"
    _svc_display_name_ = "NOVA Remote Agent"
    _svc_description_ = "Secure outbound connection from NOVA Cloud to the local network gateway."

    def __init__(self, args):
        super().__init__(args)
        self._handle = StopHandle()

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING, waitHint=20000)
        self._handle.request_stop()

    def SvcDoRun(self):
        setup_logging()
        log = logging.getLogger("nova_agent.service")
        servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE,
                              servicemanager.PYS_SERVICE_STARTED, (self._svc_name_, ""))
        reason = ExitReason.INTERNAL_ERROR
        try:
            reason = run_blocking(AgentConfig.load, self._handle, handle_signals=False)
        except Exception:  # noqa: BLE001
            log.exception("NOVA Remote Agent service failed")
        finally:
            servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE,
                                  servicemanager.PYS_SERVICE_STOPPED, (self._svc_name_, ""))
        if reason is not ExitReason.STOPPED:
            log.error("Service exiting: %s", reason.name)
            self.ReportServiceStatus(
                win32service.SERVICE_STOPPED,
                win32ExitCode=winerror.ERROR_SERVICE_SPECIFIC_ERROR,
                svcExitCode=reason.exit_code,
            )
