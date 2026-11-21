import json
import unittest

from tests.helpers import FleetCase


class RollbackTests(FleetCase):
    def setUp(self):
        super().setUp()
        self.update_vm("10.0.0.1", upgrade_ok=False)
        self.audit()

    def state(self):
        return json.loads((self.root / ".fleet" / "state.json").read_text(encoding="utf-8"))

    def fail_canary(self):
        code, payload, stderr = self.run_json(
            "execute", "--phase", "canary", "--approve", "10.0.0.1", "--yes"
        )
        self.assertEqual(code, 4, stderr)
        return self.state()["records"]["10.0.0.1"]

    def test_requires_yes(self):
        self.fail_canary()
        code, payload, stderr = self.run_json("rollback", "--ip", "10.0.0.1")
        self.assertEqual(code, 3)

    def test_requires_verified_backup(self):
        self.update_vm("10.0.0.1", backup_ok=False)
        code, _, _ = self.run_json("execute", "--phase", "canary", "--approve", "10.0.0.1", "--yes")
        self.assertEqual(code, 4)
        code, payload, stderr = self.run_json("rollback", "--ip", "10.0.0.1", "--yes")
        self.assertEqual(code, 4)
        self.assertIn("verified backup", payload["error"]["message"])

    def test_successful_rollback(self):
        record = self.fail_canary()
        self.assertTrue(record["backup"]["verified"])
        code, payload, stderr = self.run_json("rollback", "--ip", "10.0.0.1", "--yes")
        self.assertEqual(code, 0, stderr)
        updated = self.state()["records"]["10.0.0.1"]
        self.assertEqual(updated["execution"]["state"], "ROLLED_BACK")
        self.assertEqual(updated["rollback"]["state"], "SUCCEEDED")
        self.assertTrue(updated["rollback"]["config_ok"])
        self.assertTrue(updated["rollback"]["service_active"])
        self.assertIn("systemctl restart", "\n".join(self.commands()))

    def test_precheck_failure_after_restore_does_not_restart(self):
        self.fail_canary()
        self.update_vm("10.0.0.1", config_ok=False)
        code, payload, stderr = self.run_json("rollback", "--ip", "10.0.0.1", "--yes")
        self.assertEqual(code, 4)
        updated = self.state()["records"]["10.0.0.1"]
        self.assertEqual(updated["rollback"]["state"], "FAILED")
        self.assertFalse(updated["rollback"]["service_active"])
        self.assertNotIn("systemctl restart", "\n".join(self.commands()))

    def test_dry_run_changes_nothing(self):
        self.fail_canary()
        before = (self.root / ".fleet" / "state.json").read_text(encoding="utf-8")
        code, payload, stderr = self.run_json("rollback", "--ip", "10.0.0.1", "--dry-run")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(payload["data"]["ip"], "10.0.0.1")
        self.assertEqual(before, (self.root / ".fleet" / "state.json").read_text(encoding="utf-8"))
