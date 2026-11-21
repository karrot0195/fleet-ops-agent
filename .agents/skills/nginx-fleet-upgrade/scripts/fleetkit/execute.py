from __future__ import annotations

import copy
import fnmatch
import shlex
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .backup import BackupError, create_backup
from .migration import (
    MigrationError,
    bootstrap_script,
    migration_eligible,
    policy_command,
    repo_active,
)
from .records import write_record
from .ssh import SSHError
from .state import utcnow
from .survey import parse_sections
from .verdict import compare_versions, parse_apt_policy


class ApprovalError(Exception):
    exit_code = 3


class ExecutionError(Exception):
    exit_code = 4


def _new_execution(phase: str, old_version: str | None, attempt: int) -> dict[str, Any]:
    return {
        "phase": phase,
        "state": "RUNNING",
        "steps": [],
        "old_version": old_version,
        "new_version": None,
        "verification": None,
        "attempts": attempt,
        "error": None,
    }


def _step(name: str, ok: bool, started: str, detail: str) -> dict[str, Any]:
    return {
        "name": name,
        "ok": ok,
        "started_at": started,
        "finished_at": utcnow(),
        "detail": str(detail)[:2000],
    }


def _fail(
    execution: dict[str, Any],
    record: dict[str, Any],
    name: str,
    started: str,
    detail: str,
    error: str,
) -> dict[str, Any]:
    execution["steps"].append(_step(name, False, started, detail))
    execution["state"] = "FAILED"
    execution["error"] = error
    record["execution"] = execution
    record["timestamps"]["executed_at"] = utcnow()
    return record


def _probe_status(value: str | None) -> int | None:
    value = (value or "").strip()
    if value.isdigit() and 100 <= int(value) <= 599:
        return int(value)
    return None


def verify_script(cfg: Any, tls_present: bool) -> str:
    tool = cfg.tool
    precheck = str(tool["precheck"])
    service = shlex.quote(str(tool["service"]))
    version_query = str(tool["version_query"])
    paths = " ".join(shlex.quote(str(path)) for path in tool["config_paths"])
    patterns = [str(item) for item in tool["drift_patterns"]]
    expression = " -o ".join(f"-name {shlex.quote(pattern)}" for pattern in patterns)
    lines = [
        "printf '###PRECHECK\\n'",
        f"{precheck} 2>&1",
        "rc=$?",
        "printf '###PRECHECK_RC\\n'",
        'echo "$rc"',
        "printf '###ACTIVE\\n'",
        f"systemctl is-active {service} 2>/dev/null || true",
        "printf '###VERSION\\n'",
        f"{version_query} 2>/dev/null || true",
        "echo",
    ]
    http_block = tool["verify"]["http"]
    if http_block["enabled"]:
        base_url = str(http_block["url"])
        # Strip trailing slash to reuse host+port for fallback probes
        probe_url = base_url.rstrip("/")
        lines.extend(
            [
                "printf '###HTTP\\n'",
                f"curl -s -o /dev/null -w '%{{http_code}}' --max-time {int(http_block['timeout'])} "
                f"{shlex.quote(probe_url)} 2>/dev/null || true",
                "echo",
                "# Discover listen ports from nginx config for fallback probing",
                "printf '###FALLBACK_PORTS\\n'",
                r"grep -rEoh '^\s*listen\s+' {paths} 2>/dev/null | "
                r"sed -E 's/^.*listen[[:space:]]+[^:]*:([0-9]+).*/\1/; s/^([0-9]+)[[:space:];].*/\1/' | "
                r"sort -un || true",
                "echo",
                "# Probe each discovered port and report status",
                "printf '###FALLBACK_HTTP\\n'",
            ]
        )
        # Build inline shell loop: scan config, probe each unique port
        lines.append(r"""for _port in $(grep -rhoE '^\s*listen\s+' {paths} 2>/dev/null | \
sed -E 's/^.*listen[[:space:]]+[^:]*:([0-9]+).*/\1/; s/^([0-9]+)[[:space:];].*/\1/' | sort -un); do
  _code=$(curl -s -o /dev/null -w '%{{http_code}}' --max-time {timeout} \
    http://127.0.0.1:\$_port/ 2>/dev/null || echo "")
  printf '%s %s\n' "\$_port" "$_code"
done""")
        lines.append("echo")
        lines.append("printf '###END\\n'")
    else:
        lines.append("printf '###END\\n'")

    https_block = tool["verify"]["https"]
    https_mode = https_block["enabled"]
    https_included = https_mode is True or (https_mode == "auto" and tls_present)
    if https_included:
        probe_url = str(https_block["url"]).rstrip("/")
        lines.extend(
            [
                "printf '###HTTPS\\n'",
                f"curl -s -k -o /dev/null -w '%{{http_code}}' --max-time {int(https_block['timeout'])} "
                f"{shlex.quote(probe_url)} 2>/dev/null || true",
                "echo",
            ]
        )
    if patterns:
        lines.extend(
            [
                "printf '###DRIFT\\n'",
                f"find {paths} \\( {expression} \\) 2>/dev/null || true",
            ]
        )
    return "\n".join(lines) + "\n"


def verify_and_drift(
    client: Any, cfg: Any, ip: str, tls_present: bool, candidate: str | None
) -> tuple[dict[str, Any], bool, str, str | None, list[dict[str, Any]]]:
    tool = cfg.tool
    http_block = tool["verify"]["http"]
    https_block = tool["verify"]["https"]
    http_enabled = bool(http_block["enabled"])
    https_mode = https_block["enabled"]
    https_included = https_mode is True or (https_mode == "auto" and tls_present)
    verification: dict[str, Any] = {
        "config_ok": False,
        "service_active": False,
        "version_matches": False,
        "http_status": None,
        "https_status": None,
    }
    drift: list[dict[str, Any]] = []
    result = client.run(
        ip,
        verify_script(cfg, tls_present),
        timeout=max(int(cfg.get("ssh.command_timeout")), 120),
        need_privilege=True,
    )
    if not result.ok:
        detail = (result.stderr or result.stdout or f"ssh exit {result.returncode}").strip()
        return verification, False, f"verification failed: {detail}", None, drift
    sections = parse_sections(result.stdout or "")
    config_ok = sections.get("PRECHECK_RC", "").strip() == "0"
    service_active = sections.get("ACTIVE", "").strip() == "active"
    installed = sections.get("VERSION", "").strip() or None
    version_matches = bool(installed and candidate and installed == candidate)
    http_status = _probe_status(sections.get("HTTP")) if http_enabled else None
    https_status = _probe_status(sections.get("HTTPS")) if https_included else None

    # If primary HTTP probe failed, try discovered listen ports from nginx config
    if http_enabled and http_status is None:
        fb_ports_raw = (sections.get("FALLBACK_PORTS") or "").splitlines()
        fb_http_raw = (sections.get("FALLBACK_HTTP") or "").splitlines()
        discovered_ports = [p.strip() for p in fb_ports_raw if p.strip().isdigit()]
        # Build port -> status mapping from fallback probes
        fb_port_status: dict[str, int | None] = {}
        for line in fb_http_raw:
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and parts[0].isdigit():
                ps = _probe_status(parts[1])
                if ps is not None:
                    fb_port_status[parts[0]] = ps
        # Find first working port; record it
        best_fb_port = None
        best_fb_status = None
        for port in discovered_ports:
            if port in fb_port_status:
                best_fb_port = port
                best_fb_status = fb_port_status[port]
                break
        if best_fb_port is not None:
            http_status = best_fb_status
            verification["http_probed_port"] = best_fb_port
            if best_fb_status is not None:
                verification["http_probe_fallback"] = True

    verification.update(
        {
            "config_ok": config_ok,
            "service_active": service_active,
            "version_matches": version_matches,
            "http_status": http_status,
            "https_status": https_status,
        }
    )

    failures: list[str] = []
    if not config_ok:
        failures.append("config test failed")
    if not service_active:
        failures.append("service not active")
    if not version_matches:
        failures.append("installed version does not match candidate")
    if http_enabled and http_status is None:
        failures.append("http probe failed")
    if https_included and https_status is None:
        failures.append("https probe failed")
    required = tool["verify"]["require_status"]
    if required:
        for label, status in (("http", http_status), ("https", https_status)):
            if status is not None and status not in required:
                failures.append(f"{label} status {status} not in required set")

    patterns = [str(item) for item in tool["drift_patterns"]]
    for path in sections.get("DRIFT", "").splitlines():
        path = path.strip()
        if not path:
            continue
        base = path.rsplit("/", 1)[-1]
        pattern = next((item for item in patterns if fnmatch.fnmatchcase(base, item)), patterns[0])
        drift.append({"pattern": pattern, "path": path, "needs_manual_review": True})

    return verification, not failures, "; ".join(failures), installed, drift


def run_vm(client: Any, cfg: Any, record: dict[str, Any], phase: str, attempt: int, mode: str = "distro") -> dict[str, Any]:
    record = copy.deepcopy(record)
    evidence = record.get("evidence") or {}
    old_version = evidence.get("installed_version")
    candidate = evidence.get("candidate_version")
    execution = _new_execution(phase, old_version, attempt)
    if mode == "migrate":
        execution["mode"] = "migrate"

    if mode == "distro" and old_version and candidate and compare_versions(old_version, candidate) >= 0:
        started = utcnow()
        execution.update(
            {
                "state": "SUCCEEDED",
                "new_version": old_version,
                "steps": [_step("verify", True, started, "already up-to-date; no upgrade run")],
            }
        )
        record["execution"] = execution
        record["timestamps"]["executed_at"] = utcnow()
        return record

    current = client.run(record["ip"], str(cfg.tool["version_query"]))
    current_version = (current.stdout or "").strip() or None
    if mode == "distro" and current_version and candidate and compare_versions(current_version, candidate) >= 0:
        started = utcnow()
        execution.update(
            {
                "state": "SUCCEEDED",
                "new_version": current_version,
                "steps": [_step("verify", True, started, "already up-to-date on re-check; no upgrade run")],
            }
        )
        record["execution"] = execution
        record["timestamps"]["executed_at"] = utcnow()
        return record

    started = utcnow()
    try:
        backup = create_backup(client, cfg, record["ip"])
        record["backup"] = backup
        execution["steps"].append(
            _step("backup", True, started, f"{backup['local_path']} ({backup['size_bytes']} bytes)")
        )
    except (BackupError, SSHError) as exc:
        return _fail(execution, record, "backup", started, str(exc), f"backup failed: {exc}")

    started = utcnow()
    precheck = client.run(record["ip"], str(cfg.tool["precheck"]), need_privilege=True)
    if not precheck.ok:
        detail = (precheck.stderr or precheck.stdout).strip() or "precheck failed"
        return _fail(execution, record, "precheck", started, detail, "pre-upgrade config test failed")
    execution["steps"].append(_step("precheck", True, started, "config valid"))

    skip_upgrade = False
    if mode == "migrate":
        started = utcnow()
        try:
            bootstrap = client.run(
                record["ip"],
                bootstrap_script(cfg),
                timeout=max(int(cfg.get("ssh.command_timeout")), 300),
                need_privilege=True,
            )
            if not bootstrap.ok:
                raise MigrationError((bootstrap.stderr or bootstrap.stdout).strip() or "repo bootstrap failed")
            policy_result = client.run(record["ip"], policy_command())
            parsed = parse_apt_policy(policy_result.stdout or "")
            if not repo_active(policy_result.stdout or ""):
                raise MigrationError("candidate does not come from nginx.org after bootstrap")
            fresh_candidate = parsed["candidate"]
            if not fresh_candidate:
                raise MigrationError("no candidate version from nginx.org repo")
            candidate = fresh_candidate
            if current_version and compare_versions(current_version, candidate) >= 0:
                skip_upgrade = True
                execution["steps"].append(
                    _step("bootstrap", True, started, "nginx.org repo active; already on target version; upgrade skipped")
                )
            else:
                execution["steps"].append(_step("bootstrap", True, started, f"nginx.org repo active (candidate {candidate})"))
        except MigrationError as exc:
            return _fail(
                execution, record, "bootstrap", started, str(exc), f"repo migration bootstrap failed: {exc}"
            )

    if not skip_upgrade:
        started = utcnow()
        upgrade_template = (
            str(cfg.get("migration.upgrade_command")) if mode == "migrate" else str(cfg.execution["upgrade_command"])
        )
        upgrade_command = upgrade_template.format(package=str(cfg.tool["package"]))
        upgrade = client.run(
            record["ip"],
            upgrade_command,
            timeout=max(int(cfg.get("ssh.command_timeout")), 300),
            need_privilege=True,
        )
        if not upgrade.ok:
            detail = (upgrade.stderr or upgrade.stdout).strip() or "upgrade failed"
            return _fail(execution, record, "upgrade", started, detail, "package upgrade failed")
        execution["steps"].append(_step("upgrade", True, started, "package upgrade completed"))

    if mode == "migrate":
        started = utcnow()
        restart_command = (
            f"{str(cfg.tool['precheck'])} && systemctl restart {shlex.quote(str(cfg.tool['service']))}"
        )
        restart = client.run(
            record["ip"],
            restart_command,
            timeout=max(int(cfg.get("ssh.command_timeout")), 120),
            need_privilege=True,
        )
        if not restart.ok:
            detail = (restart.stderr or restart.stdout).strip() or "restart failed"
            return _fail(execution, record, "restart", started, detail, "service restart after migration failed")
        execution["steps"].append(_step("restart", True, started, "service restarted on migrated package"))

    started = utcnow()
    verification, verified, verify_detail, installed_now, drift = verify_and_drift(
        client, cfg, record["ip"], bool(evidence.get("tls_present")), candidate
    )
    execution["verification"] = verification
    execution["steps"].append(_step("verify", verified, started, verify_detail or "verification passed"))

    started = utcnow()
    record["drift_flags"] = drift
    execution["steps"].append(
        _step("drift", True, started, "none" if not drift else f"{len(drift)} drifted file(s)")
    )

    execution["new_version"] = installed_now
    execution["state"] = "SUCCEEDED" if verified else "FAILED"
    execution["error"] = None if verified else verify_detail
    record["execution"] = execution
    record["timestamps"]["executed_at"] = utcnow()
    return record


def dry_run_plan(cfg: Any, records: list[dict[str, Any]], mode: str = "distro") -> list[dict[str, Any]]:
    name = str(cfg.tool["name"])
    paths = " ".join(str(path) for path in cfg.tool["config_paths"])
    upgrade_template = (
        str(cfg.get("migration.upgrade_command")) if mode == "migrate" else str(cfg.execution["upgrade_command"])
    )
    upgrade_command = upgrade_template.format(package=str(cfg.tool["package"]))
    plan = []
    for record in records:
        commands = [
            f"tar czf /var/backups/{name}-<timestamp>.tar.gz {paths}",
            f"scp <user>@{record['ip']}:<remote-archive> backups/{record['ip']}/",
            str(cfg.tool["precheck"]),
        ]
        if mode == "migrate":
            commands.append(
                "bootstrap nginx.org repo: key -> "
                f"{cfg.get('migration.keyring_path')}, sources.list.d (dist {cfg.get('migration.repo_dist')}), "
                f"pin priority {cfg.get('migration.pin_priority')}, apt-get update"
            )
            commands.append("apt-cache policy nginx  # candidate must come from nginx.org")
        commands.extend(
            [
                upgrade_command,
                f"systemctl is-active {cfg.tool['service']}",
                str(cfg.tool["version_query"]),
                f"curl {cfg.tool['verify']['http']['url']}",
                f"find {paths} -name '*.dpkg-dist' -o -name '*.dpkg-new'",
            ]
        )
        plan.append({"ip": record["ip"], "mode": mode, "commands": commands})
    return plan


def validate_approvals(state: Any, cfg: Any, approved: list[str], mode: str = "distro") -> list[dict[str, Any]]:
    ordered = list(dict.fromkeys(item.strip() for item in approved if item and item.strip()))
    if not ordered:
        raise ApprovalError("no approved IPs supplied")
    entries: list[dict[str, Any]] = []
    for ip in ordered:
        record = state.data["records"].get(ip)
        if record is None:
            raise ApprovalError(f"{ip} is not in the current inventory")
        if mode == "migrate":
            reason = migration_eligible(record, cfg)
            if reason:
                raise ApprovalError(f"{ip} cannot be migrated: {reason}")
        elif record.get("verdict") != "UPGRADE":
            raise ApprovalError(f"{ip} has verdict {record.get('verdict')}; only UPGRADE VMs can be approved")
        entries.append(record)
    return entries


def execute_canary(state: Any, client: Any, cfg: Any, approved: list[str], dry_run: bool = False, mode: str = "distro") -> list[dict[str, Any]]:
    entries = validate_approvals(state, cfg, approved, mode)
    if dry_run:
        return dry_run_plan(cfg, entries, mode)
    candidate = entries[0]
    execution = candidate.get("execution") or {}
    if execution.get("state") == "SUCCEEDED":
        raise ApprovalError("canary already completed for this run")
    attempts = int(execution.get("attempts") or 0)
    if attempts >= 2 and execution.get("state") == "FAILED":
        raise ApprovalError(f"{candidate['ip']} already used its retry")
    excluded = [entry["ip"] for entry in state.data["inventory"]["entries"] if entry["ip"] not in approved]
    state.add_approval(approved, excluded)
    updated = run_vm(client, cfg, candidate, "canary", attempts + 1, mode)
    state.set_record(updated)
    state.save()
    write_record(cfg, updated, state.data["run_id"])
    return [updated]


def execute_fleet(state: Any, client: Any, cfg: Any, approved: list[str], dry_run: bool = False, mode: str = "distro") -> list[dict[str, Any]]:
    entries = validate_approvals(state, cfg, approved, mode)
    if dry_run:
        return dry_run_plan(cfg, entries, mode)
    gate = state.last_gate()
    if not gate or gate.get("decision") != "proceed":
        raise ApprovalError("canary proceed decision not recorded")
    canaries = state.canary_records()
    if not canaries:
        raise ApprovalError("canary has not run")
    if not any(record.get("execution", {}).get("state") in {"SUCCEEDED", "FAILED"} for record in canaries):
        raise ApprovalError("canary has not reached a terminal state")

    excluded = [entry["ip"] for entry in state.data["inventory"]["entries"] if entry["ip"] not in approved]
    state.add_approval(approved, excluded)

    pending = []
    for record in entries:
        execution = record.get("execution") or {}
        if execution.get("state") == "SUCCEEDED":
            continue
        if execution.get("state") == "FAILED" and int(execution.get("attempts") or 0) >= 2:
            continue
        pending.append(record)
    run_id = state.data["run_id"]
    processed: dict[str, dict[str, Any]] = {}
    concurrency = max(1, int(cfg.get("execution.concurrency")))

    def work(record: dict[str, Any], attempt: int) -> dict[str, Any]:
        return run_vm(client, cfg, record, "fleet", attempt, mode)

    def persist(updated: dict[str, Any], index: int, total: int) -> None:
        state.set_record(updated)
        state.save()
        write_record(cfg, updated, run_id)
        print(
            f"[{index}/{total}] {updated['ip']}: {updated.get('execution', {}).get('state')}",
            file=sys.stderr,
            flush=True,
        )

    def run_round(records: list[dict[str, Any]], attempt_for: Any) -> None:
        if not records:
            return
        total = len(records)
        done = 0
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            future_to_ip = {
                pool.submit(work, record, attempt_for(record)): record["ip"] for record in records
            }
            for future in as_completed(future_to_ip):
                updated = future.result()
                done += 1
                persist(updated, done, total)
                processed[future_to_ip[future]] = updated

    def attempt_now(record: dict[str, Any]) -> int:
        existing = int((record.get("execution") or {}).get("attempts") or 0)
        return min(existing + 1, 2)

    run_round(pending, attempt_now)

    retryable = [
        record
        for record in processed.values()
        if record.get("execution", {}).get("state") == "FAILED"
        and int(record.get("execution", {}).get("attempts") or 0) < 2
    ]
    run_round(retryable, lambda record: 2)

    return [state.data["records"][record["ip"]] for record in pending if record["ip"] in processed]
