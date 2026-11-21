"""Execution engine — canary + serial fleet rollout with retry-once."""

from __future__ import annotations

import shlex
import time
from pathlib import Path
from typing import Any

from .ssh import SSHClient, SSHError


class ExecuteError(Exception):
    exit_code = 3


def validate_approvals(
    records: dict[str, Any],
    approved_ips: list[str],
    tool_config: dict[str, Any],
) -> None:
    """Check that all approved IPs have UPGRADE verdict. Refuse otherwise."""
    tool_name = tool_config.get("tool", {}).get("name", "")
    for ip in approved_ips:
        key = f"{ip}:{tool_name}" if tool_name else ip
        rec = records.get(key, {})
        survey = rec.get("survey", {})
        verdict = survey.get("verdict", "")
        # Strip reason part for comparison
        base_verdict = verdict.split("(")[0] if "(" in verdict else verdict
        if base_verdict != "UPGRADE":
            raise ExecuteError(f"IP {ip} has verdict {verdict} — must be UPGRADE to approve")


def _do_upgrade(ssh: SSHClient, ip: str, config: Any, tool_config: dict[str, Any]) -> dict[str, Any]:
    """Perform a single upgrade on one VM. Returns result dict."""
    tool = tool_config.get("tool", {})
    package = tool.get("package", "")
    version_query = tool.get("version_query", "")
    precheck_cmd = tool.get("precheck", "")
    service = tool.get("service", "")
    upgrade_cmd = tool.get("upgrade_command")

    if not upgrade_cmd:
        upgrade_cmd = (
            'DEBIAN_FRONTEND=noninteractive apt-get install --only-upgrade {package} '
            '-o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold"'
        ).format(package=package)

    old_version_result = ssh.run(ip, version_query, check=False)
    old_version = old_version_result.stdout.strip() if old_version_result.ok else ""

    # Run upgrade
    upgrade_result = ssh.run(ip, upgrade_cmd.format(package=package), need_privilege=True, check=False)
    if not upgrade_result.ok:
        return {"state": "FAILED", "old_version": old_version, "new_version": None,
                "error": upgrade_result.stderr.strip()}

    # Verify post-upgrade
    verify_result = ssh.run(ip, precheck_cmd, check=False)
    new_ver_result = ssh.run(ip, version_query, check=False)
    new_version = new_ver_result.stdout.strip() if new_ver_result.ok else ""

    return {
        "state": "SUCCEEDED",
        "old_version": old_version,
        "new_version": new_version,
        "postcheck_ok": verify_result.ok,
    }


def execute_canary(
    store: Any,
    client: SSHClient,
    config: Any,
    tool_config: dict[str, Any],
    approved_ips: list[str],
) -> dict[str, Any]:
    """Execute canary rollout on a single VM.

    Returns summary dict with state of each executed VM.
    """
    if len(approved_ips) > 1:
        approved_ips = [approved_ips[0]]  # Canary is one VM only

    results: dict[str, Any] = {}
    for ip in approved_ips:
        try:
            res = _do_upgrade(client, ip, config, tool_config)
            res["phase"] = "canary"
            results[ip] = res

            # Store record
            tool_name = tool_config.get("tool", {}).get("name", "")
            key = f"{ip}:{tool_name}" if tool_name else ip
            record = store.record_for_ip(ip) or {"ip": ip, "tool": tool_name}
            record["execution"] = res
            store.set_record(record)
            store.save()

        except SSHError as exc:
            results[ip] = {"state": "FAILED", "phase": "canary", "error": str(exc)}
    return results


def execute_fleet(
    store: Any,
    client: SSHClient,
    config: Any,
    tool_config: dict[str, Any],
    approved_ips: list[str],
) -> dict[str, Any]:
    """Execute serial fleet rollout — one VM at a time with one retry round.

    Returns summary dict with state of each executed VM.
    """
    results: dict[str, Any] = {}

    for ip in approved_ips:
        attempts = 0
        max_attempts = 2  # initial + one retry
        final_state = "FAILED"

        while attempts < max_attempts:
            try:
                res = _do_upgrade(client, ip, config, tool_config)
                final_state = res["state"]
                break
            except SSHError:
                pass
            attempts += 1

        tool_name = tool_config.get("tool", {}).get("name", "")
        key = f"{ip}:{tool_name}" if tool_name else ip

        record = store.record_for_ip(ip) or {"ip": ip, "tool": tool_name}
        record["execution"] = {
            "state": final_state,
            "phase": "fleet",
            "attempts": attempts + 1,
            "ip": ip,
        }
        store.set_record(record)
        store.save()
        results[ip] = {"state": final_state, "phase": "fleet", "attempts": attempts + 1}

    return results
