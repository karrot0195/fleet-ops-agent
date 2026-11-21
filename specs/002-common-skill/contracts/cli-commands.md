# Contract: CLI Commands

**Version**: 1.0 | **Status**: Draft

## Overview

The fleet upgrade skill exposes a CLI via `fleet.py`. All commands accept `--json` for machine-readable output and `--root` to specify the project root.

## Commands

### doctor

Preflight checks: config validity, SSH credentials, provider CLI availability.

```bash
fleet.py --root . doctor
```

**Exit codes**:
- 0: All checks passed
- 2: Config invalid
- 5: Preflight failed (missing executables, SSH env)

**Output**:
```
config: .specific/nginx-fleet.yaml
ssh env: .personal/ssh.env
ssh user: root
ssh key: ~/.ssh/id_ed25519
executables: ssh, scp, doctl
doctl auth: ok
```

---

### discover

Refresh fleet inventory from the selected provider.

```bash
fleet.py --root . discover [--provider NAME] [--file PATH]
```

**Options**:
- `--provider`: Override the configured provider (e.g., `doctl`, `vultr`, `manual`)
- `--file`: For `manual` provider, path to inventory file (default: `ip.txt`)

**Exit codes**:
- 0: Discovery succeeded
- 5: Discovery failed (provider error, auth failure)

**Output**:
```
inventory: 12 VM(s) from doctl
added: 192.0.2.10
removed: none
```

---

### survey

Read-only audit of fleet VMs for a specific tool.

```bash
fleet.py --root . survey --tool NAME --all [--parallel N]
fleet.py --root . survey --tool NAME --ip IP [--ip IP]
```

**Options**:
- `--tool`: Tool to audit (required)
- `--all`: Audit all VMs in inventory
- `--ip`: Audit specific VM(s)
- `--parallel`: Concurrent survey threads (default: 4, max: 16)

**Exit codes**:
- 0: Survey completed
- 2: Tool config invalid
- 5: No inventory captured (run `discover` first)

**Output**:
```
web-01 (192.0.2.1): UPGRADE (1.24.0 → 1.25.3)
web-02 (192.0.2.2): UP-TO-DATE (1.25.3)
web-03 (192.0.2.3): BLOCKED (config test failed)
web-04 (192.0.2.4): UNREACHABLE (connection timeout)
```

---

### summary

Show grouped verdicts and eligible VMs for upgrade.

```bash
fleet.py --root . summary [--tool NAME]
```

**Options**:
- `--tool`: Filter by tool (default: all tools)

**Exit codes**:
- 0: Summary displayed

**Output**:
```
UPGRADE: 3 VMs
  web-01 (192.0.2.1): 1.24.0 → 1.25.3
  web-05 (192.0.2.5): 1.24.0 → 1.25.3
  web-06 (192.0.2.6): 1.24.0 → 1.25.3
UP-TO-DATE: 5 VMs
BLOCKED: 1 VM
  web-03 (192.0.2.3): config test failed
UNREACHABLE: 1 VM
  web-04 (192.0.2.4): connection timeout

eligible: web-01, web-05, web-06
```

---

### execute

Run canary or fleet upgrade for a tool.

```bash
fleet.py --root . execute --tool NAME --phase canary --approve IP --yes [--dry-run]
fleet.py --root . execute --tool NAME --phase fleet --approve IP[,IP] --yes [--dry-run]
```

**Options**:
- `--tool`: Tool to upgrade (required)
- `--phase`: `canary` (single VM) or `fleet` (multiple VMs, serial)
- `--approve`: Comma-separated list of IPs to upgrade
- `--yes`: Required for execution (safety gate)
- `--dry-run`: Show what would be done without executing

**Exit codes**:
- 0: Execution succeeded
- 3: Approval refused (non-UPGRADE IP, missing canary proceed)
- 4: VM failure (one or more VMs failed)

**Output**:
```
192.0.2.1: SUCCEEDED (1.24.0 → 1.25.3)
```

---

### gate

Record the canary decision (proceed or stop).

```bash
fleet.py --root . gate --decision proceed|stop [--note TEXT]
```

**Options**:
- `--decision`: `proceed` or `stop` (required)
- `--note`: Optional comment

**Exit codes**:
- 0: Decision recorded
- 3: Canary has not reached terminal state

**Output**:
```
canary decision recorded: proceed
```

---

### rollback

Restore a failed VM to its pre-upgrade state (package + config).

```bash
fleet.py --root . rollback --tool NAME --ip IP --yes [--dry-run]
```

**Options**:
- `--tool`: Tool to rollback (required)
- `--ip`: VM IP to rollback (required)
- `--yes`: Required for rollback (safety gate)
- `--dry-run`: Show what would be done without executing

**Exit codes**:
- 0: Rollback succeeded
- 4: Rollback failed or refused

**Output**:
```
192.0.2.1: rollback SUCCEEDED (config_ok=true, package_ok=true, service_active=true)
```

---

### report

Generate fleet upgrade report.

```bash
fleet.py --root . report [--tool NAME] [--log]
```

**Options**:
- `--tool`: Filter by tool (default: all tools)
- `--log`: Append summary to `LOGS.md`

**Exit codes**:
- 0: Report generated

**Output**:
```
Fleet Upgrade Report
====================
Tool: nginx
Run ID: 20261121-143022
Date: 2026-11-21 14:30:22 UTC

VM              Old Version  New Version  Status      Backup
----            -----------  -----------  ------      ------
web-01          1.24.0       1.25.3       SUCCEEDED   backups/192.0.2.1/nginx-20261121-143022.tar.gz
web-02          1.24.0       1.25.3       SUCCEEDED   backups/192.0.2.2/nginx-20261121-143022.tar.gz
web-03          1.24.0       -            FAILED      backups/192.0.2.3/nginx-20261121-143022.tar.gz

Summary: 2 succeeded, 1 failed, 0 rolled back
```

---

### config

Initialize tool or provider configuration.

```bash
fleet.py --root . config --init --type tool --name NAME [--force]
fleet.py --root . config --init --type provider --name NAME [--force]
```

**Options**:
- `--init`: Initialize config (required)
- `--type`: `tool` or `provider` (required)
- `--name`: Name of tool/provider (required)
- `--force`: Overwrite existing config

**Exit codes**:
- 0: Config created
- 2: Config already exists (use `--force`)

**Output**:
```
wrote .specific/docker.yaml
```

---

## Global Options

| Option | Description |
|--------|-------------|
| `--root PATH` | Project root (default: `.`) |
| `--config PATH` | Config file path (default: auto-detect) |
| `--json` | Machine-readable JSON output |
| `--log-level LEVEL` | Logging level: `debug`, `info`, `warn`, `error` (default: `info`) |

## JSON Output Format

All commands support `--json` for machine-readable output:

```json
{
  "schema_version": 1,
  "ok": true,
  "command": "survey",
  "run_id": "20261121-143022",
  "data": { ... },
  "warnings": [],
  "error": null
}
```

Error responses:

```json
{
  "schema_version": 1,
  "ok": false,
  "command": "execute",
  "run_id": "20261121-143022",
  "data": null,
  "warnings": [],
  "error": {
    "code": "ExecutionError",
    "message": "VM 192.0.2.3 failed: upgrade command exited 1",
    "exit_code": 4
  }
}
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Config/usage error |
| 3 | Gate refused (approval denied) |
| 4 | VM failure (one or more VMs failed) |
| 5 | Preflight/discovery error |
