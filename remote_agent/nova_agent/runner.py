"""Blocking entry point shared by the CLI (foreground) and the Windows Service.

Owns the event loop lifecycle: create loop -> run client -> cancel leftovers ->
shut down async generators and the default executor -> close. Leaves nothing
running when it returns."""

from __future__ import annotations

import asyncio
import logging
import signal
import threading
from typing import Callable

from .client import AgentClient, ExitReason
from .config import AgentConfig, ConfigError
from .logging_setup import register_secret
from .transport import require_websockets

log = logging.getLogger("nova_agent")


class StopHandle:
    """Thread-safe bridge: SvcStop / signal handlers -> client.request_stop()."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client: AgentClient | None = None
        self._requested = False

    @property
    def requested(self) -> bool:
        return self._requested

    def attach(self, loop: asyncio.AbstractEventLoop, client: AgentClient) -> None:
        with self._lock:
            self._loop, self._client = loop, client
            if self._requested:
                loop.call_soon_threadsafe(client.request_stop)

    def detach(self) -> None:
        with self._lock:
            self._loop = self._client = None

    def request_stop(self) -> None:
        with self._lock:
            self._requested = True
            loop, client = self._loop, self._client
            if loop is not None and client is not None and not loop.is_closed():
                try:
                    loop.call_soon_threadsafe(client.request_stop)
                except RuntimeError:  # loop closed in between
                    pass


def shutdown_loop(loop: asyncio.AbstractEventLoop) -> None:
    pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
    for task in pending:
        task.cancel()
    if pending:
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    loop.run_until_complete(loop.shutdown_asyncgens())
    loop.run_until_complete(loop.shutdown_default_executor())
    loop.close()
    asyncio.set_event_loop(None)


def _install_signal_handlers(handle: StopHandle) -> None:
    def _handler(signum, _frame) -> None:
        log.info("Signal %s received; stopping", signum)
        handle.request_stop()

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, _handler)
            except (ValueError, OSError):  # not main thread / unsupported
                pass


def run_blocking(
    load_config: Callable[[], AgentConfig] = AgentConfig.load,
    handle: StopHandle | None = None,
    *,
    handle_signals: bool = False,
    client_factory: Callable[[AgentConfig], AgentClient] = AgentClient,
    require_transport: bool = True,
) -> ExitReason:
    handle = handle or StopHandle()
    try:
        config = load_config()
    except ConfigError as exc:
        log.error("Configuration error: %s", exc)
        return ExitReason.CONFIG_ERROR
    register_secret(config.token)
    if require_transport:
        try:
            require_websockets()
        except RuntimeError as exc:
            log.error("%s", exc)
            return ExitReason.INTERNAL_ERROR

    if handle_signals:
        _install_signal_handlers(handle)

    loop = asyncio.new_event_loop()
    reason = ExitReason.INTERNAL_ERROR
    try:
        asyncio.set_event_loop(loop)
        client = client_factory(config)
        handle.attach(loop, client)
        try:
            reason = loop.run_until_complete(client.run())
        except KeyboardInterrupt:
            # Without signal handlers: the cancel in shutdown_loop() runs the
            # session teardown (bye + close) before the loop is closed.
            handle.request_stop()
            reason = ExitReason.STOPPED
        except Exception:  # noqa: BLE001
            log.exception("NOVA Remote Agent crashed")
            reason = ExitReason.INTERNAL_ERROR
    finally:
        handle.detach()
        try:
            shutdown_loop(loop)
        except Exception:  # noqa: BLE001
            log.exception("Event loop shutdown failed")
    return reason
