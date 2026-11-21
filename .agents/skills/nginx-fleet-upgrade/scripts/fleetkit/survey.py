from __future__ import annotations

import shlex
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from . import verdict
from .inventory import utcnow
from .records import clean_cell
from .verdict import parse_apt_policy, parse_load_modules, parse_nginx_v, third_party_modules


def evidence_script(cfg: Any) -> str:
    tool = cfg.tool
    name = shlex.quote(str(tool["name"]))
    package = shlex.quote(str(tool["package"]))
    service = shlex.quote(str(tool["service"]))
    paths = " ".join(shlex.quote(str(path)) for path in tool["config_paths"])
    enabled_paths = " ".join(
        shlex.quote(f"{path}/{leaf}") for path in tool["config_paths"] for leaf in ("sites-enabled", "conf.d")
    )
    lines = [
        "printf '###UID\\n'",
        "id -u 2>/dev/null || true",
        "printf '###OS\\n'",
        "grep '^PRETTY_NAME=' /etc/os-release 2>/dev/null | cut -d= -f2- || true",
        "printf '###CODENAME\\n'",
        "grep '^VERSION_CODENAME=' /etc/os-release 2>/dev/null | cut -d= -f2- || true",
        "printf '###BINARY\\n'",
        f"command -v {name} 2>/dev/null || true",
        "printf '###INSTALLED\\n'",
        f"{tool['version_query']} 2>/dev/null || true",
        "echo",
        "printf '###POLICY\\n'",
        f"apt-cache policy {package} 2>/dev/null || true",
        "printf '###HOLDS\\n'",
        "apt-mark showhold 2>/dev/null || true",
        "printf '###NGINXV\\n'",
        f"{name} -V 2>&1 || true",
        "printf '###LOADMODULES\\n'",
        f"grep -rhE '^[[:space:]]*load_module' {paths} 2>/dev/null || true",
        "printf '###SERVICE_ACTIVE\\n'",
        f"systemctl is-active {service} 2>/dev/null || true",
        "printf '###SERVICE_ENABLED\\n'",
        f"systemctl is-enabled {service} 2>/dev/null || true",
        "printf '###TLS\\n'",
        f"grep -rl 'ssl_certificate' {enabled_paths} 2>/dev/null | head -n 1 || true",
        "printf '###BLOCKS\\n'",
        f"grep -rhoE 'server[[:space:]]*\\{{' {enabled_paths} 2>/dev/null | wc -l || true",
        "printf '###CONFIGTEST\\n'",
        f"{tool['precheck']} 2>&1",
        "printf '###CONFIGTEST_RC:%s\\n' \"$?\"",
        "printf '###END\\n'",
    ]
    return "\n".join(lines) + "\n"


def parse_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("###"):
            marker = line[3:].strip()
            if marker.startswith("CONFIGTEST_RC:"):
                sections.setdefault("CONFIGTEST_RC", []).append(marker.split(":", 1)[1])
                continue
            if marker == "END":
                current = None
                continue
            current = marker
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(line)
    return {key: "\n".join(value).strip() for key, value in sections.items()}


def build_evidence(sections: dict[str, str], cfg: Any) -> dict[str, Any]:
    policy = parse_apt_policy(sections.get("POLICY", ""))
    nginx_v = parse_nginx_v(sections.get("NGINXV", ""))
    dynamic = sorted(set(parse_load_modules(sections.get("LOADMODULES", "")) + nginx_v["dynamic"]))
    modules = {"static": nginx_v["static"], "dynamic": dynamic}
    held = [line.strip() for line in sections.get("HOLDS", "").splitlines() if line.strip()]
    blocks_raw = sections.get("BLOCKS", "0").strip().splitlines()
    try:
        blocks = int(blocks_raw[-1]) if blocks_raw else 0
    except ValueError:
        blocks = 0
    rc_raw = sections.get("CONFIGTEST_RC", "").strip().splitlines()
    config_ok = bool(rc_raw and rc_raw[-1] == "0")
    os_name = sections.get("OS", "").strip().strip('"')
    return {
        "os": os_name or "unknown",
        "codename": sections.get("CODENAME", "").strip() or None,
        "binary_present": bool(sections.get("BINARY", "").strip()),
        "installed_version": sections.get("INSTALLED", "").strip() or None,
        "candidate_version": policy["candidate"],
        "package_origin": policy["origin"],
        "held_packages": held,
        "modules": modules,
        "third_party_modules": third_party_modules(modules, cfg.tool["allowed_dynamic_module_dirs"]),
        "service_active": sections.get("SERVICE_ACTIVE", "").strip() == "active",
        "service_enabled": sections.get("SERVICE_ENABLED", "").strip() == "enabled",
        "tls_present": bool(sections.get("TLS", "").strip()),
        "server_blocks": blocks,
        "config_test_ok": config_ok,
        "privilege": "root" if sections.get("UID", "").strip() == "0" else "sudo",
    }


def empty_record(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": entry["name"],
        "ip": entry["ip"],
        "verdict": None,
        "reason": None,
        "evidence": None,
        "execution": None,
        "backup": None,
        "drift_flags": [],
        "rollback": None,
        "timestamps": {"surveyed_at": None, "executed_at": None, "rolled_back_at": None},
    }


def survey_vm(client: Any, entry: dict[str, Any], cfg: Any, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    record = dict(existing) if existing else empty_record(entry)
    record["name"] = entry["name"]
    record["ip"] = entry["ip"]
    timeout = max(int(cfg.get("ssh.command_timeout")), 120)
    result = client.run(entry["ip"], evidence_script(cfg), timeout=timeout)
    if not result.ok:
        time.sleep(1)
        result = client.run(entry["ip"], evidence_script(cfg), timeout=timeout)
    if not result.ok:
        reason = (result.stderr or result.stdout or f"ssh exit {result.returncode}").strip()
        record.update(
            {
                "verdict": verdict.UNREACHABLE,
                "reason": f"connectivity failed: {reason}",
                "evidence": None,
                "timestamps": {**record["timestamps"], "surveyed_at": utcnow()},
            }
        )
        return record
    evidence = build_evidence(parse_sections(result.stdout), cfg)
    decided, reason = verdict.decide(evidence, cfg)
    record.update(
        {
            "verdict": decided,
            "reason": reason,
            "evidence": evidence,
            "timestamps": {**record["timestamps"], "surveyed_at": utcnow()},
        }
    )
    return record


def survey_entries(
    client: Any,
    entries: list[dict[str, Any]],
    cfg: Any,
    concurrency: int,
    existing: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    existing = existing or {}
    results: dict[str, dict[str, Any]] = {}
    total = len(entries)
    done = 0

    def work(entry: dict[str, Any]) -> dict[str, Any]:
        return survey_vm(client, entry, cfg, existing.get(entry["ip"]))

    def emit(ip: str, record: dict[str, Any]) -> None:
        nonlocal done
        done += 1
        print(f"[{done}/{total}] {ip}: {record.get('verdict') or '—'}", file=sys.stderr, flush=True)

    if concurrency <= 1:
        for entry in entries:
            record = work(entry)
            results[entry["ip"]] = record
            emit(entry["ip"], record)
        return results
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(work, entry): entry["ip"] for entry in entries}
        for future in as_completed(futures):
            ip = futures[future]
            record = future.result()
            results[ip] = record
            emit(ip, record)
    return results


def summary_data(records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    groups = {name: [] for name in verdict.VERDICTS}
    for record in records.values():
        groups.setdefault(record.get("verdict"), []).append(record["ip"])
    ordered = {name: sorted(groups.get(name, [])) for name in verdict.VERDICTS}
    counts = {name: len(ips) for name, ips in ordered.items()}
    return {"groups": ordered, "counts": counts, "eligible": ordered[verdict.UPGRADE]}


def render_summary(records: dict[str, dict[str, Any]]) -> str:
    header = "| Name | IP | Verdict | Installed | Candidate | Reason |"
    divider = "|---|---|---|---|---|---|"
    lines = [header, divider]
    for record in sorted(records.values(), key=lambda item: (item.get("verdict") or "", item["ip"])):
        evidence = record.get("evidence") or {}
        lines.append(
            "| {name} | {ip} | {verdict} | {installed} | {candidate} | {reason} |".format(
                name=clean_cell(record["name"]),
                ip=clean_cell(record["ip"]),
                verdict=clean_cell(record.get("verdict") or "—"),
                installed=clean_cell(evidence.get("installed_version") or "—"),
                candidate=clean_cell(evidence.get("candidate_version") or "—"),
                reason=clean_cell(record.get("reason") or "—"),
            )
        )
    return "\n".join(lines)
