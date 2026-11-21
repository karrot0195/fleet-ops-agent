"""Report generation — human-readable markdown, wiki output, LOGS.md append."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ReportError(Exception):
    exit_code = 3


def render_report(records: dict[str, Any]) -> str:
    """Generate human-readable markdown report with per-VM before/after versions.

    Returns the rendered markdown string.
    """
    lines = [
        "# Fleet Upgrade Report",
        "",
        f"**Generated**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "| IP | Tool | Verdict | Old Version | New Version | State |",
        "|----|------|---------|-------------|-------------|-------|",
    ]

    for key, rec in sorted(records.items()):
        survey = rec.get("survey", {})
        exec_data = rec.get("execution", {})
        ip = rec.get("ip", key)
        tool = rec.get("tool", key.split(":")[1] if ":" in key else "?")
        verdict = survey.get("verdict", "N/A")
        old_ver = survey.get("installed_version", "N/A") or "N/A"
        new_ver = exec_data.get("new_version", "N/A") or "N/A"
        state = exec_data.get("state", "PENDING")

        lines.append(f"| {ip} | {tool} | {verdict} | {old_ver} | {new_ver} | {state} |")

    lines.append("")

    # Summary section
    by_verdict: dict[str, list] = {}
    for rec in records.values():
        v = (rec.get("survey") or {}).get("verdict", "UNKNOWN")
        by_verdict.setdefault(v, []).append(rec.get("ip", ""))

    lines.append("## Summary")
    lines.append("")
    total = len(records)
    lines.append(f"**Total VMs surveyed**: {total}")
    lines.append("")
    for verdict, ips in sorted(by_verdict.items()):
        lines.append(f"- **{verdict}**: {len(ips)}")

    lines.append("")
    return "\n".join(lines)


def report_rows(records: dict[str, Any]) -> list[dict[str, Any]]:
    """Return structured data suitable for programmatic consumption."""
    rows = []
    for key, rec in records.items():
        survey = rec.get("survey", {})
        exec_data = rec.get("execution", {})
        row = {
            "ip": rec.get("ip", key),
            "tool": rec.get("tool", key.split(":")[1] if ":" in key else "?"),
            "verdict": survey.get("verdict", "N/A"),
            "installed_version": survey.get("installed_version"),
            "candidate_version": survey.get("candidate_version"),
            "old_version": exec_data.get("old_version"),
            "new_version": exec_data.get("new_version"),
            "state": exec_data.get("state", "PENDING"),
        }
        rows.append(row)
    return rows


def log_summary(records: dict[str, Any], run_id: str = "") -> tuple[str, str]:
    """Generate title and summary for LOGS.md entry.

    Returns (title, summary).
    """
    total = len(records)
    upgraded = sum(1 for r in records.values() if (r.get("execution") or {}).get("state") == "SUCCEEDED")
    failed = sum(1 for r in records.values() if (r.get("execution") or {}).get("state") == "FAILED")

    tool = "?"
    for rec in records.values():
        t = rec.get("tool", "")
        if t:
            tool = t
            break

    title = f"Fleet Upgrade: {tool}"
    summary = f"Run {run_id or '—'}: {total} VMs, {upgraded} succeeded, {failed} failed."
    return title, summary


def append_log(log_path: str | Path, title: str, summary: str) -> None:
    """Append an entry to LOGS.md (append-only, no duplicates check).

    Each entry is formatted as:
    ## {title}

    {summary}

    ---
    """
    log_file = Path(log_path)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    entry = f"\n## {title}\n\n{summary}\n\n---\n\n"

    if log_file.exists():
        content = log_file.read_text(encoding="utf-8")
        # Basic dedup: skip if same title already exists
        if f"## {title}" in content:
            return  # Don't duplicate
        content += entry
    else:
        content = f"# Change Log\n\n{entry}"

    log_file.write_text(content, encoding="utf-8")


def write_wiki_report(
    records: dict[str, Any],
    tool_name: str,
    run_id: str,
    wiki_dir: str | Path,
) -> Path:
    """Write report to wiki/fleet-reports/{YYYY-MM-DD}-{tool}.md."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_file = Path(wiki_dir) / "fleet-reports" / f"{now}-{tool_name}.md"
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(render_report(records), encoding="utf-8")
    return report_file
