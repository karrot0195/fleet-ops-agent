import json
import unittest

from fleetkit.config import load_config
from fleetkit.migration import bootstrap_script, migration_eligible, repo_active
from tests.helpers import FleetCase


class MigrationScriptTests(FleetCase):
    def test_bootstrap_script_contents(self):
        cfg = load_config(self.root)
        script = bootstrap_script(cfg)
        self.assertIn("https://nginx.org/keys/nginx_signing.key", script)
        self.assertIn("573BFD6B3D8FBC641079A6ABABF5BD827BD9BF62", script)
        self.assertIn(
            "deb [signed-by=/usr/share/keyrings/nginx-archive-keyring.gpg] "
            "https://nginx.org/packages/ubuntu noble nginx",
            script,
        )
        self.assertIn("Pin-Priority: 900", script)
        self.assertIn("/etc/apt/sources.list.d/nginx.list", script)
        self.assertIn("/etc/apt/preferences.d/99nginx", script)
        self.assertIn("conf.d/default.conf", script)
        self.assertIn("apt-get update -q", script)
        self.assertIn("curl gnupg ca-certificates", script)
        self.assertNotIn("--only-upgrade", script)

    def test_bootstrap_script_without_stub(self):
        self.update_config(**{"migration.stub_default_conf": False})
        cfg = load_config(self.root)
        self.assertNotIn("default.conf", bootstrap_script(cfg))

    def test_migration_disabled_refuses(self):
        cfg = load_config(self.root)
        record = {
            "verdict": "UP-TO-DATE",
            "evidence": {"codename": "questing", "binary_present": True, "config_test_ok": True},
        }
        self.assertEqual(migration_eligible(record, cfg), "migration disabled in config")

    def test_eligibility_rules(self):
        self.update_config(**{"migration.enabled": True})
        self.update_config(**{"migration.apply_to_dists": ["questing"]})
        cfg = load_config(self.root)
        base = {
            "verdict": "UP-TO-DATE",
            "evidence": {
                "codename": "questing",
                "binary_present": True,
                "config_test_ok": True,
                "held_packages": [],
                "third_party_modules": [],
            },
        }
        self.assertIsNone(migration_eligible(base, cfg))
        bionic = {**base, "evidence": {**base["evidence"], "codename": "bionic"}}
        self.assertIn("not in migration.apply_to_dists", migration_eligible(bionic, cfg))
        origin_blocked = {**base, "verdict": "BLOCKED"}
        self.assertIsNone(migration_eligible(origin_blocked, cfg))
        skipped = {**base, "verdict": "SKIP"}
        self.assertIn("verdict SKIP", migration_eligible(skipped, cfg))
        held = {**base, "evidence": {**base["evidence"], "held_packages": ["nginx"]}}
        self.assertIn("package held", migration_eligible(held, cfg))
        module = {**base, "evidence": {**base["evidence"], "third_party_modules": ["/opt/mod.so"]}}
        self.assertIn("third-party module", migration_eligible(module, cfg))
        bad_config = {**base, "evidence": {**base["evidence"], "config_test_ok": False}}
        self.assertIn("configuration test failed", migration_eligible(bad_config, cfg))

    def test_repo_active_detection(self):
        self.assertTrue(
            repo_active(
                "nginx:\n  Installed: 1.28.0-6ubuntu1.8\n  Candidate: 1.30.7-1~noble\n  Version table:\n"
                "     1.30.7-1~noble 900\n"
                "        900 https://nginx.org/packages/ubuntu noble/nginx amd64 Packages\n"
                " *** 1.28.0-6ubuntu1.8 500\n"
                "        500 http://archive.ubuntu.com/ubuntu questing-updates/main amd64 Packages\n"
                "        100 /var/lib/dpkg/status"
            )
        )
        self.assertFalse(
            repo_active(
                "nginx:\n  Installed: 1.28.0-6ubuntu1.8\n  Candidate: 1.28.0-6ubuntu1.8\n  Version table:\n"
                " *** 1.28.0-6ubuntu1.8 500\n"
                "        500 http://archive.ubuntu.com/ubuntu questing-updates/main amd64 Packages\n"
                "        100 /var/lib/dpkg/status"
            )
        )
        self.assertFalse(repo_active(""))


class MigrateFlowTests(FleetCase):
    def configure(self):
        questing = {
            "codename": "questing",
            "installed_version": "1.28.0-6ubuntu1.8",
            "candidate_version": "1.28.0-6ubuntu1.8",
            "origin": "https://nginx.org/packages/ubuntu noble/nginx amd64 Packages",
            "repo_candidate_version": "1.30.7-1~noble",
        }
        self.update_vm("10.0.0.1", **questing)
        self.update_vm("10.0.0.2", **questing)
        self.update_config(**{"migration.enabled": True})
        self.update_config(**{"migration.apply_to_dists": ["questing"]})
        self.audit()

    def setUp(self):
        super().setUp()
        self.configure()

    def state(self):
        return json.loads((self.root / ".fleet" / "state.json").read_text(encoding="utf-8"))

    def migrate_canary(self, ip="10.0.0.1", *extra):
        return self.run_json(
            "execute", "--phase", "canary", "--mode", "migrate", "--approve", ",".join([ip, *extra]), "--yes"
        )

    def test_migrate_requires_yes(self):
        code, _, _ = self.run_json(
            "execute", "--phase", "canary", "--mode", "migrate", "--approve", "10.0.0.1"
        )
        self.assertEqual(code, 3)
        self.assertEqual(self.state()["approvals"], [])

    def test_migrate_refuses_held_package(self):
        self.update_vm("10.0.0.3", codename="questing")
        self.audit()
        code, payload, stderr = self.migrate_canary("10.0.0.3")
        self.assertEqual(code, 3)
        self.assertIn("package held", payload["error"]["message"])
        self.assertFalse(self.applied_path.exists())

    def test_migrate_refuses_foreign_distro(self):
        self.update_vm("10.0.0.1", codename="bionic")
        self.audit()
        code, payload, stderr = self.migrate_canary("10.0.0.1")
        self.assertEqual(code, 3)
        self.assertIn("not in migration.apply_to_dists", payload["error"]["message"])
        self.assertFalse(self.applied_path.exists())

    def test_distro_mode_still_refuses_up_to_date(self):
        code, payload, stderr = self.run_json(
            "execute", "--phase", "canary", "--approve", "10.0.0.1", "--yes"
        )
        self.assertEqual(code, 3)
        self.assertIn("UP-TO-DATE", payload["error"]["message"])

    def test_migrate_dry_run(self):
        before = (self.root / ".fleet" / "state.json").read_text(encoding="utf-8")
        self.log_path.unlink(missing_ok=True)
        code, payload, stderr = self.run_json(
            "execute", "--phase", "canary", "--mode", "migrate", "--approve", "10.0.0.1", "--dry-run"
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(payload["data"][0]["ip"], "10.0.0.1")
        self.assertEqual(payload["data"][0]["mode"], "migrate")
        self.assertTrue(any("bootstrap nginx.org repo" in item for item in payload["data"][0]["commands"]))
        self.assertEqual(before, (self.root / ".fleet" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(self.commands(), [])
        self.assertFalse(self.applied_path.exists())

    def test_migrate_canary_succeeds(self):
        code, payload, stderr = self.migrate_canary()
        self.assertEqual(code, 0, stderr)
        record = self.state()["records"]["10.0.0.1"]
        self.assertEqual(record["execution"]["state"], "SUCCEEDED")
        self.assertEqual(record["execution"]["mode"], "migrate")
        self.assertEqual(record["execution"]["new_version"], "1.30.7-1~noble")
        self.assertEqual([step["name"] for step in record["execution"]["steps"]], [
            "backup",
            "precheck",
            "bootstrap",
            "upgrade",
            "restart",
            "verify",
            "drift",
        ])
        self.assertTrue(record["backup"]["verified"])
        commands = self.commands()
        self.assertTrue(any("nginx-archive-keyring.gpg" in item for item in commands))
        self.assertTrue(any("sources.list.d/nginx.list" in item for item in commands))
        self.assertTrue(any("apt-get install -y nginx" in item for item in commands))
        self.assertFalse(any("--only-upgrade" in item for item in commands))
        self.assertTrue(self.applied_path.exists())
        record_text = (self.root / "plan" / "10.0.0.1.md").read_text(encoding="utf-8")
        self.assertIn("Mode: migrate", record_text)
        self.assertIn("1.30.7-1~noble", record_text)

    def test_migrate_canary_idempotent_guard(self):
        self.migrate_canary()
        code, payload, stderr = self.migrate_canary()
        self.assertEqual(code, 3)
        self.assertIn("canary already completed", payload["error"]["message"])

    def test_bootstrap_failure_fails_vm(self):
        self.update_vm("10.0.0.1", bootstrap_ok=False)
        code, _, _ = self.migrate_canary()
        self.assertEqual(code, 4)
        record = self.state()["records"]["10.0.0.1"]
        self.assertEqual(record["execution"]["state"], "FAILED")
        self.assertIn("repo migration bootstrap failed", record["execution"]["error"])
        self.assertFalse(self.applied_path.exists())
        self.assertFalse(any("apt-get install -y nginx" in item for item in self.commands()))

    def test_migrate_fleet_flow(self):
        code, _, stderr = self.migrate_canary()
        self.assertEqual(code, 0, stderr)
        code, _, stderr = self.run_json("gate", "--decision", "proceed", "--note", "canary healthy")
        self.assertEqual(code, 0, stderr)
        code, payload, stderr = self.run_json(
            "execute", "--phase", "fleet", "--mode", "migrate", "--approve", "10.0.0.1,10.0.0.2", "--yes"
        )
        self.assertEqual(code, 0, stderr)
        records = self.state()["records"]
        self.assertEqual(records["10.0.0.1"]["execution"]["phase"], "canary")
        self.assertEqual(records["10.0.0.2"]["execution"]["phase"], "fleet")
        self.assertEqual(records["10.0.0.2"]["execution"]["mode"], "migrate")
        self.assertEqual(records["10.0.0.2"]["execution"]["new_version"], "1.30.7-1~noble")
        rerun, payload, stderr = self.run_json(
            "execute", "--phase", "fleet", "--mode", "migrate", "--approve", "10.0.0.1,10.0.0.2", "--yes"
        )
        self.assertEqual(rerun, 0, stderr)
        self.assertEqual(payload["data"]["records"], [])

    def test_migrate_fleet_still_requires_proceed_gate(self):
        self.migrate_canary()
        self.run_json("gate", "--decision", "stop")
        code, payload, stderr = self.run_json(
            "execute", "--phase", "fleet", "--mode", "migrate", "--approve", "10.0.0.1,10.0.0.2", "--yes"
        )
        self.assertEqual(code, 3)
        self.assertIn("proceed", payload["error"]["message"])
        self.assertNotIn("10.0.0.2", self.applied_path.read_text(encoding="utf-8").split())


if __name__ == "__main__":
    unittest.main()
