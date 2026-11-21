import os
import tempfile
import unittest
from pathlib import Path

from fleetkit.config import ConfigError, PreflightError, load_config, load_ssh_env


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".specific").mkdir()
        (self.root / ".personal").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text):
        (self.root / ".specific" / "nginx-fleet.yaml").write_text(text, encoding="utf-8")

    def test_defaults_are_applied(self):
        self.write("apiVersion: nginx-fleet-upgrade/v1\n")
        cfg = load_config(self.root)
        self.assertEqual(cfg.get("execution.concurrency"), 4)
        self.assertEqual(cfg.get("execution.canary_size"), 1)
        self.assertEqual(cfg.get("tool.name"), "nginx")

    def test_unknown_key_rejected(self):
        self.write("apiVersion: nginx-fleet-upgrade/v1\nbogus: true\n")
        with self.assertRaises(ConfigError):
            load_config(self.root)

    def test_canary_size_must_be_one(self):
        self.write("apiVersion: nginx-fleet-upgrade/v1\nexecution:\n  canary_size: 2\n")
        with self.assertRaises(ConfigError):
            load_config(self.root)

    def test_upgrade_command_requires_placeholder(self):
        self.write("apiVersion: nginx-fleet-upgrade/v1\nexecution:\n  upgrade_command: 'apt-get install nginx'\n")
        with self.assertRaises(ConfigError):
            load_config(self.root)

    def test_missing_config(self):
        with self.assertRaises(ConfigError):
            load_config(self.root)

    def test_ssh_env_requires_keys(self):
        self.write("apiVersion: nginx-fleet-upgrade/v1\n")
        (self.root / ".personal" / "ssh.env").write_text("SSH_USER=root\n", encoding="utf-8")
        cfg = load_config(self.root)
        with self.assertRaises(PreflightError):
            load_ssh_env(cfg)

    def test_ssh_env_loads_and_warns_on_mode(self):
        self.write("apiVersion: nginx-fleet-upgrade/v1\n")
        key = self.root / "key"
        key.write_text("k", encoding="utf-8")
        env = self.root / ".personal" / "ssh.env"
        env.write_text(f"SSH_USER=deploy\nSSH_KEY={key}\nSSH_PORT=2222\n", encoding="utf-8")
        os.chmod(env, 0o644)
        cfg = load_config(self.root)
        loaded = load_ssh_env(cfg)
        self.assertEqual(loaded["user"], "deploy")
        self.assertEqual(loaded["port"], 2222)
        self.assertTrue(loaded["warnings"])
