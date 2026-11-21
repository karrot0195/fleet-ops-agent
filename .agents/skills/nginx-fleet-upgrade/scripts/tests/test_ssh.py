import subprocess
import unittest
from pathlib import Path

from fleetkit.config import load_ssh_env
from fleetkit.ssh import SSHClient
from tests.helpers import FleetCase


class Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeRunner:
    def __init__(self, completed=None, error=None):
        self.completed = completed or Completed()
        self.error = error
        self.calls = []

    def __call__(self, argv, timeout):
        self.calls.append((argv, timeout))
        if self.error:
            raise self.error
        return self.completed


class SSHTests(FleetCase):
    def client(self, runner, **config):
        for key, value in config.items():
            self.update_config(**{key: value})
        from fleetkit.config import load_config

        cfg = load_config(self.root)
        env = load_ssh_env(cfg)
        return SSHClient(cfg, env, runner=runner, log_dir=self.root / ".fleet" / "logs")

    def test_root_command_has_no_sudo(self):
        runner = FakeRunner()
        client = self.client(runner)
        client.run("10.0.0.1", "nginx -t", need_privilege=True)
        argv = runner.calls[0][0]
        self.assertIn("root@10.0.0.1", argv)
        self.assertEqual(argv[-1], "nginx -t")
        self.assertNotIn("sudo", " ".join(argv))

    def test_non_root_uses_sudo_non_interactive(self):
        runner = FakeRunner()
        env_file = self.root / ".personal" / "ssh.env"
        env_file.write_text(f"SSH_USER=deploy\nSSH_KEY={self.root / 'id_ed25519'}\nSSH_PORT=22\n", encoding="utf-8")
        env_file.chmod(0o600)
        client = self.client(runner)
        client.run("10.0.0.1", "nginx -t", need_privilege=True)
        self.assertIn("sudo -n sh -c", runner.calls[0][0][-1])

    def test_timeout_returns_124(self):
        runner = FakeRunner(error=subprocess.TimeoutExpired(["ssh"], 5))
        client = self.client(runner)
        result = client.run("10.0.0.1", "true", timeout=5)
        self.assertEqual(result.returncode, 124)
        self.assertFalse(result.ok)

    def test_redaction_in_log(self):
        runner = FakeRunner(Completed(stdout="secret-value"))
        client = self.client(runner, **{"logging.redact": ["secret-value"]})
        client.run("10.0.0.1", "echo")
        log = (self.root / ".fleet" / "logs" / "10.0.0.1.log").read_text(encoding="utf-8")
        self.assertNotIn("secret-value", log)
        self.assertIn("***", log)

    def test_download_builds_scp(self):
        runner = FakeRunner()
        client = self.client(runner)
        client.download("10.0.0.1", "/var/backups/x.tar.gz", self.root / "backups" / "x.tar.gz")
        argv = runner.calls[0][0]
        self.assertEqual(argv[0], "scp")
        self.assertIn("-P", argv)
        self.assertIn("root@10.0.0.1:/var/backups/x.tar.gz", argv)

    def test_multiplex_options_present_by_default(self):
        runner = FakeRunner()
        client = self.client(runner)
        options = client._common_options()
        self.assertIn("ControlMaster=auto", options)
        self.assertIn("ControlPersist=300", options)
        self.assertTrue(any(option.startswith("ControlPath=") for option in options))
        self.assertIn("ServerAliveInterval=15", options)

    def test_multiplex_disabled_by_config(self):
        runner = FakeRunner()
        client = self.client(runner, **{"ssh.multiplex": False})
        options = client._common_options()
        self.assertNotIn("ControlMaster=auto", options)
        self.assertFalse(any(option.startswith("ControlPath=") for option in options))
