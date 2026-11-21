# CLI Contract: `fleet.py`

Entry point: `.agents/skills/nginx-fleet-upgrade/scripts/fleet.py`.
The skill resolves its own directory and invokes the absolute path; operators may
also call it directly.

## Global options

| Option | Default | Meaning |
|---|---|---|
| `--root PATH` | current directory | Project root holding `ip.txt`, `plan/`, `backups/`, `.fleet/`, `LOGS.md`, `.personal/`. |
| `--config PATH` | `<root>/.specific/nginx-fleet.yaml` | Config file; validated before any network call. |
| `--json` | off | Machine-readable output (one JSON envelope on stdout; logs on stderr). |
| `--log-level {debug,info,warn,error}` | `info` | Log verbosity; secrets are never logged. |

Human output goes to stdout, diagnostics to stderr. Exit codes are stable for agent
logic and must not be repurposed.

## Commands

### `doctor`

Read-only preflight: validates config, resolves the SSH env file and key (mode
warning if group/world-readable), checks `ssh`/`scp`/`doctl` availability, and tests
`doctl auth`. Never contacts a VM. Exit 5 on failure.

### `discover [--source doctl|file] [--file PATH] [--json]`

Read-only with respect to VMs. Fetches the active fleet, writes `ip.txt`
(`Name,IP`, sorted, deduped), stores the snapshot, and reports `added`/`removed` IPs.
An empty fleet is a successful discovery reported explicitly. Exit 5 when `doctl`
auth or output is unusable.

### `survey [--all | --ip IP ...] [--parallel N] [--json]`

Read-only. Surveys selected VMs (default `--all`) with connectivity preflight, assigns
one verdict each, writes state and `plan/{ip}.md`, and prints a grouped summary.
`--parallel` defaults to `execution.concurrency`. Exit 0 even when some VMs are
`UNREACHABLE`/`BLOCKED` (they are data, not command failures); exit 5 when no VM could
be reached or config/SSH is unusable.

### `summary [--json]`

Read-only. Prints the grouped verdict table and the eligible (`UPGRADE`) set used for
approval. JSON shape includes `groups` and `eligible` so the skill can build the GATE
question without re-parsing prose.

### `gate --decision {proceed,stop} [--note TEXT] [--json]`

Records the canary decision in state. Refuses (exit 3) unless the canary has reached a
terminal state in the current run. `proceed` unlocks `execute --phase fleet`; `stop`
marks the run stopped and blocks further execution.

### `execute --phase {canary,fleet} --approve IP[,IP...] [--concurrency N] [--dry-run] [--yes] [--json]`

Mutating only without `--dry-run`.

Preconditions (validated before any SSH mutation, fail closed with exit 3):

- `--yes` is present.
- Every approved IP is in the current inventory with verdict `UPGRADE`.
- The approved set is non-empty and deduplicated.
- For `fleet`: the canary reached a terminal state and `gate --decision proceed` was
  recorded in this run.
- A verified backup is obtained for each VM before any change to that VM.

Behavior:

- `canary`: processes exactly the first approved VM not already terminal in this run;
  records the result; exits 0 on success, 4 if the VM failed (state still records it).
- `fleet`: processes remaining approved VMs with bounded concurrency; a failed VM is
  retried exactly once, then marked `FAILED`; other VMs are unaffected (exit 4 if any
  VM ends `FAILED`).
- Idempotency: a VM already `SUCCEEDED` in this run is skipped; a VM whose installed
  version is already at least the candidate is recorded `UP-TO-DATE` and skipped
  (FR-018).
- `--dry-run` prints the exact planned per-VM steps and commands without contacting a
  VM or changing state.

### `rollback --ip IP [--dry-run] [--yes] [--json]`

Mutating only without `--dry-run`. Requires a recorded `FAILED`/`ROLLED_BACK`-eligible
VM with a verified local backup. Uploads the verified archive, archives the current
config as `*-pre-rollback`, extracts over configured config paths, runs the precheck,
and restarts the service only when the precheck passes. The package version is never
downgraded (FR-015). Exit 4 if the VM did not return to a healthy state.

### `report [--log] [--json]`

Read-only plus optional append. Prints the final per-VM table (old → new, backup path,
verification, drift). With `--log`, appends exactly one dated entry to
`paths.log_file` and records `report.logged_at` so a repeat does not duplicate it;
prior content is never modified (FR-016).

### `config --init [--force]`

Writes `.specific/nginx-fleet.yaml` from the bundled template. Refuses to overwrite an
existing file unless `--force` is given. No network access.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success (including audits that found BLOCKED/UNREACHABLE VMs). |
| `1` | Unexpected internal error. |
| `2` | Usage or configuration error (bad flags, invalid config, bad IP). |
| `3` | Gate/approval refused (unapproved, non-eligible IP, missing `--yes`, missing canary `proceed`, canary decision premature). |
| `4` | One or more VMs failed execution/rollback, or a run ended partial. |
| `5` | Preflight/discovery failure (doctl, SSH env, no reachable VMs, unusable state). |

## JSON envelope

Every `--json` invocation prints exactly one object:

```json
{
  "schema_version": 1,
  "ok": true,
  "command": "survey",
  "run_id": "20261120T140500Z-a1b2c3",
  "data": {},
  "warnings": [],
  "error": null
}
```

On failure, `ok` is `false`, `data` is `null` or partial, and `error` is
`{"code": "...", "message": "...", "exit_code": 3}`. Messages never contain secrets.

## File contracts

### `ip.txt`

`Name,IP` one pair per line; UTF-8; sorted by name; deduped by IP; no header. This is
both the human-readable fleet roster and the input for `--source file`.

### `.personal/ssh.env`

Shell-style `KEY=value` lines:

```text
SSH_USER=root
SSH_KEY=/home/operator/.ssh/id_ed25519
SSH_PORT=22
```

Mode `0600`. Values are read only; the CLI never writes secrets and only writes this
file during the skill's access GATE.

### `LOGS.md`

Append-only. `report --log` adds:

```text
YYYY-MM-DD HH:MM: <short title>
<one-line summary>
```

with a blank line separation; existing entries are never reordered or rewritten.

### Per-VM records

`plan/{ip}.md` follows [`record.md`](./record.md) and is overwritten only for the IP
being re-rendered.
