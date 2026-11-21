# Phase 1 Data Model: nginx Fleet Upgrade

All state is file-based. `.fleet/state.json` is the machine source of truth;
`plan/{ip}.md` is a deterministic human-readable projection of the same data.
Entity names here are conceptual; the persisted field names are defined by
[`contracts/state.schema.json`](./contracts/state.schema.json).

## FleetConfig

Operator settings, loaded from `.specific/nginx-fleet.yaml` (see
[`contracts/config.schema.yaml`](./contracts/config.schema.yaml)). Non-secret only.

| Field | Type | Default | Validation |
|---|---|---|---|
| `apiVersion` | string | `nginx-fleet-upgrade/v1` | Must match exactly. |
| `fleet.inventory_file` | path | `ip.txt` | Relative to project root; must be writable. |
| `fleet.source` | enum | `doctl` | `doctl` \| `file`. |
| `paths.records_dir` | path | `plan` | Created on demand. |
| `paths.backups_dir` | path | `backups` | Created on demand. |
| `paths.state_dir` | path | `.fleet` | Created on demand; must be gitignored. |
| `paths.log_file` | path | `LOGS.md` | Append-only target. |
| `ssh.env_file` | path | `.personal/ssh.env` | Must define `SSH_USER`, `SSH_KEY`, `SSH_PORT`. |
| `ssh.connect_timeout` | int (s) | `5` | `1..60`. |
| `ssh.command_timeout` | int (s) | `60` | `5..3600`. |
| `ssh.strict_host_key_checking` | enum | `accept-new` | `accept-new` \| `yes`. |
| `ssh.privilege` | enum | `auto` | `auto` \| `sudo` \| `root`. `auto` uses `sudo -n` when UID ≠ 0. |
| `execution.concurrency` | int | `4` | `1..16`. |
| `execution.canary_size` | int | `1` | Exactly `1` for this feature (FR-012). |
| `execution.retry_rounds` | int | `1` | `0..1`; FR-013 requires exactly one. |
| `execution.upgrade_command` | template | apt command (D10) | Must contain `{package}`; executed only after backup verification. |
| `tool.name` / `tool.package` / `tool.service` | string | `nginx` | Non-empty. |
| `tool.config_paths` | list[path] | `[/etc/nginx]` | Non-empty; used for backup and restore. |
| `tool.version_query` | command | `dpkg-query ... nginx` | Must print a Debian version. |
| `tool.precheck` | command | `nginx -t` | Exit 0 required. |
| `tool.allowed_origin_patterns` | list[string] | distro hosts (schema default) | Suffix/substring match against `apt-cache policy` sources. |
| `tool.hold_patterns` | list[glob] | `nginx`, `nginx-*` | Any `apt-mark showhold` match blocks. |
| `tool.allowed_dynamic_module_dirs` | list[path] | `[/usr/lib/nginx/modules]` | `load_module` outside these paths blocks. |
| `tool.verify.http` / `.https` | object | `127.0.0.1`, port 80/443 | Timeout `1..60`; HTTPS `enabled: auto`. |
| `tool.verify.require_status` | list[int] | `[]` | Empty = any HTTP response counts. |
| `tool.drift_patterns` | list[glob] | `*.dpkg-dist`, `*.dpkg-new`, `*.ucf-dist` | Drift flags only; never auto-merged. |

Invalid or missing configuration is a usage error (exit 2) before any network call.

## FleetInventory

One snapshot per run, persisted in state; written in human-readable form to
`ip.txt` (`Name,IP`).

| Field | Type | Validation |
|---|---|---|
| `captured_at` | ISO-8601 UTC | Set by `discover`. |
| `source` | enum | `doctl` \| `file`. |
| `entries[].name` | string | Non-empty, no comma or newline. |
| `entries[].ip` | string | Valid IPv4. |
| `entries[].status` | string | Provider status; `active` required for inclusion. |
| `entries[].first_seen` / `last_seen` | ISO-8601 | Persisted across runs. |
| `added[]` / `removed[]` | list[ip] | Diff versus the previous snapshot, compared on IP. |

Rules: dedupe by IP (first name wins), sort by name, keep the file format
`Name,IP` per line (FR-001). An empty fleet is valid and must be reported.

## VMRecord

Exactly one per inventory IP, including UNREACHABLE entries (FR-005, FR-006).

| Field | Type | Notes |
|---|---|---|
| `name` / `ip` | string | From inventory. |
| `verdict` | enum | `SKIP` \| `UP-TO-DATE` \| `UPGRADE` \| `BLOCKED` \| `UNREACHABLE`. |
| `reason` | string \| null | Required when `BLOCKED` or `UNREACHABLE`; null otherwise. |
| `evidence` | SurveyEvidence \| null | Null only for `UNREACHABLE`. |
| `execution` | ExecutionResult \| null | Populated by `execute`. |
| `backup` | ConfigBackup \| null | Populated before mutation. |
| `drift_flags` | list[DriftFlag] | From post-upgrade check. |
| `rollback` | RollbackResult \| null | Populated by `rollback`. |
| `timestamps.surveyed_at` / `.executed_at` / `.rolled_back_at` | ISO-8601 | Nullable. |

Verdict precedence is fixed (D7): `UNREACHABLE` → `SKIP` → `BLOCKED` →
`UP-TO-DATE` → `UPGRADE`. A VM that is current but fails the config test is
`BLOCKED`, not `UP-TO-DATE`.

## SurveyEvidence

Read-only facts collected per reachable VM (FR-004).

| Field | Type | Source |
|---|---|---|
| `os` | string | `/etc/os-release` `PRETTY_NAME`. |
| `binary_present` | bool | `command -v <tool.package>`; distinguishes SKIP from a source build. |
| `installed_version` | string \| null | `tool.version_query`. |
| `candidate_version` | string \| null | `apt-cache policy` candidate. |
| `package_origin` | string \| null | `apt-cache policy` source URL. |
| `held_packages` | list[string] | `apt-mark showhold`. |
| `modules.static` | list[string] | `nginx -V` `--with-*_module`. |
| `modules.dynamic` | list[string] | `load_module` paths + `--add-dynamic-module`. |
| `third_party_modules` | list[string] | Deviation from the core/allowed set. |
| `service_active` / `service_enabled` | bool \| null | `systemctl is-active/is-enabled`. |
| `tls_present` | bool | `ssl_certificate` in enabled config. |
| `server_blocks` | int | Count of `server {` blocks in enabled config. |
| `config_test_ok` | bool | `tool.precheck` exit status. |
| `privilege` | string | `root` or `sudo -n` result. |

## ConfigBackup

Created before the first change to a VM; verified before use (FR-009).

| Field | Type | Validation |
|---|---|---|
| `remote_path` | string | `/var/backups/nginx-<epoch>.tar.gz`. |
| `local_path` | string | `backups/{ip}/nginx-<epoch>.tar.gz`. |
| `size_bytes` | int | Must be `> 0`. |
| `sha256` | string | Recomputed after download; mismatch aborts the VM. |
| `verified` | bool | Must be `true` before upgrade or rollback. |
| `created_at` | ISO-8601 | — |

## ExecutionResult

| Field | Type | Notes |
|---|---|---|
| `phase` | enum | `canary` \| `fleet`. |
| `state` | enum | `PENDING` \| `RUNNING` \| `SUCCEEDED` \| `FAILED` \| `ROLLED_BACK`. |
| `steps[]` | StepResult | `backup`, `precheck`, `upgrade`, `verify`, `drift`. |
| `old_version` / `new_version` | string \| null | Recorded from evidence/verification. |
| `verification` | object \| null | `config_ok`, `service_active`, `version_matches`, `http_status`, `https_status`. |
| `attempts` | int | `1..2`; two attempts = initial + one retry (FR-013). |
| `error` | string \| null | Failure summary; no secrets. |

A failure at any step stops that VM only; other VMs continue (SC-004).

## ApprovalDecision and CanaryGate

| Entity | Fields | Rules |
|---|---|---|
| ApprovalDecision | `approved_ips[]`, `excluded_ips[]`, `approved_at`, `note` | Non-empty; every IP must exist in the inventory and have verdict `UPGRADE`; otherwise `execute` exits 3 without mutating anything (FR-007, FR-008). |
| CanaryGate | `decision` (`proceed` \| `stop`), `decided_at`, `note` | Required after the canary reaches a terminal state; `stop` ends the run; `proceed` is required for `execute --phase fleet` (FR-012). |

## DriftFlag

| Field | Type | Notes |
|---|---|---|
| `pattern` | string | Matched drift glob. |
| `path` | string | File found on the VM. |
| `needs_manual_review` | bool | Always `true`; nothing is auto-merged (FR-011, FR-016). |

## RunState

| Field | Type | Rules |
|---|---|---|
| `schema_version` | int | `1`; incompatible versions are rejected. |
| `run_id` | string | `<UTC timestamp>-<short random>`; one per discover→report cycle. |
| `created_at` / `updated_at` | ISO-8601 | Atomic writes (temp + rename). |
| `inventory` | FleetInventory | Latest snapshot. |
| `records` | map[ip → VMRecord] | Keys are inventory IPs only. |
| `approvals` | list[ApprovalDecision] | Append-only within a run. |
| `gates` | list[CanaryGate] | Append-only within a run. |
| `report` | object | `written_at`, `logged_at` (idempotent log guard). |

State writes are serialized in the orchestrating thread; worker threads return
results and never write state directly.

## State transitions

```text
DISCOVERED ──survey(ok)──────────→ SURVEYED{SKIP,UP-TO-DATE,UPGRADE,BLOCKED}
     │                                   │
     └──connectivity fails──→ UNREACHABLE│
                                         ├─ non-UPGRADE ──→ EXCLUDED (terminal for this run)
                                         └─ UPGRADE ──approve──→ APPROVED
APPROVED ──phase=canary──→ CANARY_RUNNING ──→ CANARY_SUCCEEDED | CANARY_FAILED
CANARY_SUCCEEDED ──gate(proceed)──→ eligible for FLEET
CANARY_* ──gate(stop)──→ RUN_STOPPED (terminal; no further upgrades)
APPROVED (remaining) ──phase=fleet──→ FLEET_RUNNING ──ok──→ SUCCEEDED (terminal)
                                              └──fail──→ RETRY_QUEUED (max 1)
RETRY_QUEUED ──→ FLEET_RUNNING ──ok──→ SUCCEEDED | ──fail──→ FAILED (terminal)
FAILED ──rollback(approved)──→ ROLLED_BACK (terminal; package stays new)
```

Invariants:

- No transition into `CANARY_RUNNING`/`FLEET_RUNNING` without a matching approval
  record, a verified backup, and (for fleet) a `proceed` gate.
- `attempts` never exceeds `1 + execution.retry_rounds` (max 2).
- Re-running discover/survey never mutates a VM; re-running execute on a VM whose
  installed version is already at least the candidate yields `UP-TO-DATE`
  (FR-018, SC-007).
- `plan/{ip}.md` exists for every inventory IP after survey, including
  `UNREACHABLE` records with the connectivity failure reason and no evidence
  (SC-001).
