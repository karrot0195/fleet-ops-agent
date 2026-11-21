from __future__ import annotations

from pathlib import Path
from typing import Any


def clean_cell(value: Any) -> str:
    """Render a value as a single-line markdown table cell."""
    text = "—" if value is None or value == "" else str(value)
    text = text.replace("\r\n", "; ").replace("\n", "; ").replace("\r", "; ")
    return text.replace("|", "\\|")


def _value(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "none"
    if isinstance(value, dict):
        return ", ".join(f"{key}={_value(item)}" for key, item in value.items()) if value else "none"
    return clean_cell(value)


def _evidence_table(evidence: dict[str, Any]) -> list[str]:
    rows = [
        ("OS", evidence.get("os")),
        ("Distro codename", evidence.get("codename")),
        ("nginx binary", "present" if evidence.get("binary_present") else "absent"),
        ("Installed version", evidence.get("installed_version")),
        ("Candidate version", evidence.get("candidate_version")),
        ("Package origin", evidence.get("package_origin")),
        ("Held packages", evidence.get("held_packages")),
        ("Static modules", (evidence.get("modules") or {}).get("static")),
        ("Dynamic modules", (evidence.get("modules") or {}).get("dynamic")),
        ("Third-party modules", evidence.get("third_party_modules")),
        ("Service active / enabled", f"{_value(evidence.get('service_active'))} / {_value(evidence.get('service_enabled'))}"),
        ("TLS present", evidence.get("tls_present")),
        ("Server blocks", evidence.get("server_blocks")),
        ("Config test", "pass" if evidence.get("config_test_ok") else "fail"),
    ]
    lines = ["| Field | Value |", "|---|---|"]
    lines.extend(f"| {label} | {_value(value)} |" for label, value in rows)
    return lines


def render_record(record: dict[str, Any], run_id: str) -> str:
    lines = [
        f"# {record['name']} ({record['ip']})",
        "",
        f"- Run: `{run_id}`",
        f"- Verdict: **{record.get('verdict')}**",
        f"- Reason: {_value(record.get('reason'))}",
        f"- Surveyed: {_value((record.get('timestamps') or {}).get('surveyed_at'))}",
        "",
    ]
    evidence = record.get("evidence")
    if evidence:
        lines.append("## Survey evidence")
        lines.append("")
        lines.extend(_evidence_table(evidence))
        lines.append("")
    else:
        lines.extend(
            [
                "## Connectivity",
                "",
                "- Result: unreachable",
                f"- Reason: {_value(record.get('reason'))}",
                "- Evidence: none collected",
                "",
            ]
        )

    lines.extend(["## Execution", ""])
    execution = record.get("execution")
    if not execution:
        lines.extend(["- Phase: —", "- State: —"])
    else:
        lines.extend(
            [
                f"- Phase: {_value(execution.get('phase'))}",
                f"- State: {_value(execution.get('state'))}",
            ]
        )
        if execution.get("mode"):
            lines.append(f"- Mode: {_value(execution.get('mode'))}")
        lines.extend(
            [
                f"- Old → new: {_value(execution.get('old_version'))} → {_value(execution.get('new_version'))}",
                f"- Attempts: {_value(execution.get('attempts'))}",
            ]
        )
        backup = record.get("backup")
        if backup:
            lines.append(
                f"- Backup: `{backup.get('local_path')}` (verified, {backup.get('size_bytes')} bytes, "
                f"sha256 `{backup.get('sha256')}`)"
            )
        else:
            lines.append("- Backup: —")
        for step in execution.get("steps", []):
            lines.append(
                f"- Step {step.get('name')}: {'ok' if step.get('ok') else 'failed'} — {_value(step.get('detail'))}"
            )
        if execution.get("error"):
            lines.append(f"- Error: {_value(execution.get('error'))}")
    lines.append("")

    lines.extend(["## Verification", ""])
    verification = (execution or {}).get("verification")
    if verification:
        lines.extend(
            [
                f"- Config test: {'pass' if verification.get('config_ok') else 'fail'}",
                f"- Service active: {_value(verification.get('service_active'))}",
                f"- Version matches candidate: {_value(verification.get('version_matches'))}",
                f"- HTTP status: {_value(verification.get('http_status'))}",
                f"- HTTPS status: {_value(verification.get('https_status'))}",
            ]
        )
    else:
        lines.append("- not run")
    lines.append("")

    lines.extend(["## Drift", ""])
    drift = record.get("drift_flags") or []
    if drift:
        lines.extend(
            f"- {item.get('pattern')} — `{item.get('path')}` — manual review required" for item in drift
        )
    else:
        lines.append("- none")
    lines.append("")

    lines.extend(["## Rollback", ""])
    rollback = record.get("rollback")
    if rollback:
        lines.extend(
            [
                f"- State: {_value(rollback.get('state'))}",
                f"- Pre-rollback archive: {_value(rollback.get('pre_rollback_archive'))}",
                f"- Config test after restore: {'pass' if rollback.get('config_ok') else 'fail'}",
                f"- Service active after restore: {_value(rollback.get('service_active'))}",
                f"- Package version: unchanged at `{_value((record.get('execution') or {}).get('new_version'))}`",
            ]
        )
        if rollback.get("error"):
            lines.append(f"- Error: {_value(rollback.get('error'))}")
    else:
        lines.append("- not requested")
    lines.append("")
    return "\n".join(lines)


def write_record(cfg: Any, record: dict[str, Any], run_id: str) -> Path:
    directory = cfg.resolve("paths.records_dir")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{record['ip']}.md"
    path.write_text(render_record(record, run_id), encoding="utf-8")
    return path
