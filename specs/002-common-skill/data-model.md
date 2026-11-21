# Data Model: Common Fleet Upgrade Skill

**Feature**: 002-common-skill | **Date**: 2026-11-21

## Entities

### ToolConfig

Represents a registered software tool eligible for fleet upgrades.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| apiVersion | string | yes | Schema version: `fleet-upgrade-tool/v1` |
| tool.name | string | yes | Unique identifier (e.g., `nginx`, `docker`) |
| tool.package | string | yes | OS package name (e.g., `nginx`, `docker-ce`) |
| tool.service | string | yes | Systemd service name (e.g., `nginx`, `docker`) |
| tool.config_paths | list[string] | yes | Paths to backup/restore (e.g., `["/etc/nginx"]`) |
| tool.version_query | string | yes | Command to query installed version |
| tool.precheck | string | yes | Command to verify tool health (e.g., `nginx -t`) |
| tool.allowed_origin_patterns | list[string] | no | Package origin allowlist for survey |
| tool.hold_patterns | list[string] | no | Package hold patterns to detect |
| tool.drift_patterns | list[string] | no | File patterns indicating config drift |
| tool.verify | object | no | Post-upgrade verification (http/https checks) |
| migration.enabled | bool | no | Whether migration mode is available |
| migration.repo_url | string | cond | Upstream repo URL (required if migration enabled) |
| migration.repo_dist | string | cond | Distribution codename |
| migration.key_url | string | cond | Signing key URL |
| migration.key_fingerprint | string | cond | 40-char hex fingerprint |
| migration.upgrade_command | string | cond | Command template with `{package}` placeholder |

**Storage**: `.specific/{tool.name}.yaml`

**Validation**: apiVersion must match; required fields non-empty; migration fields required when `migration.enabled: true`.

---

### ProviderConfig

Represents a registered discovery provider for fleet inventory.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| apiVersion | string | yes | Schema version: `fleet-upgrade-provider/v1` |
| provider.name | string | yes | Unique identifier (e.g., `doctl`, `vultr`, `manual`) |
| provider.cli_binary | string | yes | Executable name (e.g., `doctl`, `vultr-cli`) |
| provider.auth_check | string | yes | Command to verify authentication |
| provider.discover_command | string | yes | Command template returning VM list as JSON |
| provider.output_format | string | yes | Output parser: `json`, `csv`, `text` |
| provider.ip_field | string | cond | JSON path to IP address (for json format) |
| provider.name_field | string | cond | JSON path to VM name (for json format) |

**Storage**: `.specific/{provider.name}.yaml`

**Validation**: cli_binary must be non-empty; discover_command must produce parseable output.

---

### FleetInventory

Captured VM inventory from a discovery run.

| Field | Type | Description |
|-------|------|-------------|
| captured_at | string (ISO 8601) | Timestamp of discovery |
| source | string | Provider name used |
| entries | list[VMEntry] | List of VMs |
| added | list[string] | IPs added since last discovery |
| removed | list[string] | IPs removed since last discovery |

---

### VMEntry

Single VM in the inventory.

| Field | Type | Description |
|-------|------|-------------|
| name | string | VM hostname/label |
| ip | string | IPv4 address |
| status | string | `active`, `inactive`, `unknown` |
| first_seen | string (ISO 8601) | First discovery timestamp |
| last_seen | string (ISO 8601) | Most recent discovery |

---

### VMRecord

Per-VM per-tool execution record.

| Field | Type | Description |
|-------|------|-------------|
| ip | string | VM IP address |
| tool | string | Tool name this record applies to |
| survey | SurveyResult | Audit findings |
| execution | ExecutionResult | Upgrade outcome |
| rollback | RollbackResult | Rollback outcome (if attempted) |
| timestamps | object | Key event timestamps |

---

### SurveyResult

Read-only audit findings for a VM+tool.

| Field | Type | Description |
|-------|------|-------------|
| verdict | string | `SKIP`, `UP-TO-DATE`, `UPGRADE`, `BLOCKED(reason)`, `UNREACHABLE(reason)` |
| installed_version | string | Current version (or null) |
| candidate_version | string | Available upgrade version (or null) |
| precheck_ok | bool | Whether precheck command passed |
| config_test_ok | bool | Whether config test passed |
| origin_ok | bool | Whether package origin is allowed |
| hold_detected | bool | Whether package hold is active |
| drift_files | list[string] | Drift file paths detected |
| evidence | string | Raw command output |

---

### ExecutionResult

Upgrade execution outcome.

| Field | Type | Description |
|-------|------|-------------|
| state | string | `PENDING`, `BACKING_UP`, `UPGRADING`, `VERIFYING`, `SUCCEEDED`, `FAILED` |
| old_version | string | Version before upgrade |
| new_version | string | Version after upgrade (or null if failed) |
| attempts | int | Number of execution attempts (max 2 with retry) |
| backup_path | string | Local path to verified backup archive |
| backup_checksum | string | SHA-256 of backup archive |
| error | string | Error message if failed |

---

### RollbackResult

Rollback outcome.

| Field | Type | Description |
|-------|------|-------------|
| state | string | `SUCCEEDED`, `FAILED`, `REFUSED` |
| config_ok | bool | Whether config was restored |
| package_ok | bool | Whether package version was restored |
| service_active | bool | Whether service is running after rollback |
| error | string | Error message if failed |

---

### RunState

Top-level execution state (source of truth).

| Field | Type | Description |
|-------|------|-------------|
| run_id | string | Unique run identifier (UUID) |
| started_at | string (ISO 8601) | Run start timestamp |
| tool | string | Tool being upgraded |
| provider | string | Provider used for discovery |
| inventory | FleetInventory | Captured inventory |
| records | dict[str, VMRecord] | Per-IP per-tool records (key: `{ip}:{tool}`) |
| gates | list[GateDecision] | Approval decisions |
| report | object | Report metadata |

**Storage**: `.fleet/state.json`

---

### GateDecision

Operator approval record.

| Field | Type | Description |
|-------|------|-------------|
| decision | string | `proceed`, `stop` |
| decided_at | string (ISO 8601) | Timestamp |
| decided_by | string | Operator identifier (or `unknown`) |
| note | string | Optional comment |
| phase | string | `summary` or `canary` |

---

## Relationships

```
ToolConfig 1──* VMRecord
ProviderConfig 1──* FleetInventory
FleetInventory 1──* VMEntry
RunState 1──* VMRecord
RunState 1──* GateDecision
VMRecord 1──1 SurveyResult
VMRecord 1──1 ExecutionResult
VMRecord 1──0..1 RollbackResult
```

## State Transitions

### VMRecord.execution.state

```
PENDING → BACKING_UP → UPGRADING → VERIFYING → SUCCEEDED
                                            ↘ FAILED
         BACKING_UP → FAILED (backup failure)
         UPGRADING → FAILED (upgrade failure, after retry)
         VERIFYING → FAILED (verification failure)
```

### VMRecord.execution.state (after rollback)

```
FAILED → ROLLED_BACK (rollback succeeded)
FAILED → FAILED (rollback failed)
```

### Verdict

```
(survey) → SKIP | UP-TO-DATE | UPGRADE | BLOCKED | UNREACHABLE
```

## Validation Rules

- ToolConfig.tool.name must be unique across `.specific/*.yaml` files.
- ProviderConfig.provider.name must be unique across `.specific/*.yaml` files.
- VMEntry.ip must be a valid IPv4 address.
- VMRecord.execution.backup_checksum must match the actual backup file's SHA-256 before rollback.
- GateDecision.phase must be `summary` before `canary` (ordering constraint).
- RunState.records key format: `{ip}:{tool}` to support multiple tools per VM.
