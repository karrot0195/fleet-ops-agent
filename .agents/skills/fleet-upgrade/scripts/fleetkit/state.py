"""State store for run tracking, per-VM records, gates, and approvals."""

from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class StateError(Exception):
    exit_code = 2


SCHEMA_VERSION = 1


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)


def empty_state(tool: str = "", provider: str = "", inventory: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    now = utcnow()
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": new_run_id(),
        "started_at": now,
        "tool": tool,
        "provider": provider,
        "inventory": {
            "captured_at": now,
            "source": provider or "unknown",
            "entries": list(inventory) if inventory else [],
            "added": [],
            "removed": [],
        },
        "records": {},
        "gates": [],
        "report": {"written_at": None, "logged_at": None},
    }


class StateStore:
    """Manages ``.fleet/state.json`` — source of truth for all run state."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root).expanduser().resolve()
        state_dir = self.root / ".fleet"
        self.dir = state_dir
        self.path = state_dir / "state.json"
        self.data: dict[str, Any] = empty_state()
        self.loaded = False

    def exists(self) -> bool:
        return self.path.is_file()

    def load(self) -> dict[str, Any]:
        if not self.path.is_file():
            self.data = empty_state()
            self.loaded = False
            return self.data
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise StateError(f"cannot read state {self.path}: {exc}") from exc
        if not isinstance(data, dict):
            raise StateError(f"state {self.path} must contain an object")
        if data.get("schema_version") != SCHEMA_VERSION:
            raise StateError(
                f"unsupported state schema {data.get('schema_version')!r}; expected {SCHEMA_VERSION}"
            )
        self.data = data
        self.loaded = True
        return data

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.data["updated_at"] = utcnow()
        payload = json.dumps(self.data, indent=2, sort_keys=True) + "\n"
        fd, tmp_name = tempfile.mkstemp(dir=str(self.dir), prefix=".state-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.chmod(tmp_name, 0o600)
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    # -- record helpers -------------------------------------------------------

    @property
    def records(self) -> dict[str, Any]:
        return self.data["records"]

    def record_for_ip(self, ip: str, tool: str = "") -> dict[str, Any] | None:
        """Return record keyed by ``{ip}:{tool}``. Falls back to bare IP when tool is empty."""
        key = f"{ip}:{tool}" if tool else ip
        rec = self.data["records"].get(key)
        if rec is None and tool:
            rec = self.data["records"].get(ip)
        return rec

    def set_record(self, record: dict[str, Any]) -> None:
        """Save a VMRecord under its ``{ip}:{tool}`` key."""
        ip = record["ip"]
        t = record.get("tool", "")
        key = f"{ip}:{t}" if t else ip
        self.data["records"][key] = record

    def canary_records(self, tool: str = "") -> list[dict[str, Any]]:
        return [
            r for r in self.data["records"].values()
            if isinstance(r.get("execution"), dict) and r["execution"].get("phase") == "canary"
        ]

    # -- gate helpers ---------------------------------------------------------

    def add_gate(self, decision: str, note: str | None = None, phase: str = "canary") -> dict[str, Any]:
        gate = {
            "decision": decision,
            "decided_at": utcnow(),
            "note": note,
            "phase": phase,
        }
        self.data["gates"].append(gate)
        return gate

    def last_gate(self, phase: str | None = None) -> dict[str, Any] | None:
        gates = self.data["gates"]
        if not gates:
            return None
        if phase:
            gates = [g for g in gates if g.get("phase") == phase]
            if not gates:
                return None
        return gates[-1]

    # -- inventory helpers ----------------------------------------------------

    def get_inventory_entries(self) -> list[dict[str, Any]]:
        return self.data["inventory"].get("entries", [])
