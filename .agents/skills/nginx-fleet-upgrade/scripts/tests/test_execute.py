import json
import tempfile
import unittest
from pathlib import Path

from fleetkit.execute import run_vm
from fleetkit.ssh import CommandResult, SSHError
from tests.helpers import FleetCase


class FakeCfg:
    def __init__(self, root: Path):
        self.root = root
        self.tool = {
            "name": "nginx",
            "config_paths": ["/etc/nginx"],
            "version_query": "dpkg-query -W -f='${Version}' nginx",
        }

    def get(self, dotted: str, default=None):
        return {"ssh.command_timeout": 60}.get(dotted, default)

    def resolve(self, dotted: str) -> Path:
        return self.root / "backups"


class FlakyDownloadClient:
    def __init__(self):
        self.calls: list[str] = []

    def run(self, ip, command, **kwargs):
        self.calls.append(command)
        if "sha256sum" in command:
            stdout = "a" * 64 + "  /var/backups/x.tar.gz"
        elif "dpkg-query" in command:
            stdout = "1.18.0-1"
        else:
            stdout = ""
        return CommandResult([], 0, stdout, "")

    def download(self, ip, remote, local):
        raise SSHError(f"scp download from {ip} failed: timeout")


class RunVMFailureTests(unittest.TestCase):
    def test_scp_download_failure_marks_vm_failed(self):
        client = FlakyDownloadClient()
        record = {
            "ip": "10.0.0.1",
            "evidence": {
                "installed_version": "1.18.0-1",
                "candidate_version": "1.24.0-1",
                "tls_present": False,
            },
            "timestamps": {},
        }
        updated = run_vm(client, FakeCfg(Path(tempfile.mkdtemp())), record, "canary", 1)
        self.assertEqual(updated["execution"]["state"], "FAILED")
        self.assertIn("scp download", updated["execution"]["error"])
        self.assertEqual(updated["execution"]["steps"][-1]["name"], "backup")
        self.assertFalse(updated["execution"]["steps"][-1]["ok"])
        self.assertFalse(any("apt-get" in call for call in client.calls))


class ExecuteGuardTests(FleetCase):
    def setUp(self):
        super().setUp()
        self.audit()

    def state(self):
        return json.loads((self.root / ".fleet" / "state.json").read_text(encoding="utf-8"))

    def test_execute_requires_yes(self):
        code, payload, stderr = self.run_json("execute", "--phase", "canary", "--approve", "10.0.0.1")
        self.assertEqual(code, 3)
        self.assertEqual(self.state()["approvals"], [])

    def test_blocked_ip_cannot_be_approved(self):
        code, payload, stderr = self.run_json(
            "execute", "--phase", "canary", "--approve", "10.0.0.3", "--yes"
        )
        self.assertEqual(code, 3)
        self.assertIn("BLOCKED", payload["error"]["message"])

    def test_up_to_date_ip_cannot_be_approved(self):
        code, _, _ = self.run_json("execute", "--phase", "canary", "--approve", "10.0.0.2", "--yes")
        self.assertEqual(code, 3)

    def test_dry_run_changes_nothing(self):
        before = (self.root / ".fleet" / "state.json").read_text(encoding="utf-8")
        self.log_path.unlink(missing_ok=True)
        code, payload, stderr = self.run_json(
            "execute", "--phase", "canary", "--approve", "10.0.0.1", "--dry-run"
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(payload["data"][0]["ip"], "10.0.0.1")
        after = (self.root / ".fleet" / "state.json").read_text(encoding="utf-8")
        self.assertEqual(before, after)
        self.assertFalse(self.applied_path.exists())
        self.assertEqual(self.commands(), [])

    def test_concurrency_out_of_range(self):
        code, payload, stderr = self.run_json(
            "execute", "--phase", "canary", "--approve", "10.0.0.1", "--concurrency", "17", "--yes"
        )
        self.assertEqual(code, 2)

    def test_idempotent_recheck_skips_upgrade(self):
        self.update_vm("10.0.0.1", installed_version="1.24.0-1")
        self.log_path.unlink(missing_ok=True)
        code, payload, stderr = self.run_json(
            "execute", "--phase", "canary", "--approve", "10.0.0.1", "--yes"
        )
        self.assertEqual(code, 0, stderr)
        record = self.state()["records"]["10.0.0.1"]
        self.assertEqual(record["execution"]["state"], "SUCCEEDED")
        self.assertEqual(record["execution"]["new_version"], "1.24.0-1")
        self.assertIn("re-check", record["execution"]["steps"][0]["detail"])
        self.assertFalse(any("apt-get" in command for command in self.commands()))
        self.assertFalse(any("tar czf" in command for command in self.commands()))

    def test_canary_is_always_first_approved_vm(self):
        self.update_vm("10.0.0.2", installed_version="1.18.0-1", candidate_version="1.24.0-1")
        self.audit()
        first, _, _ = self.run_json(
            "execute", "--phase", "canary", "--approve", "10.0.0.1,10.0.0.2", "--yes"
        )
        self.assertEqual(first, 0)
        second, payload, stderr = self.run_json(
            "execute", "--phase", "canary", "--approve", "10.0.0.1,10.0.0.2", "--yes"
        )
        self.assertEqual(second, 3)
        self.assertIn("canary already completed", payload["error"]["message"])

    def test_canary_success_records_backup_and_version(self):
        code, payload, stderr = self.run_json(
            "execute", "--phase", "canary", "--approve", "10.0.0.1", "--yes"
        )
        self.assertEqual(code, 0, stderr)
        record = self.state()["records"]["10.0.0.1"]
        self.assertEqual(record["execution"]["state"], "SUCCEEDED")
        self.assertEqual(record["execution"]["new_version"], "1.24.0-1")
        self.assertTrue(record["backup"]["verified"])
        self.assertTrue((self.root / "backups" / "10.0.0.1").is_dir())
        self.assertTrue(self.applied_path.exists())

    def test_backup_failure_aborts_before_upgrade(self):
        self.update_vm("10.0.0.1", backup_ok=False)
        code, _, _ = self.run_json("execute", "--phase", "canary", "--approve", "10.0.0.1", "--yes")
        self.assertEqual(code, 4)
        record = self.state()["records"]["10.0.0.1"]
        self.assertEqual(record["execution"]["state"], "FAILED")
        self.assertFalse(any("apt-get" in command for command in self.commands()))

    def test_empty_backup_aborts(self):
        self.write_scenario({**self.load_scenario(), "backup_empty": True})
        code, _, _ = self.run_json("execute", "--phase", "canary", "--approve", "10.0.0.1", "--yes")
        self.assertEqual(code, 4)
        record = self.state()["records"]["10.0.0.1"]
        self.assertEqual(record["execution"]["state"], "FAILED")
        self.assertFalse(any("apt-get" in command for command in self.commands()))

    def test_backup_checksum_mismatch_aborts(self):
        self.update_vm("10.0.0.1", backup_corrupt=True)
        code, _, _ = self.run_json("execute", "--phase", "canary", "--approve", "10.0.0.1", "--yes")
        self.assertEqual(code, 4)
        record = self.state()["records"]["10.0.0.1"]
        self.assertEqual(record["execution"]["state"], "FAILED")
        self.assertIn("checksum mismatch", record["execution"]["error"])
        self.assertFalse(any("apt-get" in command for command in self.commands()))

    def test_gate_before_canary_refused(self):
        code, _, _ = self.run_json("gate", "--decision", "proceed")
        self.assertEqual(code, 3)

    def test_fleet_requires_proceed(self):
        code, _, _ = self.run_json("execute", "--phase", "fleet", "--approve", "10.0.0.1", "--yes")
        self.assertEqual(code, 3)

    def test_fleet_with_stop_refused(self):
        self.run_json("execute", "--phase", "canary", "--approve", "10.0.0.1", "--yes")
        self.run_json("gate", "--decision", "stop")
        code, payload, stderr = self.run_json(
            "execute", "--phase", "fleet", "--approve", "10.0.0.1", "--yes"
        )
        self.assertEqual(code, 3)
        self.assertIn("proceed", payload["error"]["message"])
