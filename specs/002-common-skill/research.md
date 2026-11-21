# Research: Common Fleet Upgrade Skill

**Feature**: 002-common-skill | **Date**: 2026-11-21

## R1: Provider Plugin Architecture

**Decision**: File-based provider registration via `.specific/{provider}.yaml` with a Python module implementing a standard interface.

**Rationale**: Matches the tool registration pattern (`.specific/{tool}.yaml`) for consistency. The YAML config declares provider metadata (CLI binary, auth method, discovery command template), while the Python module implements the discover/validate/reconcile interface. This keeps provider-specific logic isolated and testable.

**Alternatives considered**:
- Filesystem auto-discovery (`.fleet/providers/`): Rejected — less explicit, harder to track which providers are configured vs. available.
- Central registry file (`providers.yaml`): Rejected — single file becomes a bottleneck; per-provider YAML is cleaner for version control and per-provider overrides.
- Pure config-driven (no Python module): Rejected — provider CLIs have different output formats (JSON, CSV, text); a Python adapter is needed for parsing.

## R2: Tool Registration Schema

**Decision**: Each tool is defined by a `.specific/{tool}.yaml` file containing: tool identifier, package name, service name, version query command, precheck command, config paths, allowed origin patterns, hold patterns, optional migration configuration, and execution tuning.

**Rationale**: Directly generalizes the existing `tool` section from `nginx-fleet.yaml`. The schema captures everything needed for survey (version query, precheck), execute (package name, upgrade command), and rollback (config paths for backup). Migration mode is optional per tool.

**Alternatives considered**:
- Minimal schema (name + package only): Rejected — survey needs version_query and precheck; execute needs config_paths for backup; without these, the tool registration is incomplete.
- Code-based registration (Python class per tool): Rejected — over-engineering for config-driven tools; YAML is sufficient and operator-friendly.

## R3: Full Rollback Strategy

**Decision**: Rollback restores both the package version and configuration from the verified backup. The backup captures the pre-upgrade package version (via `dpkg-query`) and the configuration files (via tar archive). Rollback reinstalls the old package version and restores the config archive.

**Rationale**: The constitution requires a "working rollback path." Config-only rollback leaves the VM in a mixed state (new package, old config) which may not be stable. Full rollback returns the VM to its exact pre-upgrade state.

**Alternatives considered**:
- Config-only rollback (original nginx skill): Rejected — does not guarantee a working state if the new package is incompatible with old config.
- Snapshot-based rollback (VM-level): Rejected — out of scope for a config-level skill; requires hypervisor integration.

## R4: Serial Fleet Execution

**Decision**: After canary approval, fleet rollout executes one VM at a time (serial). Each VM completes fully (backup → upgrade → verify) before the next begins.

**Rationale**: The constitution's safety-first principle and the clarification answer (fleet size 10-100 VMs) make serial execution acceptable. Serial execution minimizes blast radius — if a tool's playbook has a bug, only one VM is affected before the operator can halt. For 100 VMs, the total time is longer but the risk is bounded.

**Alternatives considered**:
- Bounded parallel (5-10 VMs): Rejected — increases blast radius; operator cannot react fast enough if a batch fails.
- Configurable concurrency: Rejected — adds complexity without clear benefit for the target fleet size; serial is safest.

## R5: Backward Compatibility with nginx-fleet-upgrade

**Decision**: The existing `nginx-fleet-upgrade` skill remains functional. The new `fleet-upgrade` skill reads `.specific/nginx-fleet.yaml` (the existing config) and treats nginx as a registered tool. During transition, both skills can coexist.

**Rationale**: FR-013 requires backward compatibility. The existing config schema is a valid tool registration; the new skill adapts it internally. No migration is required — operators can continue using the old skill until they explicitly register nginx with the new skill.

**Alternatives considered**:
- Force migration to new schema: Rejected — breaks existing workflows; violates the "change only what is needed" principle.
- Deprecate old skill immediately: Rejected — no transition period; operators have no time to validate the new skill.

## R6: Provider Interface Contract

**Decision**: Providers implement a Python class with three methods: `discover() -> list[dict]`, `validate() -> bool`, and `reconcile(previous: list[dict], current: list[dict]) -> tuple[list[str], list[str]]`. The provider's `.specific/{provider}.yaml` declares the CLI binary, auth check command, and discovery command template.

**Rationale**: The three methods map to the existing inventory module's responsibilities. `discover()` fetches VMs from the provider's API/CLI. `validate()` checks that the provider CLI is installed and authenticated. `reconcile()` computes added/removed VMs against previous inventory.

**Alternatives considered**:
- Single `discover()` method only: Rejected — validation and reconciliation are distinct concerns; separating them allows better error messages and testability.
- Plugin-as-script (shell-based): Rejected — shell scripts cannot easily return structured data; Python modules are more maintainable.

## R7: Config Loading and Validation

**Decision**: Reuse the existing `Config` class pattern from `nginx-fleet-upgrade/scripts/fleetkit/config.py`. Extend it to load both tool configs (`.specific/{tool}.yaml`) and provider configs (`.specific/{provider}.yaml`). Validation uses the same `_check_unknown` + `_validate` pattern.

**Rationale**: The existing config loader is well-tested and handles YAML parsing, deep merging with defaults, unknown key detection, and type validation. Extending it preserves these guarantees.

**Alternatives considered**:
- New config library (pydantic, marshmallow): Rejected — adds a dependency; the existing pattern works and is understood.
- Schema-per-tool (dynamic validation): Rejected — over-engineering; a single schema with optional sections (migration) is sufficient.

## R8: State Management

**Decision**: Continue using `.fleet/state.json` as the single source of truth. Extend the record structure to include a `tool` field, so each VM can have multiple records (one per tool).

**Rationale**: The existing state module is proven. Adding a `tool` field to records allows concurrent tool operations without interfering with each other's state (FR-007, SC-007).

**Alternatives considered**:
- Per-tool state files (`.fleet/{tool}/state.json`): Rejected — fragments state; makes cross-tool reporting harder.
- Database (SQLite): Rejected — over-engineering for 10-100 VMs; JSON is sufficient and human-readable.
