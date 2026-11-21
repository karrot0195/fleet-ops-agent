from __future__ import annotations

import json
import os
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


def empty_state() -> dict[str, Any]:
    now = utcnow()
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": new_run_id(),
        "created_at": now,
        "updated_at": now,
        "inventory": {
            "captured_at": now,
            "source": "doctl",
            "entries": [],
            "added": [],
            "removed": [],
        },
        "records": {},
        "approvals": [],
        "gates": [],
        "report": {"written_at": None, "logged_at": None},
    }


class StateStore:
    def __init__(self, state_dir: str | os.PathLike[str]) -> None:
        self.dir = Path(state_dir)
        self.path = self.dir / "state.json"
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
            data = json.loads(self.path.read_text(encoding="utf-8"))
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

    @property
    def records(self) -> dict[str, Any]:
        return self.data["records"]

    def record(self, ip: str) -> dict[str, Any] | None:
        return self.data["records"].get(ip)

    def set_record(self, record: dict[str, Any]) -> None:
        self.data["records"][record["ip"]] = record

    def add_approval(self, ips: list[str], excluded: list[str], note: str | None = None) -> dict[str, Any]:
        approval = {
            "approved_ips": list(dict.fromkeys(ips)),
            "excluded_ips": list(dict.fromkeys(excluded)),
            "approved_at": utcnow(),
            "note": note,
        }
        self.data["approvals"].append(approval)
        return approval

    def add_gate(self, decision: str, note: str | None = None) -> dict[str, Any]:
        gate = {"decision": decision, "decided_at": utcnow(), "note": note}
        self.data["gates"].append(gate)
        return gate

    def last_gate(self) -> dict[str, Any] | None:
        return self.data["gates"][-1] if self.data["gates"] else None

    def canary_records(self) -> list[dict[str, Any]]:
        return [
            record
            for record in self.data["records"].values()
            if isinstance(record.get("execution"), dict) and record["execution"].get("phase") == "canary"
        ]

    def record_for_ip(self, ip: str) -> dict[str, Any]:
        record = self.data["records"].get(ip)
        if record is None:
            raise StateError(f"no record for {ip}; run discover and survey first")
        return record
