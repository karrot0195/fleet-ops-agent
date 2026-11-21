import json
import tempfile
import unittest
from pathlib import Path

from fleetkit.state import SCHEMA_VERSION, StateStore, StateError, empty_state


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / ".fleet"

    def tearDown(self):
        self.tmp.cleanup()

    def test_roundtrip(self):
        store = StateStore(self.dir)
        store.load()
        store.data["run_id"] = "20260101T000000Z-abcdef"
        store.save()
        again = StateStore(self.dir)
        again.load()
        self.assertEqual(again.data["run_id"], "20260101T000000Z-abcdef")
        self.assertEqual(again.data["schema_version"], SCHEMA_VERSION)

    def test_unsupported_schema(self):
        self.dir.mkdir(parents=True)
        (self.dir / "state.json").write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
        with self.assertRaises(StateError):
            StateStore(self.dir).load()

    def test_record_helpers(self):
        store = StateStore(self.dir)
        store.load()
        store.set_record({"ip": "10.0.0.1", "name": "a"})
        self.assertEqual(store.record_for_ip("10.0.0.1")["name"], "a")
        with self.assertRaises(StateError):
            store.record_for_ip("10.0.0.9")

    def test_new_state_shape(self):
        data = empty_state()
        self.assertEqual(data["records"], {})
        self.assertEqual(data["report"], {"written_at": None, "logged_at": None})
