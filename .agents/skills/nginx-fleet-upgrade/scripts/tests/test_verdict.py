import unittest

from fleetkit.verdict import (
    BLOCKED,
    SKIP,
    UNREACHABLE,
    UPGRADE,
    UP_TO_DATE,
    compare_versions,
    decide,
    parse_apt_policy,
    parse_nginx_v,
    third_party_modules,
)
from tests.helpers import FleetCase


def evidence(**overrides):
    base = {
        "os": "Ubuntu 22.04",
        "binary_present": True,
        "installed_version": "1.18.0-1",
        "candidate_version": "1.24.0-1",
        "package_origin": "http://archive.ubuntu.com/ubuntu jammy/main amd64 Packages",
        "held_packages": [],
        "modules": {"static": ["http_ssl"], "dynamic": []},
        "third_party_modules": [],
        "service_active": True,
        "service_enabled": True,
        "tls_present": False,
        "server_blocks": 2,
        "config_test_ok": True,
        "privilege": "root",
    }
    base.update(overrides)
    return base


class VersionTests(unittest.TestCase):
    def test_ordering(self):
        self.assertLess(compare_versions("1.0~rc1", "1.0"), 0)
        self.assertGreater(compare_versions("1:1.0-1", "1.0"), 0)
        self.assertLess(compare_versions("1.0-1", "1.0-2"), 0)
        self.assertGreater(compare_versions("1.0a", "1.0"), 0)
        self.assertEqual(compare_versions("1.0-1", "1.0-1"), 0)
        self.assertGreater(compare_versions("1.0-1ubuntu1", "1.0-1"), 0)


class ParserTests(unittest.TestCase):
    def test_apt_policy(self):
        text = """
nginx:
  Installed: 1.18.0-6ubuntu14.4
  Candidate: 1.24.0-1ubuntu1
  Version table:
 *** 1.18.0-6ubuntu14.4 500
        500 http://archive.ubuntu.com/ubuntu jammy-updates/main amd64 Packages
        100 /var/lib/dpkg/status
"""
        parsed = parse_apt_policy(text)
        self.assertEqual(parsed["installed"], "1.18.0-6ubuntu14.4")
        self.assertEqual(parsed["candidate"], "1.24.0-1ubuntu1")
        self.assertIn("archive.ubuntu.com", parsed["origin"])

    def test_apt_policy_origin_prefers_candidate_entry(self):
        text = """
nginx:
  Installed: 1.18.0-1
  Candidate: 1.24.0-1
  Version table:
     1.24.0-1 900
        900 https://nginx.org/packages/ubuntu noble/nginx amd64 Packages
 *** 1.18.0-1 500
        500 http://archive.ubuntu.com/ubuntu jammy/main amd64 Packages
        100 /var/lib/dpkg/status
"""
        parsed = parse_apt_policy(text)
        self.assertIn("nginx.org", parsed["origin"])

    def test_policy_none_candidate(self):
        parsed = parse_apt_policy("nginx:\n  Installed: 1.0\n  Candidate: (none)\n")
        self.assertIsNone(parsed["candidate"])

    def test_nginx_v_and_third_party(self):
        parsed = parse_nginx_v("configure arguments: --with-http_ssl_module --add-dynamic-module=/opt/mod.so")
        self.assertEqual(parsed["static"], ["http_ssl"])
        self.assertEqual(parsed["dynamic"], ["/opt/mod.so"])
        self.assertEqual(third_party_modules(parsed, ["/usr/lib/nginx/modules"]), ["/opt/mod.so"])


class VerdictTests(FleetCase):
    def test_skip_when_not_installed(self):
        cfg = self.config()
        self.assertEqual(decide(evidence(binary_present=False, installed_version=None), cfg)[0], SKIP)

    def test_blocked_config_test(self):
        self.assertEqual(decide(evidence(config_test_ok=False), self.config())[0], BLOCKED)

    def test_blocked_hold(self):
        verdict, reason = decide(evidence(held_packages=["nginx"]), self.config())
        self.assertEqual(verdict, BLOCKED)
        self.assertIn("held", reason)

    def test_blocked_source_build(self):
        verdict, reason = decide(evidence(installed_version=None, package_origin=None), self.config())
        self.assertEqual(verdict, BLOCKED)
        self.assertIn("source build", reason)

    def test_blocked_unexpected_origin(self):
        verdict, reason = decide(evidence(package_origin="http://nginx.example.com/packages/ubuntu"), self.config())
        self.assertEqual(verdict, BLOCKED)
        self.assertIn("unexpected package source", reason)

    def test_blocked_third_party_module(self):
        self.assertEqual(decide(evidence(third_party_modules=["/opt/x.so"]), self.config())[0], BLOCKED)

    def test_blocked_no_candidate(self):
        verdict, reason = decide(evidence(candidate_version=None), self.config())
        self.assertEqual(verdict, BLOCKED)
        self.assertIn("no candidate", reason)

    def test_up_to_date(self):
        self.assertEqual(decide(evidence(installed_version="1.24.0-1"), self.config())[0], UP_TO_DATE)

    def test_upgrade(self):
        self.assertEqual(decide(evidence(), self.config())[0], UPGRADE)

    def test_unreachable_is_handled_by_survey(self):
        self.assertEqual(UNREACHABLE, "UNREACHABLE")

    def config(self):
        from fleetkit.config import load_config

        return load_config(self.root)
