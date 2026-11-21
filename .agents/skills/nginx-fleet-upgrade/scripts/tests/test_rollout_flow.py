import json
import unittest

from tests.helpers import FleetCase


class RolloutFlowTests(FleetCase):
    def setUp(self):
        super().setUp()
        self.update_vm("10.0.0.2", installed_version="1.18.0-1", candidate_version="1.24.0-1")
        self.audit()

    def state(self):
        return json.loads((self.root / ".fleet" / "state.json").read_text(encoding="utf-8"))

    def canary(self):
        return self.run_json("execute", "--phase", "canary", "--approve", "10.0.0.1,10.0.0.2", "--yes")

    def test_canary_then_fleet(self):
        self.update_vm("10.0.0.2", drift=["/etc/nginx/nginx.conf.dpkg-dist"])
        code, payload, stderr = self.canary()
        self.assertEqual(code, 0, stderr)
        code, payload, stderr = self.run_json("gate", "--decision", "proceed", "--note", "healthy")
        self.assertEqual(code, 0, stderr)
        code, payload, stderr = self.run_json(
            "execute", "--phase", "fleet", "--approve", "10.0.0.1,10.0.0.2", "--yes"
        )
        self.assertEqual(code, 0, stderr)
        records = self.state()["records"]
        self.assertEqual(records["10.0.0.1"]["execution"]["state"], "SUCCEEDED")
        self.assertEqual(records["10.0.0.2"]["execution"]["state"], "SUCCEEDED")
        self.assertEqual(records["10.0.0.1"]["execution"]["phase"], "canary")
        self.assertEqual(records["10.0.0.2"]["execution"]["phase"], "fleet")
        self.assertEqual(len(self.state()["gates"]), 1)
        self.assertEqual(len(records["10.0.0.2"]["drift_flags"]), 1)
        record_text = (self.root / "plan" / "10.0.0.2.md").read_text(encoding="utf-8")
        self.assertIn("nginx.conf.dpkg-dist", record_text)
        self.assertIn("manual review required", record_text)
        self.assertIn("## Verification", record_text)

    def test_stop_blocks_fleet(self):
        self.canary()
        self.run_json("gate", "--decision", "stop")
        code, payload, stderr = self.run_json(
            "execute", "--phase", "fleet", "--approve", "10.0.0.1,10.0.0.2", "--yes"
        )
        self.assertEqual(code, 3)
        self.assertNotIn("10.0.0.2", self.applied_path.read_text(encoding="utf-8").split())

    def test_retry_then_success(self):
        self.update_vm("10.0.0.2", upgrade_fail_count=1)
        self.canary()
        self.run_json("gate", "--decision", "proceed")
        code, payload, stderr = self.run_json(
            "execute", "--phase", "fleet", "--approve", "10.0.0.1,10.0.0.2", "--yes"
        )
        self.assertEqual(code, 0, stderr)
        record = self.state()["records"]["10.0.0.2"]
        self.assertEqual(record["execution"]["state"], "SUCCEEDED")
        self.assertEqual(record["execution"]["attempts"], 2)

    def test_failure_isolated_after_retry(self):
        self.update_vm("10.0.0.2", upgrade_ok=False)
        self.canary()
        self.run_json("gate", "--decision", "proceed")
        code, payload, stderr = self.run_json(
            "execute", "--phase", "fleet", "--approve", "10.0.0.1,10.0.0.2", "--yes"
        )
        self.assertEqual(code, 4)
        records = self.state()["records"]
        self.assertEqual(records["10.0.0.2"]["execution"]["state"], "FAILED")
        self.assertEqual(records["10.0.0.2"]["execution"]["attempts"], 2)
        self.assertEqual(records["10.0.0.1"]["execution"]["state"], "SUCCEEDED")

        retry_again, payload, stderr = self.run_json(
            "execute", "--phase", "fleet", "--approve", "10.0.0.2", "--yes"
        )
        self.assertEqual(retry_again, 0, stderr)
        self.assertEqual(self.state()["records"]["10.0.0.2"]["execution"]["attempts"], 2)

    def test_fleet_dry_run_after_gate(self):
        self.canary()
        self.run_json("gate", "--decision", "proceed")
        before = (self.root / ".fleet" / "state.json").read_text(encoding="utf-8")
        code, payload, stderr = self.run_json(
            "execute", "--phase", "fleet", "--approve", "10.0.0.1,10.0.0.2", "--dry-run"
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(payload["data"][0]["ip"], "10.0.0.1")
        self.assertEqual(before, (self.root / ".fleet" / "state.json").read_text(encoding="utf-8"))
