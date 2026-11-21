"""Unit tests for IP validation, file parsing, and reconciliation."""

from __future__ import annotations

import tempfile
import unittest

from fleetkit.inventory import (
    InventoryError,
    parse_ip_file,
    reconcile,
    validate_ip,
    write_ip_file,
)


class TestValidateIP(unittest.TestCase):
    """Test IPv4 address validation."""

    def test_valid_ips(self):
        self.assertEqual(validate_ip("192.168.1.1"), "192.168.1.1")
        self.assertEqual(validate_ip("10.0.0.1"), "10.0.0.1")
        self.assertEqual(validate_ip("0.0.0.0"), "0.0.0.0")
        self.assertEqual(validate_ip("255.255.255.255"), "255.255.255.255")

    def test_invalid_ips(self):
        invalid = ["", "256.1.1.1", "abc.def.ghi.jkl", "192.168.1", "192.168.1.1.1"]
        for ip in invalid:
            with self.assertRaises(InventoryError):
                validate_ip(ip)


class TestParseIpFile(unittest.TestCase):
    """Test CSV file parsing."""

    def test_parse_simple_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Name,IP\nweb-01,192.0.2.1\nweb-02,192.0.2.2\n")
            f.flush()
            entries = parse_ip_file(f.name)
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0]["ip"], "192.0.2.1")
            self.assertEqual(entries[1]["ip"], "192.0.2.2")

    def test_parses_comments_and_empty_lines(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("# Comment\nName,IP\n\nweb-01,192.0.2.1\n# Another comment\n")
            f.flush()
            entries = parse_ip_file(f.name)
            self.assertEqual(len(entries), 1)

    def test_deduplicates_by_ip(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Name,IP\nweb-01,192.0.2.1\nweb-02,192.0.2.1\n")
            f.flush()
            entries = parse_ip_file(f.name)
            self.assertEqual(len(entries), 1)

    def test_skips_invalid_ips(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Name,IP\nweb-01,192.0.2.1\nbad-guy,999.999.999.999\n")
            f.flush()
            entries = parse_ip_file(f.name)
            self.assertEqual(len(entries), 1)

    def test_missing_file_returns_empty(self):
        import os
        path = "/tmp/nonexistent_inventory_test_xyz_12345.txt"
        entries = parse_ip_file(path)
        self.assertEqual(entries, [])


class TestWriteIpFile(unittest.TestCase):
    """Test writing inventory to CSV file."""

    def test_write_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/ip.txt"
            entries = [{"name": "vm-1", "ip": "10.0.0.2"}, {"name": "vm-2", "ip": "10.0.0.1"}]
            result = write_ip_file(path, entries)
            self.assertTrue(result.exists())
            lines = result.read_text().splitlines()
            self.assertEqual(lines[0], "Name,IP")
            # Should be sorted by IP
            self.assertIn("10.0.0.1", lines[1])


class TestReconcile(unittest.TestCase):
    """Test added/removed IP computation."""

    def test_all_added(self):
        prev = [{"ip": "1.1.1.1"}]
        curr = [{"ip": "2.2.2.2"}]
        added, removed = reconcile({"inventory": {"entries": prev}}, curr, "doctl")
        self.assertEqual(added, ["2.2.2.2"])
        self.assertEqual(removed, ["1.1.1.1"])

    def test_no_changes(self):
        entry = [{"ip": "1.1.1.1"}]
        added, removed = reconcile({"inventory": {"entries": entry}}, list(entry), "doctl")
        self.assertEqual(added, [])
        self.assertEqual(removed, [])

    def test_new_entry_only(self):
        prev = []
        curr = [{"ip": "1.1.1.1"}, {"ip": "2.2.2.2"}]
        added, removed = reconcile({"inventory": {"entries": prev}}, curr, "manual")
        self.assertEqual(len(added), 2)
        self.assertEqual(removed, [])


if __name__ == "__main__":
    unittest.main()
