from __future__ import annotations
import asyncio, logging, threading
import servicemanager, win32event, win32service, win32serviceutil
from .client import AgentClient
from .config import AgentConfig
from .logging_setup import setup_logging

class NovaAgentService(win32serviceutil.ServiceFramework):
    _svc_name_ = "NOVARemoteAgent"
    _svc_display_name_ = "NOVA Remote Agent"
    _svc_description_ = "Secure outbound connection from NOVA Cloud to the local network gateway."

    def __init__(self, args):
        super().__init__(args)
        self.stop_handle = win32event.CreateEvent(None, 0, 0, None)
        self.client = None
        self.loop = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_handle)
        if self.loop and self.client:
            self.loop.call_soon_threadsafe(self.client.stop)

    def SvcDoRun(self):
        setup_logging()
        servicemanager.LogInfoMsg("NOVA Remote Agent starting")
        try:
            cfg = AgentConfig.load()
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.client = AgentClient(cfg)
            self.loop.run_until_complete(self.client.run())
        except Exception:
            logging.getLogger("nova_agent").exception("NOVA Agent service failed")
            raise
        finally:
            if self.loop:
                self.loop.close()
