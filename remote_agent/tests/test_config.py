import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from nova_agent.config import (
    AgentConfig, ConfigError, save_config, validate_agent_id, validate_server_url, validate_token,
)
from tests.helpers import AGENT_ID, TOKEN


class AgentIdTests(unittest.TestCase):
    def test_valid_uuid4_is_normalized_to_lowercase(self):
        self.assertEqual(validate_agent_id(AGENT_ID.upper()), AGENT_ID)

    def test_rejects_invalid(self):
        for bad in (
            "not-a-uuid", "", None, 123,
            "{" + AGENT_ID + "}", AGENT_ID.replace("-", ""),
            "00000000-0000-1000-8000-000000000000",  # v1, backend demands v4
            AGENT_ID + " ",
        ):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                validate_agent_id(bad)


class TokenTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(validate_token(TOKEN), TOKEN)

    def test_rejects_invalid_without_leaking_value(self):
        legacy = "L" * 40  # old static token: >=32 chars but not Phase A format
        for bad in ("", "short", legacy, TOKEN + "x", TOKEN[:-1], "nova_agt_" + "!" * 43, None, 5):
            with self.subTest(bad=bad), self.assertRaises(ConfigError) as ctx:
                validate_token(bad)
            if isinstance(bad, str) and bad:
                self.assertNotIn(bad, str(ctx.exception))
        with self.assertRaises(ConfigError) as ctx:
            validate_token(legacy)
        self.assertIn("POST /agents", str(ctx.exception))  # migration hint


class ServerUrlTests(unittest.TestCase):
    def test_https_ok_and_normalized(self):
        self.assertEqual(validate_server_url("https://nova.example.com/"), "https://nova.example.com")
        self.assertEqual(validate_server_url("wss://nova.example.com:8443/api"), "https://nova.example.com:8443/api")

    def test_http_requires_opt_in(self):
        for url in ("http://localhost:8000", "ws://localhost:8000"):
            with self.subTest(url=url):
                with self.assertRaises(ConfigError):
                    validate_server_url(url)
                self.assertEqual(validate_server_url(url, allow_insecure=True), "http://localhost:8000")

    def test_rejects_bad_urls(self):
        for bad in (
            "", None, "nova.example.com", "ftp://nova.example.com", "https://",
            "https://user:pw@nova.example.com", "https://nova.example.com?token=x",
            "https://nova.example.com#frag", "https://nova.example.com:notaport",
            "https://nova.example.com/ws/agent/" + AGENT_ID, "https://nova.example.com/agent/ws",
            "https://nova .example.com",
        ):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                validate_server_url(bad)


class WebsocketUrlTests(unittest.TestCase):
    def test_phase_a_endpoint_without_token(self):
        cfg = AgentConfig.create(AGENT_ID, TOKEN, "https://nova.example.com")
        self.assertEqual(cfg.websocket_url, f"wss://nova.example.com/ws/agent/{AGENT_ID}")
        self.assertNotIn("token", cfg.websocket_url)
        self.assertNotIn(TOKEN, cfg.websocket_url)
        self.assertNotIn("?", cfg.websocket_url)

    def test_path_prefix_and_insecure_scheme(self):
        cfg = AgentConfig.create(AGENT_ID, TOKEN, "http://127.0.0.1:8000/nova", allow_insecure=True)
        self.assertEqual(cfg.websocket_url, f"ws://127.0.0.1:8000/nova/ws/agent/{AGENT_ID}")
        self.assertTrue(cfg.is_insecure)


class SecrecyTests(unittest.TestCase):
    def test_repr_and_str_hide_token(self):
        cfg = AgentConfig.create(AGENT_ID, TOKEN, "https://nova.example.com")
        self.assertNotIn(TOKEN, repr(cfg))
        self.assertNotIn(TOKEN, str(cfg))


class LoadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "nova" / "config.json"

    def _write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")

    def test_roundtrip_via_save_config(self):
        cfg = AgentConfig.create(AGENT_ID, TOKEN, "https://nova.example.com")
        save_config(cfg, self.path)
        self.assertEqual(AgentConfig.load(self.path), cfg)

    @unittest.skipIf(os.name == "nt", "POSIX permission bits")
    def test_saved_file_is_owner_only_and_no_temp_left(self):
        save_config(AgentConfig.create(AGENT_ID, TOKEN, "https://nova.example.com"), self.path)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["config.json"])

    def test_existing_config_with_legacy_keys_still_loads_if_token_is_new(self):
        self._write({"server_url": "https://nova.example.com/", "agent_id": AGENT_ID,
                     "token": TOKEN, "heartbeat_interval_seconds": 30})
        cfg = AgentConfig.load(self.path)
        self.assertEqual(cfg.server_url, "https://nova.example.com")

    def test_legacy_static_token_gets_actionable_error(self):
        self._write({"server_url": "https://nova.example.com", "agent_id": AGENT_ID,
                     "token": "x" * 48, "heartbeat_interval_seconds": 30})
        with self.assertRaises(ConfigError) as ctx:
            AgentConfig.load(self.path)
        self.assertNotIn("x" * 48, str(ctx.exception))
        self.assertIn("nova-agent init", str(ctx.exception))

    def test_errors(self):
        with self.assertRaises(ConfigError):
            AgentConfig.load(self.path)  # missing file
        self._write("{not json")
        with self.assertRaises(ConfigError):
            AgentConfig.load(self.path)
        self._write([1, 2])
        with self.assertRaises(ConfigError):
            AgentConfig.load(self.path)
        self._write({"agent_id": AGENT_ID})
        with self.assertRaises(ConfigError):
            AgentConfig.load(self.path)

    def test_insecure_requires_explicit_opt_in(self):
        data = {"server_url": "http://localhost:8000", "agent_id": AGENT_ID, "token": TOKEN}
        self._write(data)
        with self.assertRaises(ConfigError):
            AgentConfig.from_mapping(data, env={})
        self.assertTrue(AgentConfig.from_mapping(data, env={"NOVA_AGENT_ALLOW_INSECURE": "1"}).is_insecure)
        self.assertTrue(AgentConfig.from_mapping({**data, "allow_insecure": True}, env={}).is_insecure)
        # truthy-but-not-True must not count as opt-in
        with self.assertRaises(ConfigError):
            AgentConfig.from_mapping({**data, "allow_insecure": "yes"}, env={})


if __name__ == "__main__":
    unittest.main()
