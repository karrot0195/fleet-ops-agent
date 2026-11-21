import unittest

from tests.helpers import FleetCase


class ConfigCliTests(FleetCase):
    def test_init_refuses_overwrite(self):
        code, payload, stderr = self.run_json("config", "--init")
        self.assertEqual(code, 2)
        self.assertIn("already exists", payload["error"]["message"])

    def test_init_force_rewrites(self):
        code, payload, stderr = self.run_json("config", "--init", "--force")
        self.assertEqual(code, 0, stderr)
        self.assertTrue((self.root / ".specific" / "nginx-fleet.yaml").is_file())

    def test_doctor(self):
        code, stdout, stderr = self.run_cli("doctor")
        self.assertEqual(code, 0, stderr)
        self.assertIn("doctl auth: ok", stdout)
        self.assertIn("ssh env:", stdout)

    def test_doctor_fails_without_doctl_auth(self):
        self.write_scenario({**self.load_scenario(), "doctl_auth": False})
        code, stdout, stderr = self.run_cli("doctor")
        self.assertEqual(code, 5)
        self.assertIn("doctl auth failed", stderr)
