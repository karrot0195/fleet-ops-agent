"""Unit tests for rollback module."""

from __future__ import annotations

import unittest


class TestRollbackPlan(unittest.TestCase):
    """Test rollback dry-run plan generation."""

    def test_dry_run_with_backup(self):
        from fleetkit.rollback import dry_run_plan
        record = {
            "ip": "192.0.2.1",
            "tool": "nginx",
            "execution": {
                "state": "SUCCEEDED",
                "backup_path": "/tmp/backup.tar.gz",
                "old_version": "1.24.0",
            },
        }
        result = dry_run_plan(record)
        self.assertEqual(result["state"] if "state" in result else "PLAN", "PLAN")
        plan_text = "\n".join(result["plan"])
        self.assertIn("192.0.2.1", plan_text)
        self.assertIn("backup", plan_text.lower())

    def test_dry_run_no_backup(self):
        from fleetkit.rollback import dry_run_plan
        record = {"ip": "192.0.2.1", "tool": "nginx", "execution": {}}
        result = dry_run_plan(record)
        plan_text = "\n".join(result["plan"])
        self.assertIn("ERROR", plan_text)


if __name__ == "__main__":
    unittest.main()
