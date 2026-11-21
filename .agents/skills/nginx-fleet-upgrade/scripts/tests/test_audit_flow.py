import json
import unittest

from tests.helpers import FleetCase


class AuditFlowTests(FleetCase):
    def test_discover_and_survey_every_vm(self):
        data = self.audit()
        self.assertEqual(len(data["groups"]["UPGRADE"]), 1)
        self.assertEqual(data["groups"]["UPGRADE"], ["10.0.0.1"])
        self.assertEqual(data["groups"]["UP-TO-DATE"], ["10.0.0.2"])
        self.assertEqual(data["groups"]["BLOCKED"], ["10.0.0.3"])
        self.assertEqual(data["groups"]["UNREACHABLE"], ["10.0.0.4"])
        state = json.loads((self.root / ".fleet" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(len(state["records"]), 4)
        for ip in ("10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4"):
            self.assertTrue((self.root / "plan" / f"{ip}.md").is_file())
        unreachable = (self.root / "plan" / "10.0.0.4.md").read_text(encoding="utf-8")
        self.assertIn("Connectivity", unreachable)
        self.assertIn("connection refused", unreachable)
        blocked = (self.root / "plan" / "10.0.0.3.md").read_text(encoding="utf-8")
        self.assertIn("held", blocked)

    def test_audit_never_mutates(self):
        self.audit()
        mutating = [
            command
            for command in self.commands()
            if "apt-get" in command or "tar czf" in command or "systemctl restart" in command
        ]
        self.assertEqual(mutating, [])
        self.assertFalse(self.applied_path.exists())

    def test_rerun_is_stable(self):
        self.audit()
        before = (self.root / ".fleet" / "state.json").read_text(encoding="utf-8")
        before_commands = len(self.commands())
        self.audit()
        self.assertFalse(self.applied_path.exists())
        self.assertGreaterEqual(len(self.commands()), before_commands)
        state = json.loads((self.root / ".fleet" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(len(state["records"]), 4)
        self.assertEqual(before.count('"schema_version"'), 1)

    def test_unknown_ip_rejected(self):
        self.audit()
        code, payload, stderr = self.run_json("survey", "--ip", "10.0.0.99")
        self.assertEqual(code, 5)
        self.assertFalse(payload["ok"])

    def test_survey_before_discover_refused(self):
        code, payload, _ = self.run_json("survey", "--all")
        self.assertEqual(code, 5)
        self.assertIn("discover", payload["error"]["message"])
        self.assertFalse((self.root / ".fleet" / "state.json").exists())

    def test_report_before_discover_refused(self):
        code, payload, _ = self.run_json("report")
        self.assertEqual(code, 5)
        self.assertIn("discover", payload["error"]["message"])
        self.assertFalse((self.root / ".fleet" / "state.json").exists())

    def test_unreachable_vm_is_retried_once(self):
        self.audit()
        evidence_calls = [command for command in self.commands() if "###UID" in command]
        self.assertEqual(len(evidence_calls), 5)

    def test_empty_fleet(self):
        self.write_scenario({"doctl": [], "vms": {}})
        code, data, stderr = self.run_json("discover")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(data["data"]["inventory"], [])
        code, data, stderr = self.run_json("survey", "--all")
        self.assertEqual(code, 0, stderr)
