from __future__ import annotations
import asyncio, json, logging, random
from websockets.asyncio.client import connect
from .config import AgentConfig

log = logging.getLogger("nova_agent")

class AgentClient:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.stop_event = asyncio.Event()

    def stop(self):
        self.stop_event.set()

    async def run(self):
        delay = 2
        while not self.stop_event.is_set():
            try:
                await self._session()
                delay = 2
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("Cloud connection failed (%s); reconnecting.", type(exc).__name__)
            if self.stop_event.is_set():
                break
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=delay + random.uniform(0, min(3, delay / 4)))
            except asyncio.TimeoutError:
                pass
            delay = min(delay * 2, 60)

    async def _session(self):
        log.info("Connecting to NOVA Cloud")
        async with connect(self.config.websocket_url, open_timeout=15, close_timeout=5,
                           ping_interval=20, ping_timeout=20, max_size=65536) as ws:
            await ws.send(json.dumps({"type":"authenticate","agent_id":self.config.agent_id,"token":self.config.token}))
            auth = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            if auth.get("type") != "authenticated":
                raise RuntimeError("Agent authentication rejected")
            log.info("Agent authenticated; heartbeat active")
            interval = max(10, int(auth.get("heartbeat_interval_seconds", self.config.heartbeat_interval_seconds)))
            while not self.stop_event.is_set():
                await ws.send(json.dumps({"type":"heartbeat","agent_id":self.config.agent_id}))
                ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=interval))
                if ack.get("type") != "heartbeat_ack":
                    raise RuntimeError("Unexpected gateway response")
                try:
                    await asyncio.wait_for(self.stop_event.wait(), timeout=max(5, interval - 1))
                except asyncio.TimeoutError:
                    pass
