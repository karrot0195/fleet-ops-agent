from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .records import clean_cell


def _cell(value: Any) -> str:
    return clean_cell(value)


def report_rows(records: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in sorted(records.values(), key=lambda item: (item["name"], item["ip"])):
        execution = record.get("execution") or {}
        verification = execution.get("verification") or {}
        drift = record.get("drift_flags") or []
        rows.append(
            {
                "name": record["name"],
                "ip": record["ip"],
                "verdict": record.get("verdict"),
                "old_version": execution.get("old_version"),
                "new_version": execution.get("new_version"),
                "state": execution.get("state"),
                "backup": (record.get("backup") or {}).get("local_path"),
                "config_ok": verification.get("config_ok"),
                "service_active": verification.get("service_active"),
                "http_status": verification.get("http_status"),
                "https_status": verification.get("https_status"),
                "drift": len(drift),
                "rollback": (record.get("rollback") or {}).get("state"),
            }
        )
    return rows


def render_report(records: dict[str, dict[str, Any]]) -> str:
    rows = report_rows(records)
    lines = [
        "| Name | IP | Verdict | Old → New | State | Backup | Config | Service | HTTP | HTTPS | Drift | Rollback |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {name} | {ip} | {verdict} | {old} → {new} | {state} | {backup} | {config} | {service} | {http} | {https} | {drift} | {rollback} |".format(
                name=_cell(row["name"]),
                ip=_cell(row["ip"]),
                verdict=_cell(row["verdict"]),
                old=_cell(row["old_version"]),
                new=_cell(row["new_version"]),
                state=_cell(row["state"]),
                backup=_cell(row["backup"]),
                config=_cell(row["config_ok"]),
                service=_cell(row["service_active"]),
                http=_cell(row["http_status"]),
                https=_cell(row["https_status"]),
                drift=row["drift"],
                rollback=_cell(row["rollback"]),
            )
        )
    if not rows:
        lines.append("| — | — | — | — | — | — | — | — | — | — | — | — |")
    return "\n".join(lines)


def log_summary(records: dict[str, dict[str, Any]], run_id: str) -> tuple[str, str]:
    rows = report_rows(records)
    processed = [row for row in rows if row["state"]]
    succeeded = sum(1 for row in processed if row["state"] == "SUCCEEDED")
    failed = sum(1 for row in processed if row["state"] == "FAILED")
    rolled_back = sum(1 for row in processed if row["state"] == "ROLLED_BACK")
    drift = sum(1 for row in rows if row["drift"])
    if processed:
        summary = (
            f"Processed {len(processed)} VM(s): {succeeded} succeeded, {failed} failed, "
            f"{rolled_back} rolled back; drift flags on {drift} VM(s)."
        )
    else:
        verdicts = {}
        for row in rows:
            verdicts[row["verdict"]] = verdicts.get(row["verdict"], 0) + 1
        detail = ", ".join(f"{count} {name}" for name, count in sorted(verdicts.items()))
        summary = f"Audited {len(rows)} VM(s): {detail or 'none'}."
    return f"nginx fleet upgrade {run_id}", summary


def append_log(path: str | Path, title: str, summary: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    if existing and not existing.endswith("\n\n"):
        existing += "\n"
    stamp = time.strftime("%Y-%m-%d %H:%M")
    target.write_text(existing + f"{stamp}: {title}\n{summary}\n", encoding="utf-8")
