---
name: fleet-upgrade
description: Generic, extensible fleet upgrade skill supporting pluggable discovery providers (doctl, vultr-cli, manual) and pluggable tool registrations (nginx, docker, ...). Use when the user asks to audit or upgrade any registered software tool across a fleet of VMs.
---

# Fleet Upgrade Skill

Gated fleet operations: read-only audit first, explicit approval before any change,
verified backup before every upgrade, canary then serial rollout, and full rollback
(package + config).

## When to use

- The user asks which fleet VMs can upgrade a specific tool today.
- The user approves an upgrade set and wants it executed with backups.
- A VM failed after an upgrade and must be rolled back.
- The user wants VMs discovered from a cloud provider or manual inventory.
- The user wants to register a new tool or provider via configuration files.

## When NOT to use

- Provisioning new VMs or changing application configs.
- Upgrading non-apt installs (out of scope).
- Any VM outside the `ip.txt` inventory.

## Files

| Path | Role |
|---|---|
| `.specific/{tool}.yaml` | Tool registration config (`config --init --type tool --name`). |
| `.specific/{provider}.yaml` | Provider registration config (`config --init --type provider --name`). |
| `.personal/ssh.env` | `SSH_USER`, `SSH_KEY`, `SSH_PORT`; mode 0600; never committed. |
| `ip.txt` | Fleet roster, `Name,IP` per line. |
| `plan/{ip}.md` | Per-VM record rendered from state. |
| `backups/{ip}/` | Verified local config archives. |
| `.fleet/state.json` | Run state (source of truth). |

Resolve this skill's directory and invoke the CLI by absolute path:
`python3 "$SKILL_DIR/scripts/fleet.py"`.

## Procedure

1. **Preflight** — `doctor --provider NAME`; if `.personal/ssh.env` is missing, ask for credentials and write mode 0600.
2. **Discover** — `discover --provider NAME`; show added/removed IPs.
3. **Audit** — `survey --tool NAME --all`; every VM gets a verdict and `plan/{ip}.md`. Nothing is modified.
4. **Summary GATE** — show grouped table; ask which `UPGRADE` VMs to include. BLOCKED/UNREACHABLE VMs cannot be approved.
5. **Canary** — after approval, `execute --phase canary --approve <ip> --yes`. Use `--mode migrate` to bootstrap upstream repo.
6. **Canary GATE** — show result; ask proceed or stop. Record with `gate --decision proceed|stop`.
7. **Fleet** — `execute --phase fleet --approve <ips> --yes` with serial execution.
8. **Report** — `report --log` (one appended `LOGS.md` entry).

## Commands

```bash
fleet.py doctor [--provider NAME]
fleet.py discover --provider NAME [--output ip.txt]
fleet.py survey --tool NAME [--all|--ips IP[,IP]] [--concurrency N] [--dry-run]
fleet.py summary [--tool NAME]
fleet.py execute --phase canary|fleet --tool NAME --approve IP[,IP] [--yes] [--dry-run]
fleet.py gate --decision proceed|stop [--note TEXT]
fleet.py rollback --tool NAME --ip IP [--yes] [--dry-run]
fleet.py report --tool NAME [--log]
fleet.py config --init --type tool|provider --name NAME [--force]
fleet.py survey --list-tools
```

All commands accept `--json` flag for JSON output. Exit codes: `0` success,
`2` config/usage, `3` gate refused, `4` VM failure, `5` preflight/discovery.

## Gates

- No mutation without `--yes` plus an approved set of `UPGRADE` IPs.
- No fleet execution without a recorded canary `proceed`.
- A missing or empty backup aborts that VM before any change.

## Registration

Register a new tool:
```bash
fleet.py config --init --type tool --name docker --force
```

Register a new provider:
```bash
fleet.py config --init --type provider --name vultr --force
```

Edit the generated `.specific/{name}.yaml` with appropriate values, then run `doctor`.

## Safety rules

- Read-only until the summary GATE; never auto-fix BLOCKED VMs.
- Full rollback restores both package version AND configuration.
- Never commit credentials, `ip.txt`, `plan/`, `backups/`, or `.fleet/`.
- Serial fleet execution limits blast radius to one VM at a time.
- Retry-once policy before marking a VM as FAILED.

## Verification

```bash
# Audit verification
python3 -m unittest discover -s .agents/skills/fleet-upgrade/scripts/tests \
  -t .agents/skills/fleet-upgrade/scripts -k verdict -k survey -k inventory -k audit_flow -v

# Rollout verification
python3 -m unittest discover -s .agents/skills/fleet-upgrade/scripts/tests \
  -t .agents/skills/fleet-upgrade/scripts -k execute -k rollout -v

# Rollback verification
python3 -m unittest discover -s .agents/skills/fleet-upgrade/scripts/tests \
  -t .agents/skills/fleet-upgrade/scripts -k rollback -v

# Report verification
python3 -m unittest discover -s .agents/skills/fleet-upgrade/scripts/tests \
  -t .agents/skills/fleet-upgrade/scripts -k report -v
```

Fixture-based tests cover verdict logic, parsing, ledger/guards, dry runs, canary and
fleet flow, retry-once, rollback, and append-only reporting.
