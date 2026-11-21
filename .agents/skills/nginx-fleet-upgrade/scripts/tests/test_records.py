import unittest

from fleetkit.records import render_record


def base_record():
    return {
        "name": "vm",
        "ip": "10.0.0.1",
        "verdict": "UPGRADE",
        "reason": None,
        "evidence": {
            "os": "Ubuntu 22.04",
            "binary_present": True,
            "installed_version": "1.18.0-1",
            "candidate_version": "1.24.0-1",
            "package_origin": "http://archive.ubuntu.com/ubuntu",
            "held_packages": [],
            "modules": {"static": ["http_ssl"], "dynamic": []},
            "third_party_modules": [],
            "service_active": True,
            "service_enabled": True,
            "tls_present": False,
            "server_blocks": 2,
            "config_test_ok": True,
            "privilege": "root",
        },
        "execution": {
            "phase": "canary",
            "state": "SUCCEEDED",
            "steps": [{"name": "upgrade", "ok": True, "detail": "apt upgrade completed"}],
            "old_version": "1.18.0-1",
            "new_version": "1.24.0-1",
            "verification": {
                "config_ok": True,
                "service_active": True,
                "version_matches": True,
                "http_status": 200,
                "https_status": None,
            },
            "attempts": 1,
            "error": None,
        },
        "backup": {
            "local_path": "backups/10.0.0.1/nginx-1.tar.gz",
            "size_bytes": 100,
            "sha256": "a" * 64,
            "verified": True,
        },
        "drift_flags": [{"pattern": "*.dpkg-dist", "path": "/etc/nginx/nginx.conf.dpkg-dist", "needs_manual_review": True}],
        "rollback": None,
        "timestamps": {"surveyed_at": "2026-01-01T00:00:00Z", "executed_at": "2026-01-01T00:01:00Z", "rolled_back_at": None},
    }


class RecordTests(unittest.TestCase):
    def test_reachable_record_sections(self):
        text = render_record(base_record(), "run-1")
        for heading in ("## Survey evidence", "## Execution", "## Verification", "## Drift", "## Rollback"):
            self.assertIn(heading, text)
        self.assertIn("1.18.0-1 → 1.24.0-1", text)
        self.assertIn("HTTP status: 200", text)
        self.assertIn("manual review required", text)
        self.assertIn("nginx.conf.dpkg-dist", text)

    def test_unreachable_record_has_connectivity_not_evidence(self):
        record = base_record()
        record.update({"verdict": "UNREACHABLE", "reason": "connectivity failed: timeout", "evidence": None})
        record["execution"] = None
        text = render_record(record, "run-1")
        self.assertIn("## Connectivity", text)
        self.assertNotIn("## Survey evidence", text)
        self.assertIn("connectivity failed: timeout", text)

    def test_rollback_section(self):
        record = base_record()
        record["execution"]["state"] = "ROLLED_BACK"
        record["rollback"] = {
            "state": "SUCCEEDED",
            "pre_rollback_archive": "/var/backups/nginx-pre-rollback-1.tar.gz",
            "config_ok": True,
            "service_active": True,
            "at": "2026-01-01T00:02:00Z",
        }
        text = render_record(record, "run-1")
        self.assertIn("State: SUCCEEDED", text)
        self.assertIn("Package version: unchanged", text)
