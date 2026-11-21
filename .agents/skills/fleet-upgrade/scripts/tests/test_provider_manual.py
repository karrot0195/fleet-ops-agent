"""Unit tests for manual provider."""

from __future__ import annotations

import tempfile
import unittest

from fleetkit.providers.manual import ManualProvider, DiscoveryError


class TestManualProvider(unittest.TestCase):
    """Test manual file-based provider."""

    def _create_inventory_file(self, content):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
        f.write(content)
        f.flush()
        return f.name

    def test_validate_missing_file_raises(self):
        import os
        orig_cwd = os.getcwd()
        try:
            os.chdir(tempfile.gettempdir())
            prov = ManualProvider("/tmp")
            with self.assertRaises(DiscoveryError):
                prov.validate()
        finally:
            os.chdir(orig_cwd)

    def test_discover_reads_csv(self):
        import os
        orig_cwd = os.getcwd()
        try:
            tmpdir = tempfile.mkdtemp()
            ip_path = os.path.join(tmpdir, "ip.txt")
            with open(ip_path, "w") as f:
                f.write("Name,IP\nweb-01,192.0.2.1\nweb-02,192.0.2.2\n")
            os.chdir(tmpdir)
            prov = ManualProvider(tmpdir)
            entries = prov.discover()
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0]["name"], "web-01")
            self.assertEqual(entries[0]["ip"], "192.0.2.1")
        finally:
            os.chdir(orig_cwd)

    def test_discover_skips_invalid_ips(self):
        import os
        orig_cwd = os.getcwd()
        try:
            tmpdir = tempfile.mkdtemp()
            ip_path = os.path.join(tmpdir, "ip.txt")
            with open(ip_path, "w") as f:
                f.write("Name,IP\nvalid,192.0.2.1\ninvalid,999.0.0.1\nbad,abc.def\n")
            os.chdir(tmpdir)
            prov = ManualProvider(tmpdir)
            entries = prov.discover()
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["ip"], "192.0.2.1")
        finally:
            os.chdir(orig_cwd)

    def test_discover_deduplicates(self):
        import os
        orig_cwd = os.getcwd()
        try:
            tmpdir = tempfile.mkdtemp()
            ip_path = os.path.join(tmpdir, "ip.txt")
            with open(ip_path, "w") as f:
                f.write("Name,IP\nvm-1,192.0.2.1\nvm-2,192.0.2.1\n")
            os.chdir(tmpdir)
            prov = ManualProvider(tmpdir)
            entries = prov.discover()
            self.assertEqual(len(entries), 1)
        finally:
            os.chdir(orig_cwd)

    def test_reconcile_computes_changes(self):
        prev = [{"ip": "1.1.1.1"}, {"ip": "2.2.2.2"}]
        curr = [{"ip": "2.2.2.2"}, {"ip": "3.3.3.3"}]
        added, removed = ManualProvider.reconcile(None, prev, curr)
        self.assertEqual(added, ["3.3.3.3"])
        self.assertEqual(removed, ["1.1.1.1"])


if __name__ == "__main__":
    unittest.main()
