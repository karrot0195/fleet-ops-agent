"""Unit tests for report generation."""

from __future__ import annotations

import tempfile
import unittest


class TestRenderReport(unittest.TestCase):
    """Test report rendering output."""

    def test_render_report_format(self):
        from fleetkit.report import render_report
        records = {
            "192.0.2.1:nginx": {
                "ip": "192.0.2.1",
                "tool": "nginx",
                "survey": {"verdict": "UPGRADE", "installed_version": "1.24.0"},
                "execution": {"state": "SUCCEEDED", "new_version": "1.25.0"},
            },
            "192.0.2.2:nginx": {
                "ip": "192.0.2.2",
                "tool": "nginx",
                "survey": {"verdict": "SKIP", "installed_version": None},
                "execution": {"state": "PENDING"},
            },
        }
        output = render_report(records)
        self.assertIn("Fleet Upgrade Report", output)
        self.assertIn("192.0.2.1", output)
        self.assertIn("Summary", output)
        self.assertIn("Total VMs surveyed", output)

    def test_report_with_empty_records(self):
        from fleetkit.report import render_report
        output = render_report({})
        self.assertIn("Fleet Upgrade Report", output)


class TestReportRows(unittest.TestCase):
    """Test report_rows structured data."""

    def test_report_rows_structure(self):
        from fleetkit.report import report_rows
        records = {
            "192.0.2.1:nginx": {
                "ip": "192.0.2.1",
                "tool": "nginx",
                "survey": {"verdict": "UPGRADE", "installed_version": "1.24.0"},
                "execution": {"state": "SUCCEEDED", "new_version": "1.25.0"},
            },
        }
        rows = report_rows(records)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["verdict"], "UPGRADE")
        self.assertEqual(rows[0]["state"], "SUCCEEDED")


class TestLogSummary(unittest.TestCase):
    """Test log summary generation."""

    def test_log_summary_generation(self):
        from fleetkit.report import log_summary
        records = {
            "192.0.2.1:nginx": {"tool": "nginx", "execution": {"state": "SUCCEEDED"}},
            "192.0.2.2:nginx": {"tool": "nginx", "execution": {"state": "FAILED"}},
        }
        title, summary = log_summary(records, "run-001")
        self.assertEqual(title, "Fleet Upgrade: nginx")
        self.assertIn("2 VMs", summary)
        self.assertIn("run-001", summary)


class TestAppendLog(unittest.TestCase):
    """Test LOGS.md append-only behavior."""

    def test_append_creates_new_file(self):
        from fleetkit.report import append_log
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            path = f.name
        try:
            append_log(path, "Test Entry", "Test summary")
            content = open(path).read()
            self.assertIn("## Test Entry", content)
            self.assertIn("Test summary", content)
        finally:
            import os
            if os.path.exists(path):
                os.unlink(path)

    def test_append_no_duplicate(self):
        from fleetkit.report import append_log
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# Log\n\n## Test Entry\n\nFirst entry\n\n")
            path = f.name
        try:
            append_log(path, "Test Entry", "Duplicate should be skipped")
            content = open(path).read()
            # Should still only have one ## Test Entry
            count = content.count("## Test Entry")
            self.assertEqual(count, 1)
        finally:
            import os
            if os.path.exists(path):
                os.unlink(path)


if __name__ == "__main__":
    unittest.main()
