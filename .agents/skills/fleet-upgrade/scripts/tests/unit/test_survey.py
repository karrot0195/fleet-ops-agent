"""Unit tests for survey entries with mocked SSH client."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fleetkit.survey import survey_entries, render_summary, summary_data
from fleetkit.verdict import SKIP, UP_TO_DATE, UPGRADE

# Minimal mock tool config
TOOL_CONFIG = {
    "tool": {
        "name": "nginx",
        "package": "nginx",
        "service": "nginx",
        "config_paths": ["/etc/nginx"],
        "version_query": "dpkg-query -W -f='${Version}' nginx",
        "precheck": "nginx -t",
        "allowed_origin_patterns": ["archive.ubuntu.com"],
        "hold_patterns": ["nginx"],
        "drift_patterns": ["*.dpkg-dist"],
        "verify": {
            "http": {"enabled": False, "url": "", "timeout": 10},
            "https": {"enabled": "auto", "url": "", "timeout": 10},
            "require_status": [],
        },
    },
    "migration": {"enabled": False},
}


class MockCommandResult:
    ok = True
    returncode = 0
    stdout = "1.24.0"
    stderr = ""


class MockSSHClient:
    def __init__(self, version="1.24.0", candidate="1.25.0"):
        self.version = version
        self.candidate = candidate

    def run(self, ip, command, need_privilege=False, check=False, timeout=None):
        result = MockCommandResult()
        if "version_query" in command or "dpkg-query" in command or "version" in command.lower():
            result.stdout = self.version
        elif "policy" in command:
            result.stdout = "nginx:\n  Installed: 1.24.0\n  Candidate: 1.25.0\n  Version table:"
        elif "nginx -t" in command:
            result.stdout = "nginx: the configuration file /etc/nginx/nginx.conf syntax is ok"
            result.returncode = 0
        elif "dpkg --get-selections" in command:
            result.returncode = 1  # no holds
        elif "find" in command:
            result.stdout = ""
        return result


class TestSurveyEntries(unittest.TestCase):
    """Test survey_entries produces correct records."""

    def test_single_vm_survey(self):
        ssh = MockSSHClient(version="1.24.0", candidate="1.25.0")
        entries = [{"name": "web-01", "ip": "192.0.2.1"}]
        cfg = MagicMock()
        cfg.get.return_value = 5
        cfg.resolve.return_value = Path("/tmp")

        records = survey_entries(ssh, entries, cfg, TOOL_CONFIG)
        self.assertIn("192.0.2.1", records)
        rec = records["192.0.2.1"]
        self.assertIsNotNone(rec["survey"])
        self.assertEqual(rec["survey"]["installed_version"], "1.24.0")
        self.assertEqual(rec["survey"]["candidate_version"], "1.25.0")

    def test_skips_entry_without_ip(self):
        ssh = MockSSHClient()
        entries = [{"name": "no-ip"}, {"name": "vm-1", "ip": "10.0.0.1"}]
        cfg = MagicMock()
        cfg.get.return_value = 5

        records = survey_entries(ssh, entries, cfg, TOOL_CONFIG)
        self.assertNotIn("no-ip", records)
        self.assertIn("10.0.0.1", records)


class TestRenderSummary(unittest.TestCase):
    """Test render_summary output."""

    def test_render_groups_by_verdict(self):
        records = {
            "192.0.2.1": {"survey": {"verdict": "UPGRADE"}, "execution": {}},
            "192.0.2.2": {"survey": {"verdict": "UP_TO_DATE"}, "execution": {}},
            "192.0.2.3": {"survey": {"verdict": "SKIP"}, "execution": {}},
        }
        output = render_summary(records)
        self.assertIn("UPGRADE", output)
        self.assertIn("192.0.2.1", output)
        self.assertIn("Fleet Survey Summary", output)


class TestSummaryData(unittest.TestCase):
    """Test summary_data structured output."""

    def test_summary_data_structure(self):
        records = {
            "192.0.2.1": {"survey": {"verdict": "UPGRADE"}, "execution": {}},
            "192.0.2.2": {"survey": {"verdict": "UP_TO_DATE"}, "execution": {}},
            "192.0.2.3": {"survey": {"verdict": "UPGRADE"}, "execution": {}},
        }
        data = summary_data(records)
        self.assertEqual(data["total"], 3)
        self.assertEqual(len(data["by_verdict"].get("UPGRADE", [])), 2)
        self.assertEqual(len(data["eligible_for_upgrade"]), 2)


if __name__ == "__main__":
    unittest.main()
