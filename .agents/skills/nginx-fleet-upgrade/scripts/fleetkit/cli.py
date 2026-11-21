from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .backup import BackupError
from .config import Config, ConfigError, PreflightError, load_config, load_ssh_env
from .execute import (
    ApprovalError,
    ExecutionError,
    execute_canary,
    execute_fleet,
    validate_approvals,
)
from .inventory import (
    DiscoveryError,
    discover_from_doctl,
    discover_from_file,
    reconcile,
    write_ip_file,
)
from .migration import MigrationError
from .records import write_record
from .report import append_log, log_summary, render_report, report_rows
from .rollback import RollbackError, dry_run_plan as rollback_plan, rollback_vm
from .ssh import SSHError, SSHClient
from .state import StateError, StateStore, utcnow
from .survey import render_summary, summary_data, survey_entries

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "references" / "fleet-config.template.yaml"


@dataclass
class Outcome:
    data: Any = None
    text: str = ""
    warnings: list[str] = field(default_factory=list)
    exit_code: int = 0
    run_id: str | None = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fleet.py", description="nginx fleet audit, upgrade, and rollback")
    parser.add_argument("--root", default=".", help="project root")
    parser.add_argument("--config", default=None, help="config path")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warn", "error"])
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("doctor", help="preflight checks")

    discover = commands.add_parser("discover", help="refresh the fleet inventory")
    discover.add_argument("--source", choices=["doctl", "file"], default=None)
    discover.add_argument("--file", default=None)

    survey = commands.add_parser("survey", help="read-only per-VM audit")
    survey.add_argument("--all", action="store_true")
    survey.add_argument("--ip", action="append", default=[])
    survey.add_argument("--parallel", type=int, default=None)

    commands.add_parser("summary", help="show verdicts and eligible VMs")

    gate = commands.add_parser("gate", help="record the canary decision")
    gate.add_argument("--decision", required=True, choices=["proceed", "stop"])
    gate.add_argument("--note", default=None)

    execute = commands.add_parser("execute", help="run the canary or fleet rollout")
    execute.add_argument("--phase", required=True, choices=["canary", "fleet"])
    execute.add_argument("--mode", choices=["distro", "migrate"], default="distro",
                         help="distro: in-repo upgrade; migrate: bootstrap the upstream nginx.org repo first")
    execute.add_argument("--approve", required=True)
    execute.add_argument("--concurrency", type=int, default=None)
    execute.add_argument("--dry-run", action="store_true")
    execute.add_argument("--yes", action="store_true")

    rollback = commands.add_parser("rollback", help="restore a failed VM configuration")
    rollback.add_argument("--ip", required=True)
    rollback.add_argument("--dry-run", action="store_true")
    rollback.add_argument("--yes", action="store_true")

    report = commands.add_parser("report", help="final fleet report")
    report.add_argument("--log", action="store_true")

    config = commands.add_parser("config", help="configuration helpers")
    config.add_argument("--init", action="store_true")
    config.add_argument("--force", action="store_true")
    return parser


def _state(cfg: Config) -> StateStore:
    store = StateStore(cfg.resolve("paths.state_dir"))
    store.load()
    return store


def _client(cfg: Config, state: StateStore) -> SSHClient:
    env = load_ssh_env(cfg)
    for warning in env["warnings"]:
        print(f"warning: {warning}", file=sys.stderr)
    log_dir = cfg.resolve("paths.state_dir") / "logs" / state.data["run_id"]
    return SSHClient(cfg, env, log_dir=log_dir)


def _split_ips(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _cmd_doctor(cfg: Config) -> Outcome:
    env = load_ssh_env(cfg)
    checks = {name: shutil.which(name) for name in ("ssh", "scp", "doctl")}
    missing = [name for name, path in checks.items() if not path]
    if missing:
        raise PreflightError("missing executables: " + ", ".join(missing))
    try:
        auth = subprocess.run(["doctl", "auth", "list"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PreflightError(f"doctl auth check failed: {exc}") from exc
    if auth.returncode != 0:
        raise PreflightError(f"doctl auth failed: {(auth.stderr or auth.stdout).strip()}")
    text = "\n".join(
        [
            f"config: {cfg.path}",
            f"ssh env: {env['env_file']}",
            f"ssh user: {env['user']}",
            f"ssh key: {env['key']}",
            f"executables: {', '.join(name for name, path in checks.items() if path)}",
            "doctl auth: ok",
        ]
    )
    return Outcome(data={"config": str(cfg.path), "ssh_env": env["env_file"], "executables": checks}, text=text, warnings=env["warnings"])


def _cmd_discover(cfg: Config, args: argparse.Namespace) -> Outcome:
    source = args.source or str(cfg.get("fleet.source"))
    if source == "file":
        entries = discover_from_file(args.file or cfg.resolve("fleet.inventory_file"))
    else:
        entries = discover_from_doctl()
    store = _state(cfg)
    added, removed = reconcile(store.data, entries, source)
    write_ip_file(cfg.resolve("fleet.inventory_file"), store.data["inventory"]["entries"])
    store.save()
    text_lines = [f"inventory: {len(store.data['inventory']['entries'])} VM(s) from {source}"]
    text_lines.append("added: " + (", ".join(added) if added else "none"))
    text_lines.append("removed: " + (", ".join(removed) if removed else "none"))
    return Outcome(
        data={
            "inventory": store.data["inventory"]["entries"],
            "added": added,
            "removed": removed,
            "run_id": store.data["run_id"],
        },
        text="\n".join(text_lines),
        run_id=store.data["run_id"],
    )


def _cmd_survey(cfg: Config, args: argparse.Namespace) -> Outcome:
    store = _state(cfg)
    if not store.loaded:
        raise PreflightError("no inventory captured; run discover first")
    entries = store.data["inventory"].get("entries", [])
    if args.ip:
        wanted = set(args.ip)
        known = {entry["ip"] for entry in entries}
        unknown = [ip for ip in args.ip if ip not in known]
        if unknown:
            raise DiscoveryError("unknown IPs: " + ", ".join(unknown))
        entries = [entry for entry in entries if entry["ip"] in wanted]
    client = _client(cfg, store)
    concurrency = args.parallel or int(cfg.get("execution.concurrency"))
    if concurrency < 1 or concurrency > 16:
        raise ConfigError("--parallel must be between 1 and 16")
    results = survey_entries(client, entries, cfg, concurrency, store.records)
    for record in results.values():
        store.set_record(record)
        write_record(cfg, record, store.data["run_id"])
    store.save()
    return Outcome(
        data=summary_data(store.records),
        text=render_summary(store.records),
        run_id=store.data["run_id"],
    )


def _cmd_summary(cfg: Config) -> Outcome:
    store = _state(cfg)
    if not store.records:
        return Outcome(data={"groups": {}, "counts": {}, "eligible": []}, text="No audit records.")
    data = summary_data(store.records)
    text = render_summary(store.records) + "\n\neligible: " + (", ".join(data["eligible"]) if data["eligible"] else "none")
    return Outcome(data=data, text=text, run_id=store.data["run_id"])


def _cmd_gate(cfg: Config, args: argparse.Namespace) -> Outcome:
    store = _state(cfg)
    terminal = [
        record
        for record in store.canary_records()
        if (record.get("execution") or {}).get("state") in {"SUCCEEDED", "FAILED"}
    ]
    if not terminal:
        raise ApprovalError("canary has not reached a terminal state")
    gate = store.add_gate(args.decision, args.note)
    store.save()
    return Outcome(
        data=gate, text=f"canary decision recorded: {args.decision}", run_id=store.data["run_id"]
    )


def _execution_outcome(store: StateStore, updated: list[dict[str, Any]], show_versions: bool) -> Outcome:
    failed = False
    lines = []
    for record in updated:
        execution = record.get("execution") or {}
        if execution.get("state") == "FAILED":
            failed = True
        detail = (
            f" {execution.get('old_version')} → {execution.get('new_version')}"
            if show_versions
            else f" attempts={execution.get('attempts')}"
        )
        lines.append(f"{record['ip']}: {execution.get('state')}{detail}")
    return Outcome(
        data={"records": updated, "run_id": store.data["run_id"]},
        text="\n".join(lines) or "no VMs remaining",
        exit_code=4 if failed else 0,
        run_id=store.data["run_id"],
    )


def _cmd_execute(cfg: Config, args: argparse.Namespace) -> Outcome:
    if not args.yes and not args.dry_run:
        raise ApprovalError("--yes is required for execution")
    if args.concurrency is not None:
        if args.concurrency < 1 or args.concurrency > 16:
            raise ConfigError("--concurrency must be between 1 and 16")
        cfg.data["execution"]["concurrency"] = args.concurrency
    approved = _split_ips(args.approve)
    store = _state(cfg)
    validate_approvals(store, cfg, approved, mode=args.mode)
    if args.phase == "canary":
        updated = execute_canary(store, _client(cfg, store), cfg, approved, dry_run=args.dry_run, mode=args.mode)
        if args.dry_run:
            return Outcome(data=updated, text=json.dumps(updated, indent=2))
        return _execution_outcome(store, updated, show_versions=True)

    updated = execute_fleet(store, _client(cfg, store), cfg, approved, dry_run=args.dry_run, mode=args.mode)
    if args.dry_run:
        return Outcome(data=updated, text=json.dumps(updated, indent=2))
    return _execution_outcome(store, updated, show_versions=False)


def _cmd_rollback(cfg: Config, args: argparse.Namespace) -> Outcome:
    if not args.yes and not args.dry_run:
        raise ApprovalError("--yes is required for rollback")
    store = _state(cfg)
    record = store.record_for_ip(args.ip)
    if args.dry_run:
        plan = rollback_plan(cfg, record)
        return Outcome(data=plan, text=json.dumps(plan, indent=2))
    result = rollback_vm(_client(cfg, store), cfg, record)
    record["rollback"] = result
    record["timestamps"]["rolled_back_at"] = result["at"]
    if result["state"] == "SUCCEEDED":
        record["execution"]["state"] = "ROLLED_BACK"
    store.set_record(record)
    store.save()
    write_record(cfg, record, store.data["run_id"])
    text = f"{args.ip}: rollback {result['state']} (config_ok={result['config_ok']}, service_active={result['service_active']})"
    return Outcome(
        data=result,
        text=text,
        exit_code=0 if result["state"] == "SUCCEEDED" else 4,
        run_id=store.data["run_id"],
    )


def _cmd_report(cfg: Config, args: argparse.Namespace) -> Outcome:
    store = _state(cfg)
    if not store.loaded:
        raise PreflightError("no fleet state; run discover first")
    rows = report_rows(store.records)
    text = render_report(store.records)
    warnings: list[str] = []
    logged = False
    if args.log:
        if store.data["report"].get("logged_at"):
            warnings.append("LOGS.md entry already recorded for this run; not appending again")
        else:
            title, summary = log_summary(store.records, store.data["run_id"])
            append_log(cfg.resolve("paths.log_file"), title, summary)
            store.data["report"]["logged_at"] = utcnow()
            logged = True
    store.data["report"]["written_at"] = utcnow()
    store.save()
    return Outcome(
        data={"rows": rows, "run_id": store.data["run_id"], "logged": logged},
        text=text,
        warnings=warnings,
        run_id=store.data["run_id"],
    )


def _cmd_config(args: argparse.Namespace, root: Path) -> Outcome:
    if not args.init:
        raise ConfigError("config requires --init")
    target = root / ".specific" / "nginx-fleet.yaml"
    if target.exists() and not args.force:
        raise ConfigError(f"config already exists: {target} (use --force to overwrite)")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    return Outcome(data={"path": str(target)}, text=f"wrote {target}")


def _emit(args: argparse.Namespace, outcome: Outcome, command: str) -> int:
    for warning in outcome.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if args.json:
        payload = {
            "schema_version": 1,
            "ok": outcome.exit_code == 0,
            "command": command,
            "run_id": outcome.run_id,
            "data": outcome.data,
            "warnings": outcome.warnings,
            "error": None,
        }
        print(json.dumps(payload, sort_keys=True))
    elif outcome.text:
        print(outcome.text)
    return outcome.exit_code


def _emit_error(args: argparse.Namespace, command: str, exc: Exception, code: int) -> int:
    message = str(exc) or exc.__class__.__name__
    if args.json:
        payload = {
            "schema_version": 1,
            "ok": False,
            "command": command,
            "run_id": None,
            "data": None,
            "warnings": [],
            "error": {"code": exc.__class__.__name__, "message": message, "exit_code": code},
        }
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"error: {message}", file=sys.stderr)
    return code


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.root).expanduser().resolve()
    try:
        if args.command == "config":
            return _emit(args, _cmd_config(args, root), args.command)
        cfg = load_config(root, args.config)
        if args.command == "doctor":
            return _emit(args, _cmd_doctor(cfg), args.command)
        if args.command == "discover":
            return _emit(args, _cmd_discover(cfg, args), args.command)
        if args.command == "survey":
            return _emit(args, _cmd_survey(cfg, args), args.command)
        if args.command == "summary":
            return _emit(args, _cmd_summary(cfg), args.command)
        if args.command == "gate":
            return _emit(args, _cmd_gate(cfg, args), args.command)
        if args.command == "execute":
            return _emit(args, _cmd_execute(cfg, args), args.command)
        if args.command == "rollback":
            return _emit(args, _cmd_rollback(cfg, args), args.command)
        if args.command == "report":
            return _emit(args, _cmd_report(cfg, args), args.command)
        raise ConfigError(f"unknown command: {args.command}")
    except (ConfigError, StateError, DiscoveryError, PreflightError, SSHError, ApprovalError, ExecutionError, BackupError, RollbackError, MigrationError) as exc:
        return _emit_error(args, args.command, exc, getattr(exc, "exit_code", 1))
    except Exception as exc:
        return _emit_error(args, args.command, exc, 1)
