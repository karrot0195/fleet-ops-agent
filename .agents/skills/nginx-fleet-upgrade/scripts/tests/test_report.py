import json
import unittest

from fleetkit.records import clean_cell
from tests.helpers import FleetCase


class ReportTests(FleetCase):
    def setUp(self):
        super().setUp()
        self.audit()

    def test_report_lists_every_vm(self):
        code, payload, stderr = self.run_json("report")
        self.assertEqual(code, 0, stderr)
        rows = payload["data"]["rows"]
        self.assertEqual(len(rows), 4)
        self.assertEqual({row["verdict"] for row in rows}, {"UPGRADE", "UP-TO-DATE", "BLOCKED", "UNREACHABLE"})

    def test_log_appends_once(self):
        code, payload, stderr = self.run_json("report", "--log")
        self.assertEqual(code, 0, stderr)
        self.assertTrue(payload["data"]["logged"])
        code, payload, stderr = self.run_json("report", "--log")
        self.assertEqual(code, 0, stderr)
        self.assertFalse(payload["data"]["logged"])
        self.assertIn("already recorded", stderr)
        text = (self.root / "LOGS.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("nginx fleet upgrade"), 1)
        self.assertIn("Audited 4 VM(s)", text)

    def test_empty_fleet_report(self):
        self.write_scenario({"doctl": [], "vms": {}})
        self.run_json("discover")
        code, payload, stderr = self.run_json("report", "--log")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(payload["data"]["rows"], [])
        self.assertIn("Audited 0 VM(s)", (self.root / "LOGS.md").read_text(encoding="utf-8"))

    def test_clean_cell_collapses_newlines_and_pipes(self):
        self.assertEqual(clean_cell("stale\nevidence\nblob"), "stale; evidence; blob")
        self.assertEqual(clean_cell("a|b"), "a\\|b")
        self.assertEqual(clean_cell(None), "—")

    def test_report_flow_after_rollout(self):
        self.run_json("execute", "--phase", "canary", "--approve", "10.0.0.1", "--yes")
        code, payload, stderr = self.run_json("report", "--log")
        self.assertEqual(code, 0, stderr)
        row = next(item for item in payload["data"]["rows"] if item["ip"] == "10.0.0.1")
        self.assertEqual(row["old_version"], "1.18.0-1")
        self.assertEqual(row["new_version"], "1.24.0-1")
        self.assertTrue(row["config_ok"])
        self.assertEqual(row["state"], "SUCCEEDED")
        text = (self.root / "LOGS.md").read_text(encoding="utf-8")
        self.assertIn("Processed 1 VM(s): 1 succeeded", text)
