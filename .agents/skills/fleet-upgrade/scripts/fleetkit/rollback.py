"""Full rollback — restore config + reinstall old package version."""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .backup import verify_backup
from .ssh import SSHClient, SSHError


class RollbackError(Exception):
    exit_code = 3


@dataclass
class RollbackResult:
    state: str          # SUCCEEDED, FAILED, REFUSED
    config_ok: bool
    package_ok: bool
    service_active: bool
    error: str | None = None


def rollback_vm(
    client: SSHClient,
    config: Any,
    tool_config: dict[str, Any],
    record: dict[str, Any],
) -> dict[str, Any]:
    """Perform full rollback on a single VM.

    Steps:
      1. Restore config from verified backup archive.
      2. Reinstall old package version.
      3. Run precheck to verify.
      4. Restart service.

    Returns dict with keys: state, config_ok, package_ok, service_active, error.
    """
    result = {"state": "REFUSED", "config_ok": False, "package_ok": False,
              "service_active": False, "error": None}

    exec_data = record.get("execution", {})
    backup_path = exec_data.get("backup_path")
    backup_checksum = exec_data.get("backup_checksum")
    old_version = exec_data.get("old_version")
    package = tool_config.get("tool", {}).get("package", "")
    service = tool_config.get("tool", {}).get("service", "")
    precheck_cmd = tool_config.get("tool", {}).get("precheck", "")
    ip = record.get("ip", "")

    if not backup_path or not backup_checksum:
        result["error"] = "no verified backup found; cannot rollback"
        return result

    # Step 1: Verify backup checksum
    if not verify_backup(backup_path, backup_checksum):
        result["error"] = "backup checksum mismatch — refusing rollback"
        return result

    # Step 2: Restore config from backup
    restore_cmd = f"tar -xzf {shlex.quote(backup_path)} -C /"
    restore_result = client.run(ip, restore_cmd, need_privilege=True, check=False)
    config_ok = restore_result.ok

    # Step 3: Reinstall old version
    if old_version:
        pin_cmd = (
            f"DEBIAN_FRONTEND=noninteractive apt-get install -y {package}={old_version} "
            '-o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold"'
        )
        pin_result = client.run(ip, pin_cmd, need_privilege=True, check=False)
        package_ok = pin_result.ok
    else:
        package_ok = False

    # Step 4: Precheck and restart service
    precheck_result = client.run(ip, precheck_cmd, check=False)
    service_ok = precheck_result.ok

    # Try to restart service if it failed
    if not service_ok and service:
        restart = client.run(ip, f"systemctl restart {service}", need_privilege=True, check=False)
        if restart.ok:
            precheck_result = client.run(ip, precheck_cmd, check=False)
            service_ok = precheck_result.ok

    if config_ok and package_ok and service_ok:
        result["state"] = "SUCCEEDED"
    else:
        errors = []
        if not config_ok:
            errors.append("config restore failed")
        if not package_ok:
            errors.append("package reinstallation failed")
        if not service_ok:
            errors.append("service not active after rollback")
        result["error"] = "; ".join(errors)
        result["state"] = "FAILED"

    result["config_ok"] = config_ok
    result["package_ok"] = package_ok
    result["service_active"] = service_ok

    return result


def dry_run_plan(record: dict[str, Any]) -> dict[str, Any]:
    """Show what rollback would do without executing."""
    exec_data = record.get("execution", {})
    backup_path = exec_data.get("backup_path")
    old_version = exec_data.get("old_version")
    package = record.get("tool", "unknown")

    plan_lines = [f"Rollback plan for {record.get('ip', 'unknown')}:"]
    if backup_path:
        plan_lines.append(f"  1. Restore config from: {backup_path}")
    else:
        plan_lines.append("  1. ERROR: No backup path found")
    if old_version:
        plan_lines.append(f"  2. Reinstall {package}={old_version}")
    else:
        plan_lines.append("  2. INFO: No old version recorded — manual intervention needed")
    plan_lines.append("  3. Run precheck")
    plan_lines.append("  4. Restart service")
    return {"plan": plan_lines}
