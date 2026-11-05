import asyncio
import io
import json
import logging
import os
import stat
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from nova_agent import cli, client as client_mod
from nova_agent.client import AgentClient, ExitReason
from nova_agent.config import AgentConfig, ConfigError
from nova_agent.logging_setup import RedactingFormatter, register_secret
from nova_agent.runner import StopHandle, run_blocking
from tests.helpers import AGENT_ID, TOKEN, FakeConnector, FakeTransport, backend, make_config


class RunnerTests(unittest.TestCase):
    def test_config_error_returns_config_exit(self):
        def bad():
            raise ConfigError("nope")
        self.assertEqual(run_blocking(bad, require_transport=False), ExitReason.CONFIG_ERROR)

    def _factory(self, connector):
        return lambda cfg: AgentClient(cfg, connector=connector, rng=lambda: 0.0,
                                       min_heartbeat_interval=0.01)

    def test_stop_requested_from_another_thread_shuts_down_cleanly(self):
        transport = FakeTransport(on_send=backend())
        handle = StopHandle()
        result = {}

        def target():
            result["reason"] = run_blocking(
                make_config, handle, client_factory=self._factory(FakeConnector([transport])),
                require_transport=False)

        thread = threading.Thread(target=target)
        thread.start()
        deadline = 50
        while len([m for m in transport.sent if m["type"] == "heartbeat"]) < 2 and deadline:
            threading.Event().wait(0.05)
            deadline -= 1
        handle.request_stop()  # what SvcStop does (different thread)
        thread.join(5)
        self.assertFalse(thread.is_alive(), "agent thread did not stop")
        self.assertEqual(result["reason"], ExitReason.STOPPED)
        self.assertEqual(transport.sent[-1], {"type": "bye"})
        self.assertEqual(transport.closed_with[0], 1000)

    def test_stop_before_loop_exists_is_not_lost(self):
        handle = StopHandle()
        handle.request_stop()  # SvcStop arrived before SvcDoRun built the loop
        gate_connector = FakeConnector([FakeTransport()])
        reason = run_blocking(make_config, handle, client_factory=self._factory(gate_connector),
                              require_transport=False)
        self.assertEqual(reason, ExitReason.STOPPED)

    def test_fatal_auth_failure_exit_code(self):
        def on_send(tr, msg):
            tr.server_close(4401)
        conn = FakeConnector([FakeTransport(on_send=on_send)])
        reason = run_blocking(make_config, client_factory=self._factory(conn), require_transport=False)
        self.assertEqual(reason, ExitReason.AUTH_FAILED)
        self.assertNotEqual(reason.exit_code, 0)

    def test_event_loop_is_closed_and_no_tasks_left(self):
        loops = []
        real_new = asyncio.new_event_loop

        def spy():
            loop = real_new()
            loops.append(loop)
            return loop

        handle = StopHandle()
        handle.request_stop()
        with mock.patch("nova_agent.runner.asyncio.new_event_loop", spy):
            run_blocking(make_config, handle, client_factory=self._factory(FakeConnector([])),
                         require_transport=False)
        self.assertTrue(loops and all(l.is_closed() for l in loops))


class LoggingTests(unittest.TestCase):
    def test_formatter_redacts_registered_secrets_and_token_shaped_strings(self):
        register_secret("legacy-secret-value-123")
        unregistered = "nova_agt_" + "Z" * 43  # never registered: caught by the pattern
        fmt = RedactingFormatter("%(message)s")
        try:
            raise RuntimeError(f"failed with {TOKEN} and {unregistered}")
        except RuntimeError:
            rec = logging.LogRecord("t", logging.ERROR, __file__, 1,
                                    "token=%s legacy-secret-value-123 %s", (TOKEN, unregistered),
                                    sys.exc_info())
        text = fmt.format(rec)
        for secret in (TOKEN, unregistered, "legacy-secret-value-123"):
            self.assertNotIn(secret, text)
        self.assertIn("nova_agt_***", text)  # pattern path
        self.assertIn("Traceback", text)     # tracebacks are redacted too, not dropped


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp.name}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        self.cfg = Path(self.tmp.name) / "nova-agent" / "config.json"

    def invoke(self, argv, stdin=""):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), mock.patch("sys.stdin", io.StringIO(stdin)):
            try:
                code = cli.main(argv)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def init_args(self, *extra):
        return ["init", "--server-url", "https://nova.example.com", "--agent-id", AGENT_ID, *extra]

    def test_init_from_stdin_writes_config_and_never_prints_token(self):
        code, out, err = self.invoke(self.init_args("--token-stdin"), stdin=TOKEN + "\n")
        self.assertEqual(code, 0)
        self.assertNotIn(TOKEN, out + err)
        data = json.loads(self.cfg.read_text())
        self.assertEqual(data["token"], TOKEN)
        self.assertEqual(data["agent_id"], AGENT_ID)
        self.assertIn(f"/ws/agent/{AGENT_ID}", out)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(self.cfg.stat().st_mode), 0o600)
        AgentConfig.load(self.cfg)  # and it is loadable

    def test_init_rejects_bad_input_without_echoing_it(self):
        bad_token = "short-token"
        code, out, err = self.invoke(self.init_args("--token-stdin"), stdin=bad_token)
        self.assertEqual(code, 2)
        self.assertNotIn(bad_token, out + err)
        self.assertFalse(self.cfg.exists())
        code, _, _ = self.invoke(["init", "--server-url", "https://x.example", "--agent-id", "nope",
                                  "--token-stdin"], stdin=TOKEN)
        self.assertEqual(code, 2)
        code, _, err = self.invoke(["init", "--server-url", "http://x.example", "--agent-id", AGENT_ID,
                                    "--token-stdin"], stdin=TOKEN)
        self.assertEqual(code, 2)
        self.assertNotIn(TOKEN, err)
        self.assertFalse(self.cfg.exists())

    def test_token_flag_warns_but_still_never_prints_token(self):
        code, out, err = self.invoke(self.init_args("--token", TOKEN))
        self.assertEqual(code, 0)
        self.assertIn("warning", err)
        self.assertNotIn(TOKEN, out + err)

    def test_insecure_init_requires_flag_and_is_persisted(self):
        argv = ["init", "--server-url", "http://localhost:8000", "--agent-id", AGENT_ID, "--token-stdin"]
        code, _, _ = self.invoke(argv + ["--allow-insecure"], stdin=TOKEN)
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(self.cfg.read_text())["allow_insecure"])
        self.assertEqual(AgentConfig.load(self.cfg).websocket_url, f"ws://localhost:8000/ws/agent/{AGENT_ID}")

    def test_service_commands_rejected_off_windows(self):
        for cmd in ("install-service", "uninstall-service", "start", "stop", "restart", "status"):
            with self.subTest(cmd=cmd), mock.patch.object(cli, "_is_windows", return_value=False):
                code, _, err = self.invoke([cmd])
                self.assertEqual(code, 2)
                self.assertIn("only supported on Windows", err)

    def test_service_commands_dispatch_including_restart(self):
        names = {"install-service": "install", "uninstall-service": "remove", "start": "start",
                 "stop": "stop", "restart": "restart", "status": "status"}
        for cmd, func in names.items():
            with self.subTest(cmd=cmd), mock.patch.object(cli, "_is_windows", return_value=True), \
                    mock.patch.object(cli.service_control, func, return_value=0) as target:
                code, _, _ = self.invoke([cmd])
                self.assertEqual(code, 0)
                target.assert_called_once()

    def test_run_without_config_fails_cleanly(self):
        with mock.patch("nova_agent.logging_setup.log_dir", return_value=Path(self.tmp.name) / "logs"):
            code, _, err = self.invoke(["run"])
        self.assertEqual(code, ExitReason.CONFIG_ERROR.exit_code)


if __name__ == "__main__":
    unittest.main()
