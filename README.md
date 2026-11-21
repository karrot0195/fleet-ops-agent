# fleet-ops-agent

Automated, safety-gated upgrades for **nginx** across a fleet of DigitalOcean VMs.

The `fleet-upgrade` Agent Skill audits every VM in the fleet, writes a per-VM
plan, and — once you approve — upgrades nginx with verified backups and full rollback
capability. Rollouts run canary-first, then across the fleet.

## What it does

- **Discovery** — syncs the VM roster from a pluggable provider (DigitalOcean via `doctl`
  today; Vultr and manual inventories supported).
- **Audit** — read-only survey of each VM: nginx presence, installed vs. candidate
  version, config drift, held packages, origin checks, health.
- **Planning** — writes the per-VM audit/execution record to `plan/{ip}.md`.
- **Gated execution** — summary identifies eligible (`UPGRADE`) VMs; canary executes the
  approved VM; a recorded `gate --decision proceed` unlocks the fleet phase; fleet rolls out
  the approved set (bounded concurrency, retry-once).
- **Rollback** — configuration + package restore from verified local backups.
- **Reporting** — per-VM before/after report, optional append-only `LOGS.md` entry.

## Safety model

- **Safety First** — every change is preceded by a local backup and a working rollback path;
  backups are checksum-verified before use, and a missing/empty backup aborts the VM before
  any mutation.
- **Explicit Confirmation Gates** — execution never begins before the user confirms the
  summarized per-VM plan.
- **Per-VM Traceability** — every audited or modified VM has a plan under `plan/{ip}.md`.
- **Change Only What Is Needed** — config updates are justified by the audit; minimal diffs only.
- **Scripted and Idempotent** — all steps are reproducible and safe to re-run.

## Prerequisites

- Python 3.11+ (tested on 3.14), PyYAML, OpenSSH client.
- `doctl` authenticated, with operator access to the fleet.
- A usable SSH key; `.personal/ssh.env` (`SSH_USER`, `SSH_KEY`, `SSH_PORT`, mode `0600`).

## Setup

```bash
python3 .agents/skills/fleet-upgrade/scripts/fleet.py config --init --type tool --name nginx --force
python3 .agents/skills/fleet-upgrade/scripts/fleet.py config --init --type provider --name doctl --force
python3 .agents/skills/fleet-upgrade/scripts/fleet.py doctor
```

If `.personal/ssh.env` is missing, create it with `SSH_USER`, `SSH_KEY`, and `SSH_PORT`
(values, mode `0600`) before running any mutating command.

## Usage

The workflow is a fixed command sequence; run each command from the repository root.
Typical run: discover → audit (`survey` + `summary`) → approve → canary → gate → fleet →
rollback/report as needed.

### 1. Discover

```bash
python3 .agents/skills/fleet-upgrade/scripts/fleet.py discover --provider doctl
```

### 2. Audit

```bash
python3 .agents/skills/fleet-upgrade/scripts/fleet.py survey --tool nginx --all
python3 .agents/skills/fleet-upgrade/scripts/fleet.py summary
```

### 3. Approve and execute

```bash
# preview the canary (no mutation)
python3 .agents/skills/fleet-upgrade/scripts/fleet.py execute --phase canary --tool nginx --approve <ip> --dry-run

# execute the canary
python3 .agents/skills/fleet-upgrade/scripts/fleet.py execute --phase canary --tool nginx --approve <ip> --yes

# after a healthy canary, record the gate decision and (if proceeding) run the fleet
python3 .agents/skills/fleet-upgrade/scripts/fleet.py gate --decision proceed --note "canary healthy"
python3 .agents/skills/fleet-upgrade/scripts/fleet.py execute --phase fleet --tool nginx --approve 203.0.113.10,203.0.113.11 --yes
```

`--dry-run` prints the exact per-VM steps — backup, precheck, upgrade, verify, drift — and
changes nothing; approving a `BLOCKED`, `UNREACHABLE`, `SKIP`, or `UP-TO-DATE` IP exits `3`
with no mutation. `--yes` is required for execution, and `--approve` takes a
comma-separated list of IPs (e.g. `--approve 203.0.113.10,203.0.113.11`).

The `gate` decision (`proceed` or `stop`) controls whether the fleet phase may run after
the canary; `proceed` unlocks `execute --phase fleet`.

`--mode {none,migrate}` controls pre-upgrade bootstrap: `migrate` bootstraps the upstream
apt repository before upgrading (used when migrating from a distro repo to an upstream
repo, e.g. nginx's own package repository).

### 4. Rollback

```bash
# preview (no mutation)
python3 .agents/skills/fleet-upgrade/scripts/fleet.py rollback --tool nginx --ip <ip> --dry-run

# execute
python3 .agents/skills/fleet-upgrade/scripts/fleet.py rollback --tool nginx --ip <ip> --yes
```

### 5. Report

```bash
python3 .agents/skills/fleet-upgrade/scripts/fleet.py report --tool nginx --log
```

### 6. Register a new tool (optional)

```bash
python3 .agents/skills/fleet-upgrade/scripts/fleet.py config --init --type tool --name docker --force
```

Edit the generated `.specific/docker.yaml` with the package, service, config paths, version
query, precheck, and health-check settings, then re-run `doctor`.

## Command reference

| Command | Flags | Purpose | Mutating |
|---|---|---|---|
| `doctor` | `--provider NAME` | Preflight: config, SSH env, provider CLI/auth | No |
| `discover` | `--provider NAME`, `--output PATH` | Fetch fleet inventory, write `ip.txt` | No |
| `survey` | `--tool NAME`, `--all`, `--ips IP[,IP]`, `--concurrency N`, `--dry-run` | Read-only audit; writes `plan/{ip}.md` | No |
| `summary` | `--tool NAME` | Grouped verdicts + eligible (`UPGRADE`) set | No |
| `execute` | `--tool NAME`, `--phase {canary,fleet}`, `--approve IP[,IP]`, `--yes`, `--dry-run`, `--mode {none,migrate}` | Canary/fleet rollout | Yes |
| `gate` | `decision {proceed,stop}`, `--note TEXT` | Record canary gate decision | Yes |
| `rollback` | `--tool NAME`, `--ip IP`, `--yes`, `--dry-run` | Restore VM from verified backup | Yes |
| `report` | `--tool NAME`, `--log` | Print report; optionally append to `LOGS.md` | No (append-only with `--log`) |
| `config` | `--init`, `--type {tool,provider}`, `--name NAME`, `--force`, `--path PATH` | Initialize tool/provider config | Yes |

All commands accept `--json` for machine-readable output.

## Interpreting results

Audit verdicts are `UPGRADE`, `UP-TO-DATE`, `SKIP`, `BLOCKED`, or `UNREACHABLE`:

- `UPGRADE` — old → new version available; eligible for execution.
- `UP-TO-DATE` — installed version already matches the candidate.
- `SKIP` — nothing to do for this VM.
- `BLOCKED` — held package, failed config test, unexpected package origin, or no candidate version.
- `UNREACHABLE` — connectivity failure; no evidence collected.

Only `UPGRADE` VMs appear in the eligible set used for approval; pass those IPs into the
next `--approve`. `BLOCKED`/`UNREACHABLE` VMs are data, not command failures — audits exit
`0` even when they find them.

For `BLOCKED` VMs, resolve the underlying cause (held package, config test failure,
package origin, candidate version) before retrying; for `UNREACHABLE` VMs, verify SSH
connectivity and credentials, then re-run the survey.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success (including audits that found `BLOCKED`/`UNREACHABLE` VMs). |
| `1` | Unexpected internal error. |
| `2` | Usage or configuration error. |
| `3` | Gate/approval refused. |
| `4` | One or more VMs failed execution/rollback. |
| `5` | Preflight/discovery failure. |

During execute/rollback, per-VM failures surface as exit `4`; gate refusals as exit `3`.

## Project layout

```text
upgrade-VM/
├── .agents/skills/fleet-upgrade/   # Agent Skill + fleetkit/ Python CLI
├── .specific/                       # tool / provider / fleet configs
├── ip.txt                           # fleet roster (Name,IP)
├── plan/{ip}.md                     # per-VM audit & execution records
├── backups/{ip}/                    # verified local config backups
├── .fleet/                          # run state (source of truth)
├── LOGS.md                          # append-only audit trail
└── specs/                           # spec / plan / tasks / quickstart docs
```

`.personal/`, `backups/`, `ip.txt`, `plan/`, and `.fleet/` are not committed (see
`.gitignore`); credentials and fleet inventory stay local.

## Development and tests

```bash
python3 -m compileall -q .agents/skills/fleet-upgrade/scripts/fleet.py .agents/skills/fleet-upgrade/scripts/fleetkit
python3 -m unittest discover -s .agents/skills/fleet-upgrade/scripts/tests -t .agents/skills/fleet-upgrade/scripts -v
```

The suite covers verdict logic, parsing, guards, dry runs, canary and fleet flow, retry-once,
rollback, and append-only reporting. Integration tests use fake `doctl`/`ssh`/`scp`
executables from `tests/fixtures/bin`; no network is used.

## Further reading

- [`specs/001-nginx-fleet-upgrade/quickstart.md`](specs/001-nginx-fleet-upgrade/quickstart.md) — runnable validation scenarios.
- [`specs/001-nginx-fleet-upgrade/spec.md`](specs/001-nginx-fleet-upgrade/spec.md) — requirements and design.
- [`specs/002-common-skill/`](specs/002-common-skill/) — common-skill contracts (tool registry, providers).
