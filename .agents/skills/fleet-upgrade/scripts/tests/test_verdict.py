"""Unit tests for verdict computation."""

from __future__ import annotations

import unittest

from fleetkit.verdict import (
    BLOCKED,
    SKIP,
    UP_TO_DATE,
    UPGRADE,
    UNREACHABLE,
    compute_verdict,
)

TOOL_CONFIG = {
    "tool": {
        "name": "nginx",
        "package": "nginx",
        "service": "nginx",
        "config_paths": ["/etc/nginx"],
        "version_query": "dpkg-query -W -f='${Version}' nginx",
        "precheck": "nginx -t",
        "allowed_origin_patterns": ["archive.ubuntu.com"],
        "hold_patterns": ["nginx", "nginx-*"],
    },
    "migration": {"enabled": False},
}


class TestVerdict(unittest.TestCase):
    """Test all verdict computation scenarios."""

    def _result(self, **kw):
        defaults = {
            "installed_version": "1.24.0",
            "candidate_version": "1.25.0",
            "precheck_ok": True,
            "origin_ok": True,
            "hold_detected": False,
            "unreachable": False,
            "error": None,
        }
        defaults.update(kw)
        return defaults

    def test_skip_no_installed_version(self):
        r = self._result(installed_version="")
        self.assertEqual(compute_verdict(TOOL_CONFIG, r), SKIP)

    def test_up_to_date_no_candidate(self):
        r = self._result(candidate_version="")
        self.assertEqual(compute_verdict(TOOL_CONFIG, r), UP_TO_DATE)

    def test_up_to_date_matching_versions(self):
        r = self._result(installed_version="1.24.0", candidate_version="1.24.0")
        self.assertEqual(compute_verdict(TOOL_CONFIG, r), UP_TO_DATE)

    def test_upgrade_available(self):
        r = self._result(installed_version="1.24.0", candidate_version="1.25.0")
        self.assertEqual(compute_verdict(TOOL_CONFIG, r), UPGRADE)

    def test_blocked_precheck_failure(self):
        r = self._result(precheck_ok=False)
        self.assertTrue(r["installed_version"])  # ensure installed is set
        v = compute_verdict(TOOL_CONFIG, r)
        self.assertTrue(v.startswith(BLOCKED))
        self.assertIn("precheck", v.lower())

    def test_blocked_hold_detected(self):
        r = self._result(hold_detected=True)
        v = compute_verdict(TOOL_CONFIG, r)
        self.assertTrue(v.startswith(BLOCKED))
        self.assertIn("held", v.lower())

    def test_blocked_unexpected_origin(self):
        r = self._result(origin_ok=False)
        v = compute_verdict(TOOL_CONFIG, r)
        self.assertTrue(v.startswith(BLOCKED))
        self.assertIn("origin", v.lower())

    def test_unreachable_connection_failed(self):
        r = self._result(unreachable=True, error="connection timeout")
        v = compute_verdict(TOOL_CONFIG, r)
        self.assertTrue(v.startswith(UNREACHABLE))
        self.assertIn("connection", v.lower())


if __name__ == "__main__":
    unittest.main()
