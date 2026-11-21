# Feature Specification: Common Fleet Upgrade Skill

**Feature Branch**: `002-common-skill`

**Created**: 2026-11-21

**Status**: Draft

**Input**: User description: "migrate nginx-fleet-upgrade to common skill — (1) can choose provider (doctl, vultr-cli, manual, ...) support register more; (2) can register new software want to upgrade: nginx, docker, ... ; for specific config keep at .specific/xxx (expect inside yaml if possible); report, docs -> wiki; for special information (secret, personal, ...) -> .personal; IMPORTANT: FLOW should safe for can rollback"

## Clarifications

### Session 2026-11-21

- Q: What is the expected maximum fleet size (number of VMs) this skill must handle in a single upgrade run? → A: Medium fleet: 10-100 VMs
- Q: How should provider plugins be discovered and registered by the system? → A: Provider plugins are registered via `.specific/{provider}.yaml` files, following the same pattern as tool registrations
- Q: When a tool's upgrade fails on a VM and rollback is triggered, what should happen to the package version? → A: Full rollback: restore both package version and configuration from backup (VM returns to exact pre-upgrade state)
- Q: During fleet rollout (after canary approval), how many VMs should be upgraded concurrently? → A: Serial: one VM at a time (safest, slowest)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Register a new tool to manage fleet upgrades (Priority: P1)

The operator wants to add support for upgrading a new software package (e.g., Docker, Python, a custom binary) across the fleet without rewriting the entire flow. They register the tool by providing its name, the package/service identifiers, default verification commands, a configuration template, and optionally a migration mode bootstrap script. Once registered, the tool appears alongside nginx in the list of manageable services, and all the standard audit → gate → rollout → rollback workflow becomes available for it automatically.

- **Why this priority**: This is the core abstraction — without it, every new tool requires a new skill from scratch. Registering a tool unlocks the entire verified upgrade pipeline for it immediately.

**Acceptance Scenarios**:
1. **Given** an existing fleet with inventory already discovered, **When** the operator registers a new tool (e.g., `docker`) with its playbook definition, **Then** a config file `.specific/docker.yaml` is created, the tool appears in the registry, and the operator can run the audit phase for Docker upgrades.
2. **Given** a registered tool, **When** the operator runs the audit, **Then** every reachable VM receives a verdict for that tool's package using the defined verification and version-query commands.
3. **Given** a tool that has no migration mode, **When** the operator tries to invoke migrate mode, **Then** the command fails with a clear message indicating migration is not available for this tool.

---

### User Story 2 - Choose a provider for fleet inventory discovery (Priority: P1)

The operator has a mixed fleet or wants to switch cloud providers. Instead of being locked into DigitalOcean + `doctl`, they select a discovery provider (`doctl`, `vultr-cli`, or `manual`) and the system discovers VMs accordingly. Providers are registered as pluggable modules so new ones can be added later. Inventory reconciliation works identically regardless of provider.

- **Why this priority**: Lock-in to one provider prevents adoption in multi-cloud scenarios. Provider choice is foundational — everything downstream uses the inventory.

**Acceptance Scenarios**:
1. **Given** an operator who selects `manual` as the provider, **When** they run discover, **Then** the system reads the inventory from the configured file without making any API calls.
2. **Given** a supported provider (e.g., `doctl`), **When** the operator runs discover, **Then** VMs are fetched via that provider's API and reconciled against previous inventory, showing added and removed entries.
3. **Given** a newly registered provider plugin, **When** the operator selects it as the active provider, **Then** the system validates the plugin is properly installed and discovers VMs using its interface.

---

### User Story 3 - Gated, canaried upgrade rollout with rollback (Priority: P2)

The operator reviews audit results for any registered tool, selects which VMs to upgrade, and executes the full canary-then-fleet rollout with the same safety guarantees as the original nginx skill: verified backups before changes, explicit approval gates, serial execution, retry-once on failure, and full rollback (package + configuration). The flow must work generically for any registered tool.

- **Why this priority**: This delivers the actual operational value — safe, auditable, reversible upgrades — applied generically to whatever tools are registered.

**Acceptance Scenarios**:
1. **Given** audit records exist for a registered tool, **When** the operator approves an upgrade set, **Then** execution proceeds: backup → verify backup → upgrade → verify post-upgrade, pausing after the canary for operator review.
2. **Given** a VM that fails during upgrade, **When** the operator initiates rollback, **Then** the VM's package version and configuration are both restored from the verified backup, the service passes its precheck command, and the record shows `ROLLED_BACK`.
3. **Given** multiple tools registered, **When** the operator runs an upgrade for one tool, **Then** only that tool's packages and configurations are affected — other tools remain untouched.

---

### User Story 4 - Organized output: configs, secrets, reports (Priority: P3)

All persistent artifacts are stored in appropriate locations per project conventions: non-secret configuration lives under `.specific/{tool}.yaml`, sensitive data (SSH keys, API tokens) goes to `.personal/`, and reports/documentation are written to `wiki/`. The structure must be clean, machine-parseable (preferably YAML for configs), and never leak sensitive data into version control.

- **Why this priority**: Clean separation of concerns between config, secrets, and documentation ensures maintainability, security compliance, and easy access to operational reports.

**Acceptance Scenarios**:
1. **Given** a tool is registered, **When** its config is initialized, **Then** it creates `.specific/{tool}.yaml` with a structured YAML schema including tool metadata, provider settings, execution parameters, and optional migration configuration.
2. **Given** SSH credentials are collected, **When** they are saved, **Then** they are stored in `.personal/ssh.env` with restricted permissions (mode 0600) and excluded from version control.
3. **Given** an upgrade run completes, **When** a report is produced, **Then** it is written to `wiki/fleet-reports/{YYYY-MM-DD}-{tool}.md` as a human-readable markdown document, and the structured summary is appended to `.fleet/logs/LOGS.md` as before.

---

### Edge Cases

- What happens when a registered tool's config file is malformed? The system rejects it at preflight with a parse error indicating the offending field, and refuses to proceed until the operator fixes it.
- What happens when a provider plugin is registered but not properly installed? Discovery fails at preflight with an explicit error naming the missing dependency, and the system falls back to manual inventory input.
- What happens when a VM has a different OS/package manager than what the tool expects? The tool records a `BLOCKED` verdict with reason reflecting the incompatibility (e.g., "expected Debian/Ubuntu apt, found RedHat yum").
- What happens when the same tool is upgraded twice in quick succession? The second run yields UP-TO-DATE for all VMs and produces a zero-change report.
- What happens when rollback is attempted on a VM that never had an upgrade executed in the current run? Rollback refuses and exits with a clear error — rollback is only valid after a failed upgrade or for restoring from a prior run's backup. When rollback executes, it restores both the package version and configuration to their exact pre-upgrade state from the verified backup.
- What happens when two tools share a configuration directory (e.g., both affect `/etc/nginx`)? Each tool manages its own paths; conflicts are flagged as drift during survey.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The skill MUST maintain a tool registry that allows operators to register, list, and unregister software tools eligible for fleet upgrades.
- **FR-002**: The skill MUST allow the operator to select a discovery provider from a registered set (e.g., `doctl`, `vultr-cli`, `manual`) and MUST NOT attempt provider-specific API calls for unselected providers.
- **FR-003**: Provider plugins MUST expose a standard interface (discover, validate, reconcile) and MUST be registered via `.specific/{provider}.yaml` configuration files, following the same pattern as tool registrations.
- **FR-004**: Tool registrations MUST store configuration as YAML in `.specific/{tool}.yaml`, containing at minimum: tool identifier, package name, service name, version query command, precheck command, allowed origin patterns, hold patterns, optional migration configuration, and execution tuning.
- **FR-005**: The skill MUST collect and store sensitive credentials (SSH keys, API tokens) exclusively in the `.personal/` directory with restricted file permissions (mode 0600), and MUST refuse to commit any `.personal/` content to version control.
- **FR-006**: The audit/survey phase MUST assign exactly one verdict per VM per registered tool: SKIP, UP-TO-DATE, UPGRADE, BLOCKED(reason), or UNREACHABLE(reason), using the tool's specific version query and precheck commands.
- **FR-007**: The execution flow MUST follow the same gated pattern for every tool: read-only audit → summary review GATE → canary execution → canary review GATE → fleet rollout → final report. Fleet rollout MUST execute serially (one VM at a time) to minimize blast radius and ensure safety.
- **FR-008**: Before modifying any VM, the skill MUST create and verify a local configuration backup. A backup failure aborts that VM only.
- **FR-009**: After upgrading a VM, the skill MUST verify success using the tool's defined precheck and version-check commands.
- **FR-010**: A failed VM MUST receive one automatic retry round. If it still fails, it is marked FAILED and remaining VMs continue unaffected.
- **FR-011**: The skill MUST support rolling back a FAILED VM to its exact pre-upgrade state by restoring both the package version and configuration from the verified backup, and recording the outcome.
- **FR-012**: Reports and documentation MUST be written to `wiki/` in markdown format, preserving a dated append-only log per tool and per run.
- **FR-013**: The skill MUST preserve backward compatibility with the existing `nginx-fleet-upgrade` skill during transition: the nginx tool continues to function via `.specific/nginx-fleet.yaml` until explicitly migrated.
- **FR-014**: Re-running the full flow against the same fleet and tool MUST be idempotent: previously upgraded VMs yield UP-TO-DATE verdicts with zero changes.

### Key Entities *(include if feature involves data)*

- **Tool Registry**: Index of registered software tools, each with its playbook metadata (package name, service name, version query, precheck, optional migration bootstrap).
- **Provider Registry**: Index of registered discovery providers, each with its configuration stored in `.specific/{provider}.yaml` and exposing a standardized discover/reconcile interface.
- **Fleet Inventory**: Set of active VMs (name, address, reachability, status), source-agnostic — populated by whichever provider is selected.
- **Per-VM Record**: One record per VM per tool, holding survey evidence, verdict, execution steps, verification results, and drift flags.
- **Verdict**: Per-tool decision label — SKIP | UP-TO-DATE | UPGRADE | BLOCKED(reason) | UNREACHABLE(reason).
- **Config Backup**: Per-VM archive of the tool's configuration files, stored locally, verified before use, serving as the sole rollback artifact.
- **Approval Decision**: Operator's confirmed upgrade set at summary review and proceed/stop decision at canary review.
- **Drift Flag**: Indicator that the upgrade left upstream configuration templates alongside the active configuration, requiring manual review.
- **Runtime State**: Execution metadata (run ID, timestamps, provider used, tool version, execution outcomes) maintained in `.fleet/state.json`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can register a new tool in under five minutes by providing a YAML configuration and a basic test proving the tool's version query and precheck commands work on a single VM.
- **SC-002**: Any registered provider can discover the fleet inventory in the same time as the current `doctl`-based discovery (within a 10% variance), confirming provider selection does not introduce measurable overhead.
- **SC-003**: Zero sensitive files (SSH keys, API tokens) appear in the version-controlled repository at any point during or after an upgrade run.
- **SC-004**: Every successful upgrade run produces a report in `wiki/` listing every processed VM with its before/after version, outcome, and backup location.
- **SC-005**: A rollback restores a failed VM to a working state within two minutes of initiation (given network connectivity), verified by the tool's precheck command passing afterward.
- **SC-006**: The existing nginx-fleet-upgrade flow remains fully functional during migration — operators can complete a full nginx upgrade cycle using the current config path before explicitly migrating to the new system.
- **SC-007**: Two or more distinct tools can operate concurrently on the same fleet without interfering with each other's records, backups, or configurations.

## Assumptions

- The fleet consists of 10-100 Linux VMs reachable over SSH; most will be Debian/Ubuntu-family systems using apt (per existing project constitution). Support for other package managers may be added via tool registrations.
- Skills are managed through the Command Code agent-skills system; the common skill replaces (or wraps) the existing `nginx-fleet-upgrade` skill entry.
- YAML is the preferred format for configuration files in `.specific/`; if a tool requires complex dynamic configuration, JSON fallback is acceptable.
- Provider plugins are distributed as Python modules following a documented plugin contract.
- Wiki outputs are Markdown files organized under `wiki/fleet-reports/`, grouped by date and tool name.
- The `.personal/` directory is project-local and intended for credentials and sensitive data not shared across environments.
- Migration mode (replacing distro package sources with upstream official repositories) is optional per tool — many tools (e.g., Docker) may not benefit from or require migration mode.
