"""Read-only fleet survey — audit each VM for tool upgrade eligibility."""

from __future__ import annotations

import fnmatch
import shlex
from pathlib import Path
from typing import Any

from .ssh import SSHClient, SSHError
from .verdict import compute_verdict


class SurveyError(Exception):
    exit_code = 3


def _check_origin(ssh: SSHClient, ip: str, package: str, patterns: list[str]) -> bool:
    """Check whether package origin matches allowed origin patterns.

    Returns True if all packages come from allowed origins, or patterns is empty.
    """
    if not patterns:
        return True
    result = ssh.run(ip, f"apt-cache policy {shlex.quote(package)}", check=False)
    if not result.ok:
        return False  # If we can't check, be conservative
    output = result.stdout.lower()
    for pattern in patterns:
        if pattern.lower() in output:
            return True
    return len(patterns) == 0


def _check_holds(ssh: SSHClient, ip: str, patterns: list[str]) -> bool:
    """Check whether any package matching hold_patterns is on hold.

    Returns True if a hold is detected.
    """
    if not patterns:
        return False
    result = ssh.run(ip, "dpkg --get-selections | grep -E 'hold$'", check=False)
    if not result.ok:
        return False
    for pattern in patterns:
        if fnmatch.fnmatch(pattern, "*"):
            # Simple wildcard match — scan holds for any that match
            lines = result.stdout.strip().splitlines()
            for line in lines:
                pkg_name = line.split()[0] if line.split() else ""
                if fnmatch.fnmatch(pkg_name, pattern):
                    return True
    return False


def _check_drift(ssh: SSHClient, ip: str, patterns: list[str], config_paths: list[str]) -> list[str]:
    """Scan config paths for drift files matching patterns.

    Returns list of drift file paths found.
    """
    if not patterns:
        return []
    drift_files: list[str] = []
    escape_cmd = " && ".join(
        shlex.quote(f"test -d '{p}' || echo 'SKIP'") for p in config_paths
    )
    search_cmd = " && ".join(
        shlex.quote(f"find '{p}' -maxdepth 2 -name '{pat}' 2>/dev/null") for pat in patterns for p in config_paths
    )
    combined = f"( {escape_cmd} ); {search_cmd}"
    result = ssh.run(ip, combined, check=False)
    if result.ok and result.stdout.strip():
        drift_files = [f for f in result.stdout.strip().splitlines() if f.strip()]
    return drift_files


def survey_entries(
    client: SSHClient,
    entries: list[dict[str, Any]],
    config: Any,
    tool_config: dict[str, Any],
    concurrency: int = 4,
    records_dir: str | None = None,
) -> dict[str, Any]:
    """Run read-only audit for every VM entry.

    Returns a dict mapping IP → record with survey results.
    Each record contains: verdict, installed_version, candidate_version,
    precheck_ok, origin_ok, hold_detected, drift_files, evidence.
    """
    tool = tool_config.get("tool", {})
    package = tool.get("package", "")
    version_query = tool.get("version_query", "")
    precheck_cmd = tool.get("precheck", "")
    allowed_origins = tool.get("allowed_origin_patterns", [])
    hold_pats = tool.get("hold_patterns", [])
    drift_pats = tool.get("drift_patterns", [])
    config_paths = tool.get("config_paths", [])

    results: dict[str, Any] = {}

    for entry in entries:
        ip = entry.get("ip", "")
        if not ip:
            continue

        rec = {"ip": ip, "tool": tool_config.get("tool", {}).get("name", ""), "survey": {}, "execution": {}}

        try:
            # 1. Query installed version
            ver_result = client.run(ip, version_query, check=False)
            installed = ver_result.stdout.strip() if ver_result.ok else ""

            # 2. Check for available upgrades
            pkg_result = client.run(ip, f"apt-cache policy {shlex.quote(package)}", check=False)
            candidate = ""
            if pkg_result.ok:
                out = pkg_result.stdout
                # Look for "Candidate:" line
                for line in out.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("Candidate:"):
                        parts = stripped.split(":", 1)
                        if len(parts) > 1:
                            candidate = parts[1].strip()
                        break

            # 3. Run precheck
            precheck_result = client.run(ip, precheck_cmd, check=False)
            precheck_ok = precheck_result.ok

            # 4. Check origin
            origin_ok = _check_origin(client, ip, package, allowed_origins)

            # 5. Check holds
            hold_detected = _check_holds(client, ip, hold_pats)

            # 6. Scan for drift
            drift_files = _check_drift(client, ip, drift_pats, config_paths)

            # Build ssh_result dict for verdict computation
            ssh_result = {
                "installed_version": installed,
                "candidate_version": candidate,
                "precheck_ok": precheck_ok,
                "origin_ok": origin_ok,
                "hold_detected": hold_detected,
                "unreachable": False,
                "error": None,
            }

            verdict = compute_verdict(tool_config, ssh_result)

            evidence_parts = [
                f"$ {version_query}",
                ver_result.stdout or "(no output)",
                "",
                f"$ {precheck_cmd}",
                ("OK" if precheck_ok else "FAILED") + f"\n{precheck_result.stderr or ''}"[:200],
            ]

            rec["survey"] = {
                "verdict": verdict,
                "installed_version": installed or None,
                "candidate_version": candidate or None,
                "precheck_ok": precheck_ok,
                "origin_ok": origin_ok,
                "hold_detected": hold_detected,
                "drift_files": drift_files,
                "evidence": "\n".join(evidence_parts),
            }
            rec["execution"] = {"state": "PENDING"}

        except SSHError as exc:
            rec["survey"] = {
                "verdict": "UNREACHABLE(connection failed after retry)",
                "installed_version": None,
                "candidate_version": None,
                "precheck_ok": False,
                "origin_ok": False,
                "hold_detected": False,
                "drift_files": [],
                "evidence": str(exc),
            }
            rec["execution"] = {"state": "PENDING"}

        results[ip] = rec

    return results


def render_summary(records: dict[str, Any]) -> str:
    """Render a human-readable summary of survey results.

    Groups records by verdict and lists eligible VMs.
    """
    groups: dict[str, list[str]] = {}
    for ip, rec in records.items():
        verdict = (rec.get("survey") or {}).get("verdict", "UNKNOWN")
        groups.setdefault(verdict, []).append(ip)

    lines: list[str] = []
    lines.append("# Fleet Survey Summary\n")
    lines.append("| Verdict | Count | VMs |\n")
    lines.append("|---------|-------|-----|\n")
    for verdict in ("UPGRADE", "UP-TO-DATE", "SKIP", "BLOCKED", "UNREACHABLE"):
        ips = groups.get(verdict, [])
        lines.append(f"| {verdict} | {len(ips)} | {', '.join(ips) or '-'} |\n")

    return "\n".join(lines)


def summary_data(records: dict[str, Any]) -> dict[str, Any]:
    """Return structured summary data suitable for downstream consumers."""
    groups: dict[str, list[str]] = {}
    for ip, rec in records.items():
        verdict = (rec.get("survey") or {}).get("verdict", "UNKNOWN")
        groups.setdefault(verdict, []).append(ip)
    return {
        "total": len(records),
        "by_verdict": {k: v for k, v in sorted(groups.items())},
        "eligible_for_upgrade": groups.get("UPGRADE", []),
    }
