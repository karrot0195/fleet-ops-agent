"""Unit tests for execute module."""

from __future__ import annotations

import unittest


class TestValidateApprovals(unittest.TestCase):
    """Test validate_approvals logic."""

    def setUp(self):
        from fleetkit.execute import validate_approvals, ExecuteError
        self.validate_approvals = validate_approvals
        self.ExecuteError = ExecuteError

    def test_all_upgraded_ips_pass(self):
        records = {
            "192.0.2.1:nginx": {"survey": {"verdict": "UPGRADE"}},
            "192.0.2.2:nginx": {"survey": {"verdict": "UPGRADE"}},
        }
        # Should not raise
        self.validate_approvals(records, ["192.0.2.1", "192.0.2.2"], {"tool": {"name": "nginx"}})

    def test_non_upgrade_ip_raises(self):
        records = {
            "192.0.2.1:nginx": {"survey": {"verdict": "UP_TO_DATE"}},
        }
        with self.assertRaises(self.ExecuteError):
            self.validate_approvals(records, ["192.0.2.1"], {"tool": {"name": "nginx"}})

    def test_blocked_ip_raises(self):
        records = {
            "192.0.2.1:nginx": {"survey": {"verdict": "BLOCKED(precheck failed)"}},
        }
        with self.assertRaises(self.ExecuteError):
            self.validate_approvals(records, ["192.0.2.1"], {"tool": {"name": "nginx"}})


if __name__ == "__main__":
    unittest.main()
