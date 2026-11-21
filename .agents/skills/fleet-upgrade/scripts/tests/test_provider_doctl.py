"""Unit tests for doctl provider."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class TestDoctlProvider(unittest.TestCase):
    """Test DoctlProvider discovery and validation."""

    def _mock_result(self, returncode=0, stdout="", stderr=""):
        result = MagicMock()
        result.returncode = returncode
        result.stdout = stdout
        result.stderr = stderr
        return result

    @patch("subprocess.run")
    def test_validate_success(self, mock_run):
        from fleetkit.providers.doctl import DoctlProvider
        mock_run.return_value = self._mock_result(stdout="default:\n  token: ***")
        prov = DoctlProvider("/tmp")
        self.assertTrue(prov.validate())

    @patch("subprocess.run")
    def test_validate_fail_no_auth(self, mock_run):
        from fleetkit.providers.doctl import DoctlProvider, DiscoveryError
        mock_run.return_value = self._mock_result(returncode=1, stderr="auth failed")
        prov = DoctlProvider("/tmp")
        with self.assertRaises(DiscoveryError):
            prov.validate()

    @patch("subprocess.run")
    def test_discover_parses_json(self, mock_run):
        from fleetkit.providers.doctl import DoctlProvider
        import json
        droplets = [
            {
                "name": "web-01",
                "status": "active",
                "networks": {"v4": [{"type": "public", "ip_address": "192.0.2.1"}]},
            },
            {
                "name": "db-01",
                "status": "active",
                "networks": {"v4": [{"type": "public", "ip_address": "192.0.2.2"}]},
            },
        ]
        result = MagicMock()
        result.returncode = 0
        result.stdout = json.dumps(droplets)
        result.stderr = ""
        mock_run.return_value = result

        prov = DoctlProvider("/tmp")
        entries = prov.discover()
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["ip"], "192.0.2.1")
        self.assertEqual(entries[1]["ip"], "192.0.2.2")

    def test_reconcile_computes_added_removed(self):
        from fleetkit.providers.doctl import DoctlProvider
        prev = [{"ip": "1.1.1.1"}, {"ip": "2.2.2.2"}]
        curr = [{"ip": "2.2.2.2"}, {"ip": "3.3.3.3"}]
        added, removed = DoctlProvider.reconcile(None, prev, curr)
        self.assertEqual(added, ["3.3.3.3"])
        self.assertEqual(removed, ["1.1.1.1"])


if __name__ == "__main__":
    unittest.main()
