import unittest

from fleetkit.config import load_config
from fleetkit.ssh import CommandResult
from fleetkit.survey import build_evidence, parse_sections, summary_data, survey_vm
from tests.helpers import FleetCase


class FakeClient:
    def __init__(self, result):
        self.result = result
        self.commands = []

    def run(self, ip, command, **kwargs):
        self.commands.append((ip, command, kwargs))
        return self.result


class SurveyTests(FleetCase):
    def test_parse_sections(self):
        text = "###UID\n0\n###OS\nUbuntu\n###CONFIGTEST_RC:0\n###END\n"
        sections = parse_sections(text)
        self.assertEqual(sections["UID"], "0")
        self.assertEqual(sections["OS"], "Ubuntu")
        self.assertEqual(sections["CONFIGTEST_RC"], "0")

    def test_build_evidence(self):
        cfg = load_config(self.root)
        text = "\n".join(
            [
                "###UID", "0",
                "###OS", '"Ubuntu 22.04"',
                "###BINARY", "/usr/sbin/nginx",
                "###INSTALLED", "1.18.0-1",
                "###POLICY", "nginx:", "  Installed: 1.18.0-1", "  Candidate: 1.24.0-1",
                " *** 1.18.0-1 500", "        500 http://archive.ubuntu.com/ubuntu jammy/main amd64 Packages",
                "###HOLDS", "",
                "###NGINXV", "--with-http_ssl_module",
                "###LOADMODULES", "load_module /usr/lib/nginx/modules/ngx.so;",
                "###SERVICE_ACTIVE", "active",
                "###SERVICE_ENABLED", "enabled",
                "###TLS", "",
                "###BLOCKS", "3",
                "###CONFIGTEST", "ok",
                "###CONFIGTEST_RC:0",
                "###END",
            ]
        )
        evidence = build_evidence(parse_sections(text), cfg)
        self.assertTrue(evidence["binary_present"])
        self.assertEqual(evidence["candidate_version"], "1.24.0-1")
        self.assertEqual(evidence["server_blocks"], 3)
        self.assertTrue(evidence["config_test_ok"])
        self.assertEqual(evidence["modules"]["dynamic"], ["/usr/lib/nginx/modules/ngx.so"])

    def test_survey_vm_unreachable(self):
        cfg = load_config(self.root)
        client = FakeClient(CommandResult(["ssh"], 255, "", "connection refused"))
        record = survey_vm(client, {"name": "vm", "ip": "10.0.0.4"}, cfg)
        self.assertEqual(record["verdict"], "UNREACHABLE")
        self.assertIsNone(record["evidence"])
        self.assertIn("connection refused", record["reason"])

    def test_summary_groups(self):
        records = {
            "10.0.0.1": {"ip": "10.0.0.1", "verdict": "UPGRADE"},
            "10.0.0.2": {"ip": "10.0.0.2", "verdict": "UP-TO-DATE"},
            "10.0.0.3": {"ip": "10.0.0.3", "verdict": "UPGRADE"},
        }
        data = summary_data(records)
        self.assertEqual(data["eligible"], ["10.0.0.1", "10.0.0.3"])
        self.assertEqual(data["counts"]["UP-TO-DATE"], 1)
