import unittest

from fleetkit.inventory import (
    DiscoveryError,
    parse_doctl_json,
    parse_ip_file,
    reconcile,
    render_ip_file,
)
from fleetkit.state import empty_state


class InventoryTests(unittest.TestCase):
    def test_parse_sort_dedupe(self):
        entries = parse_ip_file("bravo,10.0.0.2\nalpha,10.0.0.1\nalpha-dup,10.0.0.1\n")
        self.assertEqual([entry["name"] for entry in entries], ["alpha", "bravo"])
        self.assertEqual(render_ip_file(entries), "alpha,10.0.0.1\nbravo,10.0.0.2\n")

    def test_invalid_line(self):
        with self.assertRaises(DiscoveryError):
            parse_ip_file("alpha 10.0.0.1\n")

    def test_invalid_ip(self):
        with self.assertRaises(DiscoveryError):
            parse_ip_file("alpha,999.1.1.1\n")

    def test_doctl_active_public_only(self):
        raw = """
        [
          {"name":"a","status":"active","networks":{"v4":[{"type":"public","ip_address":"10.0.0.1"}]}},
          {"name":"b","status":"off","networks":{"v4":[{"type":"public","ip_address":"10.0.0.2"}]}},
          {"name":"c","status":"active","networks":{"v4":[{"type":"private","ip_address":"10.0.0.3"}]}}
        ]
        """
        entries = parse_doctl_json(raw)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["name"], "a")

    def test_reconcile_add_remove_and_preserve_first_seen(self):
        state = empty_state()
        state["inventory"]["entries"] = [
            {"name": "old", "ip": "10.0.0.9", "status": "active", "first_seen": "2020-01-01T00:00:00Z", "last_seen": "2020-01-01T00:00:00Z"},
            {"name": "kept", "ip": "10.0.0.1", "status": "active", "first_seen": "2020-01-01T00:00:00Z", "last_seen": "2020-01-01T00:00:00Z"},
        ]
        state["records"] = {"10.0.0.9": {"ip": "10.0.0.9"}, "10.0.0.1": {"ip": "10.0.0.1"}}
        added, removed = reconcile(
            state,
            [{"name": "kept", "ip": "10.0.0.1", "status": "active"}, {"name": "new", "ip": "10.0.0.2", "status": "active"}],
            "file",
        )
        self.assertEqual(added, ["10.0.0.2"])
        self.assertEqual(removed, ["10.0.0.9"])
        self.assertNotIn("10.0.0.9", state["records"])
        kept = next(entry for entry in state["inventory"]["entries"] if entry["ip"] == "10.0.0.1")
        self.assertEqual(kept["first_seen"], "2020-01-01T00:00:00Z")
