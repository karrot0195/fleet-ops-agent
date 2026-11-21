from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .backup import sha256_file
from .ssh import SSHError
from .state import utcnow


class RollbackError(Exception):
    exit_code = 4


def dry_run_plan(cfg: Any, record: dict[str, Any]) -> dict[str, Any]:
    name = str(cfg.tool["name"])
    service = str(cfg.tool["service"])
    paths = " ".join(str(path) for path in cfg.tool["config_paths"])
    backup = record.get("backup") or {}
    return {
        "ip": record["ip"],
        "commands": [
            f"scp {backup.get('local_path', '<backup>')} <user>@{record['ip']}:/tmp/{name}-rollback-<timestamp>.tar.gz",
            f"tar czf /var/backups/{name}-pre-rollback-<timestamp>.tar.gz {paths}",
            f"tar xzf /tmp/{name}-rollback-<timestamp>.tar.gz -C /",
            str(cfg.tool["precheck"]),
            f"systemctl restart {service}",
        ],
    }


def rollback_vm(client: Any, cfg: Any, record: dict[str, Any]) -> dict[str, Any]:
    backup = record.get("backup") or {}
    if not backup.get("verified"):
        raise RollbackError(f"{record['ip']} has no verified backup")
    local = Path(str(backup.get("local_path")))
    if not local.is_file() or local.stat().st_size <= 0:
        raise RollbackError(f"verified backup missing on disk: {local}")
    expected = backup.get("sha256")
    if expected and sha256_file(local) != expected:
        raise RollbackError(f"backup checksum mismatch: {local}")
    execution = record.get("execution") or {}
    if execution.get("state") not in {"FAILED", "ROLLED_BACK"}:
        raise RollbackError(f"{record['ip']} is not in a failed state")

    name = str(cfg.tool["name"])
    service = str(cfg.tool["service"])
    timestamp = int(time.time())
    remote = f"/tmp/{name}-rollback-{timestamp}.tar.gz"
    pre_rollback = f"/var/backups/{name}-pre-rollback-{timestamp}.tar.gz"
    paths = " ".join(str(path) for path in cfg.tool["config_paths"])

    try:
        uploaded = client.upload(record["ip"], local, remote)
    except SSHError as exc:
        return {
            "state": "FAILED",
            "pre_rollback_archive": "",
            "config_ok": False,
            "service_active": False,
            "at": utcnow(),
            "error": f"upload failed: {exc}",
        }
    if not uploaded.ok:
        return {
            "state": "FAILED",
            "pre_rollback_archive": "",
            "config_ok": False,
            "service_active": False,
            "at": utcnow(),
            "error": f"upload failed: {(uploaded.stderr or '').strip()}",
        }

    archived = client.run(record["ip"], f"tar czf {pre_rollback} {paths}", need_privilege=True)
    if not archived.ok:
        return {
            "state": "FAILED",
            "pre_rollback_archive": pre_rollback,
            "config_ok": False,
            "service_active": False,
            "at": utcnow(),
            "error": f"pre-rollback archive failed: {(archived.stderr or '').strip()}",
        }

    restored = client.run(record["ip"], f"tar xzf {remote} -C /", need_privilege=True)
    if not restored.ok:
        return {
            "state": "FAILED",
            "pre_rollback_archive": pre_rollback,
            "config_ok": False,
            "service_active": False,
            "at": utcnow(),
            "error": f"restore failed: {(restored.stderr or '').strip()}",
        }

    precheck = client.run(record["ip"], str(cfg.tool["precheck"]), need_privilege=True)
    service_active = False
    if precheck.ok:
        client.run(record["ip"], f"systemctl restart {service}", need_privilege=True)
        status = client.run(record["ip"], f"systemctl is-active {service}")
        service_active = (status.stdout or "").strip() == "active"

    state = "SUCCEEDED" if precheck.ok and service_active else "FAILED"
    result = {
        "state": state,
        "pre_rollback_archive": pre_rollback,
        "config_ok": precheck.ok,
        "service_active": service_active,
        "at": utcnow(),
    }
    if state == "FAILED":
        result["error"] = (precheck.stderr or precheck.stdout or "config test failed after restore").strip()
    return result
