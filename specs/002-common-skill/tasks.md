---
description: "Task list for Common Fleet Upgrade Skill implementation"
---

# Tasks: Common Fleet Upgrade Skill

**Input**: Design documents from `/specs/002-common-skill/`

**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/

**Tests**: Test tasks are included per user story to verify the existing project verification skills pass.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4)
- Include exact file paths in descriptions

## Path Conventions

All source code lives under `.agents/skills/fleet-upgrade/` (the new common skill).
Tests live under `.agents/skills/fleet-upgrade/scripts/tests/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the new skill directory structure and initialize the Python project.

- [x] T001 Create skill directory structure: `.agents/skills/fleet-upgrade/scripts/fleetkit/`, `.agents/skills/fleet-upgrade/scripts/fleetkit/providers/`, `.agents/skills/fleet-upgrade/scripts/fleetkit/tools/`, `.agents/skills/fleet-upgrade/references/`
- [x] T002 [P] Create `.agents/skills/fleet-upgrade/scripts/fleetkit/__init__.py` with package docstring
- [x] T003 [P] Create `.agents/skills/fleet-upgrade/scripts/fleetkit/providers/__init__.py` with provider registry loader stub
- [x] T004 [P] Create `.agents/skills/fleet-upgrade/scripts/fleetkit/tools/__init__.py` with tool registry loader stub
- [x] T005 Create `.agents/skills/fleet-upgrade/SKILL.md` based on existing nginx-fleet-upgrade SKILL.md, updated for common skill (tool-agnostic commands, provider selection)
- [x] T006 [P] Create test directory structure: `.agents/skills/fleet-upgrade/scripts/tests/`, `.agents/skills/fleet-upgrade/scripts/tests/unit/`, `.agents/skills/fleet-upgrade/scripts/tests/contract/`, `.agents/skills/fleet-upgrade/scripts/tests/integration/`, `.agents/skills/fleet-upgrade/scripts/tests/fixtures/`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before any user story can be implemented. This includes config loading, SSH client, state management, and base interfaces.

**CRITICAL**: No user story work can begin until this phase is complete.

- [x] T007 Implement `Config` class in `.agents/skills/fleet-upgrade/scripts/fleetkit/config.py` — extends existing nginx config pattern to support loading both `.specific/{tool}.yaml` (apiVersion `fleet-upgrade-tool/v1`) and `.specific/{provider}.yaml` (apiVersion `fleet-upgrade-provider/v1`). Must include `_check_unknown` validation, `_deep_merge` with defaults, dotted-path `get()` and `resolve()`. Required fields for tool: `tool.name` (non-empty, unique), `tool.package` (non-empty), `tool.service` (non-empty), `tool.config_paths` (non-empty list), `tool.version_query` (non-empty), `tool.precheck` (non-empty). Required fields for provider: `provider.name` (non-empty), `provider.cli_binary` (non-empty), `provider.auth_check` (non-empty), `provider.discover_command` (non-empty), `provider.output_format` (one of `json`, `csv`, `text`).
- [x] T008 [P] Implement `SSHClient` in `.agents/skills/fleet-upgrade/scripts/fleetkit/ssh.py` — reuse pattern from existing nginx skill. Must support connection multiplexing (`ControlPersist 300s`), configurable timeout (`ssh.connect_timeout` 1-60), command timeout (`ssh.command_timeout` 5-3600), privilege escalation (`auto`, `sudo`, `root`), and strict host key checking (`accept-new`, `yes`). Load credentials from `.personal/ssh.env` (mode 0600).
- [x] T009 [P] Implement `StateStore` in `.agents/skills/fleet-upgrade/scripts/fleetkit/state.py` — manages `.fleet/state.json`. Must support `load()`, `save()`, `set_record()`, `record_for_ip()`, `canary_records()`, `add_gate()`. Record keys use format `{ip}:{tool}` to support multiple tools per VM. State includes `run_id`, `started_at`, `tool`, `provider`, `inventory`, `records`, `gates`, `report`.
- [x] T010 [P] Implement `ProviderBase` abstract class in `.agents/skills/fleet-upgrade/scripts/fleetkit/providers/base.py` — three abstract methods: `validate() -> bool` (check CLI installed and authenticated), `discover() -> list[dict[str, str]]` (return VM entries with `name`, `ip`, `status`), `reconcile(previous, current) -> tuple[list[str], list[str]]` (compute added/removed IPs).
- [x] T011 Implement `load_ssh_env()` in `.agents/skills/fleet-upgrade/scripts/fleetkit/config.py` — reads `.personal/ssh.env` for `SSH_USER`, `SSH_KEY`, `SSH_PORT`. Validates port is integer 1-65535. Resolves relative key paths. Warns if file mode is not 0600.
- [x] T012 Implement backup utilities in `.agents/skills/fleet-upgrade/scripts/fleetkit/backup.py` — `create_backup(ssh, config_paths, tool_name, ip, backups_dir) -> dict` creates tar archive of remote config paths, downloads to `backups/{ip}/{tool}-{timestamp}.tar.gz`, computes SHA-256 checksum. `verify_backup(backup_path, expected_checksum) -> bool` verifies local file matches remote checksum.
- [x] T013 Implement `write_record()` in `.agents/skills/fleet-upgrade/scripts/fleetkit/records.py` — renders per-VM per-tool record to `plan/{ip}.md` using record template. Includes survey verdict, execution state, rollback state, timestamps.

**Checkpoint**: Foundation ready — config loading, SSH, state, provider interface, backup, and records are complete. User story implementation can now begin.

---

## Phase 3: User Story 1 — Register a New Tool (Priority: P1) MVP

**Goal**: Operators can register a new software tool (e.g., Docker) via `.specific/{tool}.yaml` and the system can audit/survey fleet VMs for that tool.

**Independent Test**: Register Docker as a tool, run `survey --tool docker --all`, verify every VM gets a verdict.

**Verification skill**: `verify-audit` — `python3 -m unittest discover -s .agents/skills/fleet-upgrade/scripts/tests -t .agents/skills/fleet-upgrade/scripts -k verdict -k survey -k inventory -k audit_flow`

### Implementation for User Story 1

- [x] T014 [US1] Implement tool config schema and validation in `.agents/skills/fleet-upgrade/scripts/fleetkit/tools/registry.py` — `load_tool_config(root, tool_name) -> dict` loads `.specific/{tool_name}.yaml`, validates apiVersion is `fleet-upgrade-tool/v1`, validates required fields (`tool.name` non-empty unique, `tool.package` non-empty, `tool.service` non-empty, `tool.config_paths` non-empty list, `tool.version_query` non-empty, `tool.precheck` non-empty). Validates optional `migration` section: when `migration.enabled` is true, requires `migration.repo_url`, `migration.repo_dist`, `migration.key_url`, `migration.key_fingerprint` (40 hex chars), `migration.keyring_path`, `migration.sources_path`, `migration.apply_to_dists` (non-empty list), `migration.pin_priority` (1-1000), `migration.upgrade_command` (contains `{package}`).
- [x] T015 [P] Implement `list_tools(root) -> list[str]` in `.agents/skills/fleet-upgrade/scripts/fleetkit/tools/registry.py` — scans `.specific/*.yaml` for files with apiVersion `fleet-upgrade-tool/v1`, returns tool names.
- [x] T016 [US1] Implement `verdict.py` in `.agents/skills/fleet-upgrade/scripts/fleetkit/verdict.py` — parameterized by tool config. `compute_verdict(tool_config, ssh_result) -> str` returns one of: `SKIP` (tool not installed), `UP-TO-DATE` (installed version matches candidate), `UPGRADE` (newer version available), `BLOCKED(reason)` (precheck failed, package held, unexpected origin, third-party module), `UNREACHABLE(reason)` (SSH failed after retry). Uses tool's `version_query`, `precheck`, `allowed_origin_patterns`, `hold_patterns`.
- [x] T017 [US1] Implement `survey.py` in `.agents/skills/fleet-upgrade/scripts/fleetkit/survey.py` — `survey_entries(client, entries, config, tool_config, concurrency, records) -> dict` runs read-only audit per VM. For each VM: runs `tool.version_query`, checks for candidate upgrade, runs `tool.precheck`, checks origin patterns, checks hold patterns, scans for drift files. Returns dict of `{ip: VMRecord}` with survey results. Reuses existing survey pattern from nginx skill but parameterized by tool config.
- [x] T018 [P] [US1] Implement `render_summary(records) -> str` and `summary_data(records) -> dict` in `.agents/skills/fleet-upgrade/scripts/fleetkit/survey.py` — groups records by verdict, lists eligible VMs for upgrade.
- [x] T019 [US1] Implement `config --init --type tool --name NAME` command in `.agents/skills/fleet-upgrade/scripts/fleetkit/cli.py` — creates `.specific/{name}.yaml` from template at `.agents/skills/fleet-upgrade/references/tool-config.template.yaml`. Refuses to overwrite without `--force`.
- [x] T020 [P] [US1] Create tool config template at `.agents/skills/fleet-upgrade/references/tool-config.template.yaml` — contains all fields from the tool-registry contract with sensible defaults and comments explaining each field.
- [x] T021 [US1] Wire `survey` command in `.agents/skills/fleet-upgrade/scripts/fleetkit/cli.py` to accept `--tool NAME` parameter, load tool config via `load_tool_config()`, and pass to `survey_entries()`. Add `--list-tools` flag to list registered tools.
- [x] T022 [US1] Wire `summary` command in `.agents/skills/fleet-upgrade/scripts/fleetkit/cli.py` to accept `--tool NAME` filter.
- [x] T023 [P] [US1] Create test fixtures: `.agents/skills/fleet-upgrade/scripts/tests/fixtures/` — mock tool configs, mock SSH responses for version_query and precheck.
- [x] T024 [US1] Write unit tests in `.agents/skills/fleet-upgrade/scripts/tests/unit/test_tool_registry.py` — test tool config loading, validation (required fields, migration conditional fields, unknown keys), list_tools scanning.
- [x] T025 [US1] Write unit tests in `.agents/skills/fleet-upgrade/scripts/tests/unit/test_verdict.py` — test verdict computation for each case: SKIP, UP-TO-DATE, UPGRADE, BLOCKED (each reason), UNREACHABLE.
- [x] T026 [US1] Write unit tests in `.agents/skills/fleet-upgrade/scripts/tests/unit/test_survey.py` — test survey_entries with mock SSH client, mock tool config, verifies verdict assignment and evidence collection.

**Verification**:
- [x] T027 [US1] Verify tool registration and audit via skill `verify-audit`: `python3 -m unittest discover -s .agents/skills/fleet-upgrade/scripts/tests -t .agents/skills/fleet-upgrade/scripts -k verdict -k survey -k inventory -k audit_flow` — all tests pass, confirming tool config loading, verdict logic, and survey flow work correctly.

**Checkpoint**: A new tool can be registered via `.specific/{tool}.yaml` and the audit/survey flow produces correct verdicts for every VM.

---

## Phase 4: User Story 2 — Choose a Provider (Priority: P1)

**Goal**: Operators can select a discovery provider (doctl, vultr-cli, manual) and the system discovers VMs accordingly. Providers are registered via `.specific/{provider}.yaml`.

**Independent Test**: Register vultr as a provider, run `discover --provider vultr`, verify VMs are fetched and inventory updated.

**Verification skill**: `verify-audit` — `python3 -m unittest discover -s .agents/skills/fleet-upgrade/scripts/tests -t .agents/skills/fleet-upgrade/scripts -k verdict -k survey -k inventory -k audit_flow`

**Dependencies**: Phase 2 (foundational), Phase 3 (US1 — tool config pattern informs provider config pattern).

### Implementation for User Story 2

- [x] T028 [P] [US2] Implement `DoctlProvider` in `.agents/skills/fleet-upgrade/scripts/fleetkit/providers/doctl.py` — extends `ProviderBase`. `validate()` runs `doctl auth list` and checks exit code 0. `discover()` runs `doctl compute droplet list --output json`, parses JSON array, extracts `name` and `networks.v4[?type=='public'].ip_address` for active droplets. `reconcile()` computes added/removed IPs against previous inventory.
- [x] T029 [P] [US2] Implement `VultrProvider` in `.agents/skills/fleet-upgrade/scripts/fleetkit/providers/vultr.py` — extends `ProviderBase`. `validate()` runs `vultr-cli account` and checks exit code 0. `discover()` runs `vultr-cli instances --json`, parses JSON, extracts `label` as name and `main_ip` as IP. `reconcile()` same pattern as doctl.
- [x] T030 [P] [US2] Implement `ManualProvider` in `.agents/skills/fleet-upgrade/scripts/fleetkit/providers/manual.py` — extends `ProviderBase`. `validate()` checks inventory file exists. `discover()` reads CSV file (`Name,IP` per line), validates IPv4 addresses, deduplicates. `reconcile()` same pattern.
- [x] T031 [US2] Implement provider registry loader in `.agents/skills/fleet-upgrade/scripts/fleetkit/providers/__init__.py` — `load_provider(root, provider_name) -> ProviderBase` loads `.specific/{provider_name}.yaml`, validates apiVersion is `fleet-upgrade-provider/v1`, validates required fields (`provider.name` non-empty, `provider.cli_binary` non-empty, `provider.auth_check` non-empty, `provider.discover_command` non-empty, `provider.output_format` one of `json`/`csv`/`text`), instantiates the correct provider class. `list_providers(root) -> list[str]` scans `.specific/*.yaml` for provider configs.
- [x] T032 [US2] Implement `inventory.py` in `.agents/skills/fleet-upgrade/scripts/fleetkit/inventory.py` — provider-agnostic reconciliation and IP file I/O. `validate_ip(ip) -> str` validates IPv4. `parse_ip_file(text) -> list[dict]` parses CSV. `write_ip_file(path, entries)` writes sorted CSV. `reconcile(state_data, entries, source) -> tuple[list[str], list[str]]` computes added/removed, updates state inventory.
- [x] T033 [US2] Implement `config --init --type provider --name NAME` command in `.agents/skills/fleet-upgrade/scripts/fleetkit/cli.py` — creates `.specific/{name}.yaml` from template. Refuses to overwrite without `--force`.
- [x] T034 [P] [US2] Create provider config template at `.agents/skills/fleet-upgrade/references/provider-config.template.yaml` — contains all fields from the provider-interface contract with defaults and comments.
- [x] T035 [US2] Wire `discover` command in `.agents/skills/fleet-upgrade/scripts/fleetkit/cli.py` to accept `--provider NAME` parameter, load provider via `load_provider()`, call `provider.validate()` then `provider.discover()`, reconcile against previous inventory, write `ip.txt`.
- [x] T036 [US2] Wire `doctor` command in `.agents/skills/fleet-upgrade/scripts/fleetkit/cli.py` to check the active provider's CLI binary availability and auth status.
- [x] T037 [P] [US2] Create test fixtures: `.agents/skills/fleet-upgrade/scripts/tests/fixtures/bin/doctl`, `.agents/skills/fleet-upgrade/scripts/tests/fixtures/bin/vultr-cli` — mock CLI scripts returning canned JSON.
- [x] T038 [US2] Write unit tests in `.agents/skills/fleet-upgrade/scripts/tests/unit/test_inventory.py` — test IP validation, file parsing, reconciliation (added/removed), write_ip_file.
- [x] T039 [US2] Write unit tests in `.agents/skills/fleet-upgrade/scripts/tests/test_provider_doctl.py` — test doctl JSON parsing, auth check, discovery with mock runner.
- [x] T040 [US2] Write unit tests in `.agents/skills/fleet-upgrade/scripts/tests/test_provider_manual.py` — test manual file parsing, validation, edge cases (empty lines, comments, duplicates).

**Verification**:
- [x] T041 [US2] Verify provider discovery via skill `verify-audit`: `python3 -m unittest discover -s .agents/skills/fleet-upgrade/scripts/tests -t .agents/skills/fleet-upgrade/scripts -k inventory` — all inventory and provider tests pass, confirming provider registration, discovery, and reconciliation work correctly.

**Checkpoint**: A new provider can be registered via `.specific/{provider}.yaml` and the discover flow fetches VMs and updates inventory.

---

## Phase 5: User Story 3 — Gated, Canaried Upgrade Rollout with Rollback (Priority: P2)

**Goal**: Operators can execute the full canary-then-fleet rollout with safety guarantees: verified backups, explicit approval gates, serial execution, retry-once, and full rollback (package + config).

**Independent Test**: Execute a canary upgrade, record gate decision, execute fleet rollout, verify serial execution and rollback on failure.

**Verification skills**:
- `verify-rollout` — `python3 -m unittest discover -s .agents/skills/fleet-upgrade/scripts/tests -t .agents/skills/fleet-upgrade/scripts -k execute -k rollout`
- `verify-rollback` — `python3 -m unittest discover -s .agents/skills/fleet-upgrade/scripts/tests -t .agents/skills/fleet-upgrade/scripts -k rollback`

**Dependencies**: Phase 3 (US1 — tool config for upgrade commands), Phase 4 (US2 — provider for inventory).

### Implementation for User Story 3

- [x] T042 [US3] Implement `execute.py` in `.agents/skills/fleet-upgrade/scripts/fleetkit/execute.py` — `validate_approvals(store, config, approved_ips, tool_config)` checks all approved IPs have UPGRADE verdict, refuses non-UPGRADE IPs (exit 3). `execute_canary(store, client, config, tool_config, approved_ips)` runs backup → verify backup → upgrade → verify post-upgrade for single VM. `execute_fleet(store, client, config, tool_config, approved_ips)` runs same flow serially (one VM at a time) with one retry round on failure. Uses tool's `upgrade_command` (or default `apt-get install --only-upgrade {package}` with `--force-confdef --force-confold`).
- [x] T043 [US3] Implement post-upgrade verification in `.agents/skills/fleet-upgrade/scripts/fleetkit/execute.py` — after upgrade, runs `tool.precheck` and `tool.version_query` to confirm new version. If `tool.verify` is configured, runs HTTP/HTTPS checks. Records `new_version`, `state` (SUCCEEDED/FAILED).
- [x] T044 [US3] Implement retry logic in `.agents/skills/fleet-upgrade/scripts/fleetkit/execute.py` — on failure, one automatic retry round. If still fails, mark FAILED and continue to next VM. Save state after each VM completes.
- [x] T045 [US3] Implement `gate` command in `.agents/skills/fleet-upgrade/scripts/fleetkit/cli.py` — `gate --decision proceed|stop [--note TEXT]` records canary decision in state. Refuses if canary has not reached terminal state (SUCCEEDED or FAILED).
- [x] T046 [US3] Implement `rollback.py` in `.agents/skills/fleet-upgrade/scripts/fleetkit/rollback.py` — `rollback_vm(client, config, tool_config, record) -> dict` performs FULL rollback: (1) restore config from verified backup archive (tar extract to `tool.config_paths`), (2) reinstall old package version (`apt-get install {package}={old_version}`), (3) run `tool.precheck` to verify, (4) restart `tool.service`. Returns `{state, config_ok, package_ok, service_active, error}`. Refuses if no verified backup exists or checksum mismatch.
- [x] T047 [US3] Implement `dry_run_plan()` in `.agents/skills/fleet-upgrade/scripts/fleetkit/rollback.py` — shows what rollback would do without executing.
- [x] T048 [US3] Wire `execute` command in `.agents/skills/fleet-upgrade/scripts/fleetkit/cli.py` — accepts `--tool NAME`, `--phase canary|fleet`, `--approve IP[,IP]`, `--yes`, `--dry-run`. Loads tool config, validates approvals, dispatches to `execute_canary` or `execute_fleet`. Fleet execution is serial (one VM at a time).
- [x] T049 [US3] Wire `rollback` command in `.agents/skills/fleet-upgrade/scripts/fleetkit/cli.py` — accepts `--tool NAME`, `--ip IP`, `--yes`, `--dry-run`. Loads tool config, dispatches to `rollback_vm`.
- [x] T050 [US3] Implement migration mode in `.agents/skills/fleet-upgrade/scripts/fleetkit/migration.py` — optional per tool. When `tool.migration.enabled` is true and `--mode migrate` is specified: bootstrap upstream repo (signing key verified against `migration.key_fingerprint`, sources.list.d entry, apt pinning), then upgrade from upstream repo. Refuses if tool has no migration config.
- [x] T051 [P] [US3] Write unit tests in `.agents/skills/fleet-upgrade/scripts/tests/unit/test_execute.py` — test validate_approvals (non-UPGRADE IP refused), canary flow (backup → upgrade → verify), fleet serial execution, retry-once, state persistence.
- [x] T052 [P] [US3] Write unit tests in `.agents/skills/fleet-upgrade/scripts/tests/unit/test_rollout_flow.py` — test end-to-end canary → gate → fleet flow, gate decision recording, fleet without canary proceed refused.
- [x] T053 [P] [US3] Write unit tests in `.agents/skills/fleet-upgrade/scripts/tests/unit/test_rollback.py` — test full rollback (package + config), rollback refused (no backup, checksum mismatch), dry run plan, rollback precheck failure.
- [x] T054 [US3] Write unit tests in `.agents/skills/fleet-upgrade/scripts/tests/unit/test_migrate.py` — test migration mode bootstrap, key fingerprint verification, refused for non-migratable VMs.

**Verification**:
- [x] T055 [US3] Verify rollout and rollback via skills `verify-rollout` and `verify-rollback`:
  - `python3 -m unittest discover -s .agents/skills/fleet-upgrade/scripts/tests -t .agents/skills/fleet-upgrade/scripts -k execute -k rollout` — all execute/rollout tests pass.
  - `python3 -m unittest discover -s .agents/skills/fleet-upgrade/scripts/tests -t .agents/skills/fleet-upgrade/scripts -k rollback` — all rollback tests pass, confirming full rollback (package + config) works correctly.

**Checkpoint**: The full gated rollout flow works: audit → summary gate → canary → canary gate → serial fleet → rollback on failure. Full rollback restores both package version and configuration.

---

## Phase 6: User Story 4 — Organized Output: Configs, Secrets, Reports (Priority: P3)

**Goal**: All persistent artifacts stored in appropriate locations: configs in `.specific/{tool}.yaml`, secrets in `.personal/`, reports in `wiki/`. Clean, machine-parseable, no sensitive data in version control.

**Independent Test**: Complete an upgrade run, verify report in `wiki/`, LOGS.md updated, no secrets in version control.

**Verification skill**: `verify-report` — `python3 -m unittest discover -s .agents/skills/fleet-upgrade/scripts/tests -t .agents/skills/fleet-upgrade/scripts -k report`

**Dependencies**: Phase 5 (US3 — needs execution data for reports).

### Implementation for User Story 4

- [x] T056 [US4] Implement `report.py` in `.agents/skills/fleet-upgrade/scripts/fleetkit/report.py` — `render_report(records) -> str` generates human-readable markdown report with per-VM before/after versions, outcome, backup location. `report_rows(records) -> list[dict]` returns structured data. `log_summary(records, run_id) -> tuple[str, str]` generates title and summary for LOGS.md. `append_log(log_path, title, summary)` appends to LOGS.md (append-only, no duplicates).
- [x] T057 [US4] Implement wiki report output in `.agents/skills/fleet-upgrade/scripts/fleetkit/report.py` — `write_wiki_report(records, tool_name, run_id, wiki_dir)` writes report to `wiki/fleet-reports/{YYYY-MM-DD}-{tool}.md`. Includes run metadata, per-VM table, summary.
- [x] T058 [US4] Wire `report` command in `.agents/skills/fleet-upgrade/scripts/fleetkit/cli.py` — accepts `--tool NAME`, `--log`. Generates report, optionally writes to wiki and appends to LOGS.md. Warns if LOGS.md entry already recorded.
- [x] T059 [US4] Implement `.gitignore` enforcement in `.agents/skills/fleet-upgrade/scripts/fleetkit/config.py` — verify that `.personal/`, `ip.txt`, `plan/`, `backups/`, `.fleet/` are excluded from version control. `doctor` command warns if sensitive files are tracked.
- [x] T060 [P] [US4] Write unit tests in `.agents/skills/fleet-upgrade/scripts/tests/unit/test_report.py` — test render_report output format, report_rows structure, log_summary generation, append_log (no duplicates), wiki report file naming.
- [x] T061 [P] [US4] Write unit tests in `.agents/skills/fleet-upgrade/scripts/tests/unit/test_records.py` — test write_record output, per-VM plan file rendering.

**Verification**:
- [x] T062 [US4] Verify report generation via skill `verify-report`: `python3 -m unittest discover -s .agents/skills/fleet-upgrade/scripts/tests -t .agents/skills/fleet-upgrade/scripts -k report` — all report tests pass, confirming report rendering, wiki output, and LOGS.md append work correctly.

**Checkpoint**: Reports are generated in `wiki/fleet-reports/`, LOGS.md is updated, configs are in `.specific/`, secrets are in `.personal/` with mode 0600.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Backward compatibility, documentation, and final validation.

- [x] T063 Ensure backward compatibility with existing `nginx-fleet-upgrade` skill — the new skill reads `.specific/nginx-fleet.yaml` (existing config) and treats nginx as a registered tool. The `tool` section maps to tool config, `migration` section maps to migration config. Existing `fleet`, `paths`, `ssh`, `execution`, `logging` sections are handled by global config defaults.
- [x] T064 [P] Create `.agents/skills/fleet-upgrade/references/record-template.md` — per-VM record template showing survey verdict, execution state, rollback state, timestamps, evidence.
- [x] T065 [P] Create `.agents/skills/fleet-upgrade/scripts/tests/fixtures/bin/ssh` and `.agents/skills/fleet-upgrade/scripts/tests/fixtures/bin/scp` — mock SSH/SCP scripts for testing without real VMs.
- [ ] T066 Write integration test in `.agents/skills/fleet-upgrade/scripts/tests/integration/test_e2e_flow.py` — end-to-end flow: config --init → doctor → discover → survey → summary → execute canary → gate → execute fleet → report. Uses mock SSH and mock provider. Verifies serial execution, full rollback, report generation.
- [ ] T067 Write contract test in `.agents/skills/fleet-upgrade/scripts/tests/contract/test_provider_interface.py` — verify all provider implementations (doctl, vultr, manual) conform to `ProviderBase` interface: `validate()`, `discover()`, `reconcile()` methods exist and return correct types.
- [ ] T068 Write contract test in `.agents/skills/fleet-upgrade/scripts/tests/contract/test_tool_registry.py` — verify tool config loading, validation, list_tools scanning.
- [x] T069 [P] Update `.specific/project.yaml` verification skills to point to new test paths under `.agents/skills/fleet-upgrade/scripts/tests/`.
- [ ] T070 Run quickstart.md validation scenarios end-to-end with mock infrastructure to verify all 5 scenarios pass.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all user stories
- **US1 - Register Tool (Phase 3)**: Depends on Foundational — no dependency on other stories
- **US2 - Choose Provider (Phase 4)**: Depends on Foundational + US1 (provider config pattern follows tool config pattern)
- **US3 - Gated Rollout (Phase 5)**: Depends on US1 (tool config for upgrades) + US2 (provider for inventory)
- **US4 - Organized Output (Phase 6)**: Depends on US3 (needs execution data for reports)
- **Polish (Phase 7)**: Depends on all user stories being complete

### User Story Dependencies

```
Phase 1 (Setup) → Phase 2 (Foundational) → Phase 3 (US1: Register Tool)
                                              ↓
                                         Phase 4 (US2: Choose Provider)
                                              ↓
                                         Phase 5 (US3: Gated Rollout)
                                              ↓
                                         Phase 6 (US4: Organized Output)
                                              ↓
                                         Phase 7 (Polish)
```

### Within Each User Story

- Config/schema before loader before CLI wiring
- Core implementation before tests
- Implementation before verification

### Parallel Opportunities

- Phase 1: T002, T003, T004, T006 can run in parallel
- Phase 2: T008, T009, T010 can run in parallel (different files)
- Phase 3 (US1): T015, T018, T020, T023 can run in parallel
- Phase 4 (US2): T028, T029, T030, T034, T037 can run in parallel
- Phase 5 (US3): T051, T052, T053 can run in parallel
- Phase 6 (US4): T060, T061 can run in parallel
- Phase 7: T064, T065, T069 can run in parallel

---

## Parallel Example: User Story 1

```bash
# Launch parallel tasks for US1:
Task T015: "Implement list_tools() in tools/registry.py"
Task T018: "Implement render_summary() and summary_data() in survey.py"
Task T020: "Create tool-config.template.yaml in references/"
Task T023: "Create test fixtures in tests/fixtures/"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational
3. Complete Phase 3: User Story 1 (Register Tool)
4. **STOP and VALIDATE**: Run `verify-audit` skill — tool registration and survey work
5. Deploy/demo if ready

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. US1 (Register Tool) → Verify audit works → MVP!
3. US2 (Choose Provider) → Verify discovery works
4. US3 (Gated Rollout) → Verify full upgrade cycle with rollback
5. US4 (Organized Output) → Verify reports and wiki output
6. Each story adds value without breaking previous stories

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks in same phase
- [Story] label maps task to specific user story for traceability
- Each user story is independently completable and testable
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- All tasks use absolute paths under `.agents/skills/fleet-upgrade/`
- Existing nginx-fleet-upgrade skill remains untouched during development
