"""Unit tests for config loading and validation."""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from fleetkit.config import Config, ConfigError, PreflightError, _validate_tool_config
from fleetkit.state import StateStore, empty_state, utcnow


class TestConfigClass(unittest.TestCase):
    """Test Config.get() and resolve() methods."""

    def test_get_dotted_path(self):
        data = {"ssh": {"connect_timeout": 5}}
        cfg = Config(Path.cwd(), Path("/dev/null"), data)
        self.assertEqual(cfg.get("ssh.connect_timeout"), 5)
        self.assertIsNone(cfg.get("ssh.missing"))
        self.assertEqual(cfg.get("ssh.missing", "default"), "default")

    def test_resolve_relative(self):
        data = {"paths": {"records_dir": "plan"}}
        root = Path("/test/root").resolve()
        cfg = Config(root, Path("/test/root/.specific/test.yaml"), data)
        resolved = cfg.resolve("paths.records_dir")
        self.assertEqual(resolved, Path("/test/root/plan"))


class TestToolValidation(unittest.TestCase):
    """Test tool config validation from project.yaml patterns."""

    def _valid_base(self):
        return {
            "apiVersion": "fleet-upgrade-tool/v1",
            "tool": {
                "name": "nginx",
                "package": "nginx",
                "service": "nginx",
                "config_paths": ["/etc/nginx"],
                "version_query": "dpkg-query -W -f='${Version}' nginx",
                "precheck": "nginx -t",
                "allowed_origin_patterns": [],
                "hold_patterns": [],
                "drift_patterns": [],
                "verify": {
                    "http": {"enabled": False, "url": "", "timeout": 10},
                    "https": {"enabled": "auto", "url": "", "timeout": 10},
                    "require_status": [],
                },
            },
            "migration": {"enabled": False},
        }

    def test_validates_clean_config(self):
        _validate_tool_config(self._valid_base())

    def test_rejects_bad_api_version(self):
        cfg = self._valid_base()
        cfg["apiVersion"] = "wrong/v1"
        with self.assertRaises(ConfigError):
            _validate_tool_config(cfg)

    def test_rejects_empty_tool_name(self):
        cfg = self._valid_base()
        cfg["tool"]["name"] = ""
        with self.assertRaises(ConfigError):
            _validate_tool_config(cfg)

    def test_rejects_missing_required_field(self):
        cfg = self._valid_base()
        del cfg["tool"]["package"]
        with self.assertRaises(ConfigError):
            _validate_tool_config(cfg)


class TestStateStore(unittest.TestCase):
    """Test StateStore load/save."""

    def test_empty_state_structure(self):
        sd = empty_state(tool="nginx")
        self.assertIn("run_id", sd)
        self.assertIn("started_at", sd)
        self.assertIn("records", sd)
        self.assertIsInstance(sd["records"], dict)

    def test_utcnow_format(self):
        now = utcnow()
        # Must be parseable ISO format ending in Z
        self.assertTrue(now.endswith("Z"))
        self.assertIn("T", now)

    def test_store_save_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.data = empty_state(tool="nginx")
            store.data["gates"] = []
            store.add_gate("proceed", note="all good")
            store.save()

            store2 = StateStore(tmp)
            loaded = store2.load()
            self.assertEqual(len(loaded["gates"]), 1)
            self.assertEqual(loaded["gates"][0]["decision"], "proceed")


class TestLoadSSHEnv(unittest.TestCase):
    """Test SSH env file parsing."""

    def test_load_valid_env(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("SSH_USER=admin\nSSH_KEY=~/.ssh/id_rsa\nSSH_PORT=22\n")
            f.flush()
            from fleetkit.config import load_ssh_env
            result = load_ssh_env(f.name)
            self.assertEqual(result["user"], "admin")
            self.assertEqual(result["port"], 22)
            self.assertTrue(result["key"].endswith(".ssh/id_rsa"))

    def test_load_missing_fields_raises(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("SSH_USER=admin\n")  # missing key and port
            f.flush()
            from fleetkit.config import load_ssh_env
            with self.assertRaises(PreflightError):
                load_ssh_env(f.name)

    def test_load_invalid_port_raises(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("SSH_USER=admin\nSSH_KEY=~/.ssh/id_rsa\nSSH_PORT=notanumber\n")
            f.flush()
            from fleetkit.config import load_ssh_env
            with self.assertRaises(PreflightError):
                load_ssh_env(f.name)


if __name__ == "__main__":
    unittest.main()
