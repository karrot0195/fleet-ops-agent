"""CLI argument parsing and command dispatch for fleet-upgrade."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any

import yaml


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="fleet.py",
        description="Common Fleet Upgrade Skill — audit, upgrade, rollback across VM fleets.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # -- config --
    cfg = subparsers.add_parser("config", help="Initialize or manage configuration files.")
    cfg.add_argument("--init", action="store_true", help="Create a new config file.")
    cfg.add_argument("--type", choices=["tool", "provider"], dest="cfg_type",
                     help="Config type: tool or provider.")
    cfg.add_argument("--name", help="Name of the tool/provider (creates .specific/{name}.yaml).")
    cfg.add_argument("--force", action="store_true", help="Overwrite existing config.")
    cfg.add_argument("--path", help="Output path (defaults to .specific/{name}.yaml).")

    # -- doctor --
    doc = subparsers.add_parser("doctor", help="Check provider CLI availability and auth status.")
    doc.add_argument("--provider", help="Provider name to check.")

    # -- discover --
    disc = subparsers.add_parser("discover", help="Fetch fleet inventory from a registered provider.")
    disc.add_argument("--provider", required=True, help="Registered provider name.")
    disc.add_argument("--output", default="ip.txt", help="Output file for inventory (default: ip.txt).")

    # -- survey --
    surv = subparsers.add_parser("survey", help="Run read-only audit across all VMs.")
    surv.add_argument("--tool", required=True, help="Tool name.")
    surv.add_argument("--all", action="store_true", dest="survey_all", help="Survey all IPs in inventory.")
    surv.add_argument("--ips", help="Comma-separated list of IPs to survey.")
    surv.add_argument("--concurrency", type=int, default=4, help="Parallel SSH connections (default: 4).")
    surv.add_argument("--dry-run", action="store_true", help="Simulate without connecting.")

    # -- summary --
    summ = subparsers.add_parser("summary", help="Show grouped survey results.")
    summ.add_argument("--tool", help="Filter by tool name.")

    # -- execute --
    exec_cmd = subparsers.add_parser("execute", help="Run canary or fleet upgrade rollout.")
    exec_cmd.add_argument("--tool", required=True, help="Tool name.")
    exec_cmd.add_argument("--phase", choices=["canary", "fleet"], required=True, help="Rollout phase.")
    exec_cmd.add_argument("--approve", help="Comma-separated IPs approved for upgrade.")
    exec_cmd.add_argument("--yes", action="store_true", dest="auto_approve", help="Skip confirmation prompts.")
    exec_cmd.add_argument("--dry-run", action="store_true", help="Plan only — do not execute.")

    # -- gate --
    gate = subparsers.add_parser("gate", help="Record canary gate decision.")
    gate.add_argument("decision", choices=["proceed", "stop"], help="'proceed' or 'stop'.")
    gate.add_argument("--note", help="Optional note.")

    # -- rollback --
    rb = subparsers.add_parser("rollback", help="Rollback a single VM to pre-upgrade state.")
    rb.add_argument("--tool", required=True, help="Tool name.")
    rb.add_argument("--ip", required=True, help="VM IP address.")
    rb.add_argument("--yes", action="store_true", dest="auto_yes", help="Skip confirmation.")
    rb.add_argument("--dry-run", action="store_true", help="Show what would happen.")

    # -- report --
    rpt = subparsers.add_parser("report", help="Generate fleet reports.")
    rpt.add_argument("--tool", required=True, help="Tool name.")
    rpt.add_argument("--log", action="store_true", help="Also append to LOGS.md.")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    root = Path(__file__).resolve().parent.parent.parent.parent.parent.parent.parent
    # Walk up until we find a directory with .specific/ or just use cwd
    cwd = Path.cwd()
    search_root = cwd
    while search_root != search_root.parent:
        if (search_root / ".specific").is_dir():
            search_root = search_root
            break
        search_root = search_root.parent
    else:
        search_root = cwd

    try:
        if args.command == "config":
            return _cmd_config(search_root, args)
        elif args.command == "doctor":
            return _cmd_doctor(search_root, args)
        elif args.command == "discover":
            return _cmd_discover(search_root, args)
        elif args.command == "survey":
            return _cmd_survey(search_root, args)
        elif args.command == "summary":
            return _cmd_summary(search_root, args)
        elif args.command == "execute":
            return _cmd_execute(search_root, args)
        elif args.command == "gate":
            return _cmd_gate(search_root, args)
        elif args.command == "rollback":
            return _cmd_rollback(search_root, args)
        elif args.command == "report":
            return _cmd_report(search_root, args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        exit_code = getattr(exc, "exit_code", 1)
        return exit_code

    return 0


def _get_config(root: Path) -> tuple[Any, dict[str, Any]]:
    """Load global defaults + tool/provider configs into a unified config + data dict."""
    from fleetkit.config import load_tool_config, load_provider_config, Config
    from fleetkit.state import StateStore, empty_state
    from fleetkit.config import DEFAULTS

    state_store = StateStore(root)
    try:
        state_data = state_store.load()
    except Exception:
        state_data = empty_state()

    return None, state_data  # We'll handle this differently per-command


# ---- Command implementations -------------------------------------------

def _load_tool_data(root: Path, tool_name: str) -> dict[str, Any]:
    """Load tool data from .specific/{tool_name}.yaml."""
    path = root / ".specific" / f"{tool_name}.yaml"
    if not path.is_file():
        raise SystemExit(f"config not found: {path} (run 'fleet.py config --init --type tool --name {tool_name}')")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise SystemExit(f"{path} must contain a YAML mapping")
    return raw


def _make_global_cfg(root: Path, tool_data: dict[str, Any]) -> Any:
    """Build a minimal Config-like object merging tool data with defaults."""
    from fleetkit.config import _deep_merge, DEFAULTS

    merged = _deep_merge(DEFAULTS, tool_data)

    class MiniConfig:
        def get(self, dotted: str, default: Any = None) -> Any:
            node: Any = merged
            for part in dotted.split("."):
                if not isinstance(node, dict) or part not in node:
                    return default
                node = node[part]
            return node

    return MiniConfig()


def _cmd_config(root: Path, args: Any) -> int:
    """Handle `config --init --type <tool|provider> --name <name>`."""
    if not args.init:
        print("Use 'fleet.py config --init --type <tool|provider> --name NAME'.")
        return 0

    ref_dir = Path(__file__).resolve().parent.parent.parent / "references"

    if args.cfg_type == "tool":
        template_path = ref_dir / "tool-config.template.yaml"
        output_path = root / ".specific" / f"{args.name}.yaml"
    elif args.cfg_type == "provider":
        template_path = ref_dir / "provider-config.template.yaml"
        output_path = root / ".specific" / f"{args.name}.yaml"
    else:
        print("Specify --type tool or --type provider.")
        return 2

    if output_path.exists() and not args.force:
        print(f"Refusing to overwrite: {output_path} (use --force)")
        return 3

    if template_path.is_file():
        content = template_path.read_text(encoding="utf-8")
    else:
        content = "# Configuration will be generated here.\n"

    content = content.replace("TOOL_NAME", args.name)

    output_path.write_text(content, encoding="utf-8")
    print(f"Created {output_path}")
    return 0


def _cmd_doctor(root: Path, args: Any) -> int:
    """Check provider CLI binary and auth status."""
    from fleetkit.providers.doctl import DoctlProvider
    from fleetkit.providers.vultr import VultrProvider
    from fleetkit.providers.manual import ManualProvider
    from fleetkit.config import load_provider_config, ProviderBase

    provider_map = {"doctl": DoctlProvider, "vultr-cli": VultrProvider, "manual": ManualProvider}

    if not args.provider:
        # List available providers
        from fleetkit.config import list_tools
        tools = list_tools(root)
        print("Registered tools:", ", ".join(tools) if tools else "(none)")
        return 0

    # Try loading provider config first
    provider_class = provider_map.get(args.provider)
    if provider_class is None:
        try:
            cfg = load_provider_config(root, args.provider)
            # For custom providers, we need dynamic loading — skip for now
            print(f"Unknown provider '{args.provider}'. Built-in providers: doctl, vultr-cli, manual")
            return 4
        except Exception:
            print(f"Unknown provider '{args.provider}'. Built-in providers: doctl, vultr-cli, manual")
            return 4

    prov = provider_class(root)
    try:
        prov.validate()
        print(f"Provider '{args.provider}': OK")
        return 0
    except Exception as exc:
        print(f"Provider '{args.provider}': FAIL — {exc}")
        return 4


def _cmd_discover(root: Path, args: Any) -> int:
    """Fetch inventory via a registered provider."""
    from fleetkit.providers.doctl import DoctlProvider
    from fleetkit.providers.vultr import VultrProvider
    from fleetkit.providers.manual import ManualProvider
    from fleetkit.state import StateStore, empty_state
    from datetime import datetime, timezone

    provider_map = {"doctl": DoctlProvider, "vultr": VultrProvider, "manual": ManualProvider}

    provider_name = args.provider
    pclass = provider_map.get(provider_name)
    if pclass is None:
        print(f"Unknown provider '{provider_name}'. Use: doctl, vultr, or manual")
        return 4

    prov = pclass(root)
    try:
        prov.validate()
        entries = prov.discover()
    except Exception as exc:
        print(f"Discovery failed: {exc}")
        return 4

    # Write inventory to ip.txt
    output_path = Path.cwd() / args.output if not Path(args.output).is_absolute() else Path(args.output)
    lines = ["Name,IP"]
    for e in sorted(entries, key=lambda x: x.get("ip", "")):
        lines.append(f"{e.get('name', '')},{e['ip']}")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Update state
    state_store = StateStore(root)
    try:
        sd = state_store.load()
    except Exception:
        sd = empty_state()

    prev_ips = {e["ip"] for e in sd.get("inventory", {}).get("entries", [])}
    new_ips = {e["ip"] for e in entries}
    added = sorted(new_ips - prev_ips)
    removed = sorted(prev_ips - new_ips)

    sd["inventory"] = {
        "captured_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": provider_name,
        "entries": entries,
        "added": added,
        "removed": removed,
    }
    state_store.data = sd
    state_store.save()

    print(f"Discovered {len(entries)} VMs. Added: {len(added)}, Removed: {len(removed)}")
    print(f"Written to {output_path}")
    return 0


def _cmd_survey(root: Path, args: Any) -> int:
    """Run survey across VMs for a registered tool."""
    if args.dry_run:
        print("[dry-run] Survey skipped — no SSH connections made.")
        return 0

    tool_data = _load_tool_data(root, args.tool)
    mini_cfg = _make_global_cfg(root, tool_data)

    # Load ssh env
    from fleetkit.config import load_ssh_env
    ssh_env = load_ssh_env(mini_cfg.resolve("ssh.env_file"))

    # Build SSH client
    from fleetkit.ssh import SSHClient
    ssh = SSHClient(mini_cfg, ssh_env)

    # Get inventory
    state_store = StateStore(root)
    try:
        state_store.load()
    except Exception:
        pass

    if args.survey_all:
        entries = state_store.get_inventory_entries()
    elif args.ips:
        ips_list = [i.strip() for i in args.ips.split(",") if i.strip()]
        entries = [{"name": f"vm-{i}", "ip": i} for i in ips_list]
    else:
        print("Specify --all or --ips.")
        return 2

    if not entries:
        print("No VM entries to survey.")
        return 0

    # Run survey
    from fleetkit.survey import survey_entries, render_summary, summary_data
    records = survey_entries(ssh, entries, mini_cfg, tool_data,
                             concurrency=args.concurrency, records_dir=str(root))

    summary = render_summary(records)
    print(summary)

    # Store records in state
    tool = tool_data.get("tool", {})
    for ip, rec in records.items():
        key = f"{ip}:{tool.get('name', args.tool)}"
        state_store.data["records"][key] = rec
    state_store.save()

    return 0


def _cmd_summary(root: Path, args: Any) -> int:
    """Show grouped survey results from state."""
    from fleetkit.state import StateStore
    from fleetkit.survey import render_summary

    state_store = StateStore(root)
    try:
        state_store.load()
    except Exception:
        print("No state found — run discover and survey first.")
        return 2

    records = state_store.records

    if args.tool:
        filtered = {k: v for k, v in records.items() if args.tool in k}
    else:
        filtered = records

    if not filtered:
        print("No survey records found.")
        return 0

    print(render_summary(filtered))
    return 0


def _cmd_execute(root: Path, args: Any) -> int:
    """Execute canary or fleet rollout."""
    tool_data = _load_tool_data(root, args.tool)
    mini_cfg = _make_global_cfg(root, tool_data)

    from fleetkit.state import StateStore
    state_store = StateStore(root)
    try:
        state_store.load()
    except Exception:
        print("No state found — run discover and survey first.")
        return 2

    if args.phase == "canary":
        print("Canary execution requires approval gates. Use 'fleet.py survey' first.")
        return 0

    if args.dry_run:
        print("[dry-run] Execute plan would proceed after canary gate.")
        return 0

    return 0


def _cmd_gate(root: Path, args: Any) -> int:
    """Record a gate decision."""
    from fleetkit.state import StateStore
    state_store = StateStore(Path.cwd())
    try:
        state_store.load()
    except Exception:
        print("No state found — nothing to gate.")
        return 2

    state_store.add_gate(args.decision, note=args.note, phase="canary")
    state_store.save()
    print(f"Gate recorded: {args.decision}")
    return 0


def _cmd_rollback(root: Path, args: Any) -> int:
    """Rollback a single VM."""
    if args.dry_run:
        print("[dry-run] Rollback would restore backup and reinstall old package version.")
        return 0

    print("Rollback requires verified backup. Use 'fleet.py survey' before executing.")
    return 0


def _cmd_report(root: Path, args: Any) -> int:
    """Generate and optionally write reports."""
    from fleetkit.state import StateStore
    state_store = StateStore(root)
    try:
        state_store.load()
    except Exception:
        print("No state found — nothing to report.")
        return 2

    records = state_store.records
    if args.tool:
        records = {k: v for k, v in records.items() if args.tool in k}

    print(f"Report for tool '{args.tool}': {len(records)} records.")
    if args.log:
        log_path = root / "LOGS.md"
        title = f"Fleet Report: {args.tool}"
        summary = f"Run completed with {len(records)} records."
        # Simple append (idempotent check omitted for brevity)
        entry = f"\n## {title}\n\n{summary}\n\n"
        log_path.write_text(log_path.read_text(encoding="utf-8") + entry if log_path.exists() else entry,
                           encoding="utf-8")
        print(f"Appended to {log_path}")

    return 0
