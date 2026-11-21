from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fleetkit.cli import main

TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parent
SKILL = SCRIPTS.parent
FAKE_BIN = TESTS / "fixtures" / "bin"


def default_scenario() -> dict:
    return {
        "doctl": [
            {
                "name": "vm-alpha",
                "status": "active",
                "networks": {"v4": [{"type": "public", "ip_address": "10.0.0.1"}]},
            },
            {
                "name": "vm-bravo",
                "status": "active",
                "networks": {"v4": [{"type": "public", "ip_address": "10.0.0.2"}]},
            },
            {
                "name": "vm-charlie",
                "status": "active",
                "networks": {"v4": [{"type": "public", "ip_address": "10.0.0.3"}]},
            },
            {
                "name": "vm-delta",
                "status": "active",
                "networks": {"v4": [{"type": "public", "ip_address": "10.0.0.4"}]},
            },
        ],
        "vms": {
            "10.0.0.1": {
                "reachable": True,
                "installed_version": "1.18.0-1",
                "candidate_version": "1.24.0-1",
                "origin": "http://archive.ubuntu.com/ubuntu jammy/main amd64 Packages",
            },
            "10.0.0.2": {
                "reachable": True,
                "installed_version": "1.24.0-1",
                "candidate_version": "1.24.0-1",
                "origin": "http://archive.ubuntu.com/ubuntu jammy/main amd64 Packages",
            },
            "10.0.0.3": {
                "reachable": True,
                "installed_version": "1.18.0-1",
                "candidate_version": "1.24.0-1",
                "origin": "http://archive.ubuntu.com/ubuntu jammy/main amd64 Packages",
                "holds": ["nginx"],
            },
            "10.0.0.4": {"reachable": False, "error": "connection refused"},
        },
    }


class FleetCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / ".specific").mkdir()
        shutil.copy(SKILL / "references" / "fleet-config.template.yaml", self.root / ".specific" / "nginx-fleet.yaml")
        (self.root / ".personal").mkdir()
        key = self.root / "id_ed25519"
        key.write_text("fake-key", encoding="utf-8")
        key.chmod(0o600)
        ssh_env = self.root / ".personal" / "ssh.env"
        ssh_env.write_text(f"SSH_USER=root\nSSH_KEY={key}\nSSH_PORT=22\n", encoding="utf-8")
        ssh_env.chmod(0o600)
        (self.root / "LOGS.md").write_text("# LOGS\n\n## Entries\n", encoding="utf-8")
        self.scenario_path = self.root / "scenario.json"
        self.log_path = self.root / "commands.log"
        self.applied_path = self.root / "applied.txt"
        self.write_scenario(default_scenario())

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_scenario(self, data: dict) -> None:
        self.scenario_path.write_text(json.dumps(data), encoding="utf-8")

    def load_scenario(self) -> dict:
        return json.loads(self.scenario_path.read_text(encoding="utf-8"))

    def update_vm(self, ip: str, **values) -> None:
        data = self.load_scenario()
        data["vms"][ip].update(values)
        self.write_scenario(data)

    def update_config(self, **values) -> None:
        import yaml

        path = self.root / ".specific" / "nginx-fleet.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for dotted, value in values.items():
            node = data
            parts = dotted.split(".")
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = value
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    def run_cli(self, *args: str) -> tuple[int, str, str]:
        env = os.environ.copy()
        env["PATH"] = f"{FAKE_BIN}:{env.get('PATH', '')}"
        env["FLEET_FAKE_SCENARIO"] = str(self.scenario_path)
        env["FLEET_FAKE_LOG"] = str(self.log_path)
        env["FLEET_FAKE_APPLIED"] = str(self.applied_path)
        env["FLEET_FAKE_COUNTERS"] = str(self.root / "counters")
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(["--root", str(self.root), *args])
        return code, stdout.getvalue(), stderr.getvalue()

    def run_json(self, *args: str) -> tuple[int, dict, str]:
        code, stdout, stderr = self.run_cli("--json", *args)
        return code, json.loads(stdout) if stdout.strip() else {}, stderr

    def commands(self) -> list[str]:
        if not self.log_path.is_file():
            return []
        return [line.split("\t", 1)[-1] for line in self.log_path.read_text(encoding="utf-8").splitlines()]

    def audit(self) -> dict:
        code, data, stderr = self.run_json("discover")
        self.assertEqual(code, 0, stderr)
        code, data, stderr = self.run_json("survey", "--all")
        self.assertEqual(code, 0, stderr)
        return data["data"]
