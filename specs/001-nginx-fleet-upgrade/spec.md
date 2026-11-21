# Feature Specification: nginx Fleet Upgrade

**Feature Branch**: `001-nginx-fleet-upgrade`

**Created**: 2026-11-20

**Status**: Draft

**Input**: User description: "@PLAN.md — nginx Fleet Upgrade Runbook: upgrade nginx on every DigitalOcean droplet with per-VM evidence, confirmation gates, and config-backup rollback. Agent-executed; no scripts required. The same flow is intended to extend to other tools later."

## Clarifications

### Session 2026-11-20

- Q: If a VM cannot be reached during the connection check, how should the runbook record it in the audit results? (FR-003, FR-005) → A: Add an `UNREACHABLE` verdict (with reason); create a per-VM record and include it in the summary, but never allow it in the upgrade set.
- Q: How many VMs should be upgraded in the canary phase before pausing for operator review? (FR-012) → A: Canary is the first 1 approved VM; pause for review after it completes.
- Q: If no candidate (available) nginx version can be determined for a reachable VM, what verdict should that VM receive? (FR-005, FR-006) → A: Verdict `BLOCKED` with reason "no candidate version determined"; recorded, shown in summary, never in the upgrade set.
- Q: Can the operator explicitly choose to upgrade a VM that has a BLOCKED verdict in this run? (FR-010, US2) → A: No — BLOCKED VMs cannot be added to the upgrade set; they remain excluded this run and the blocking issue must be resolved before a future upgrade.
- Q: After the canary VM finishes, what decision must the operator make before the run continues? (FR-012) → A: Operator explicitly chooses “proceed” (continue to remaining approved VMs, or complete if none remain) or “stop” (end the run with no further upgrades).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Read-only fleet audit with per-VM verdicts (Priority: P1)

The operator wants to know, for every VM in the fleet, whether nginx can be safely upgraded today — without changing anything. The feature assigns every VM in the fleet inventory exactly one verdict and a per-VM record. Reachable VMs are surveyed and have their evidence recorded (operating system, installed version, available version, package source, held packages, modules including third-party/dynamic ones, service state, TLS usage, server blocks, configuration validity). Unreachable VMs are not surveyed but are still recorded with the connectivity failure reason.

- **SKIP** — nginx is not installed
- **UP-TO-DATE** — installed version is at least the available version
- **UPGRADE** — eligible for upgrade
- **BLOCKED** — with a recorded reason (configuration test fails, package held, unexpected package source, third-party module not available from the standard source, or no candidate version can be determined)
- **UNREACHABLE** — connectivity check failed; reason recorded, no survey evidence collected, never eligible for the upgrade set

**Why this priority**: every later decision depends on this evidence, and the audit alone delivers value (full fleet visibility) at zero risk because nothing is modified.

**Independent Test**: Run the audit against the fleet; verify no VM was modified, every VM in the inventory has a per-VM record and one verdict (reachable VMs include survey evidence; unreachable VMs include the connectivity failure reason), and every BLOCKED verdict carries a reason.

**Acceptance Scenarios**:

1. **Given** an active fleet and valid access credentials, **When** the audit runs, **Then** every reachable VM has a per-VM record containing the survey evidence and exactly one verdict.
2. **Given** a VM without nginx installed, **When** it is surveyed, **Then** its verdict is SKIP.
3. **Given** a VM whose installed version is at least the available version, **When** it is surveyed, **Then** its verdict is UP-TO-DATE.
4. **Given** a VM with a failing configuration test, a held package, an unexpected package source, a third-party module unavailable from the standard source, or no determinable candidate version, **When** it is surveyed, **Then** its verdict is BLOCKED with the reason recorded.
5. **Given** an unreachable VM, **When** the audit runs, **Then** a per-VM record is created with verdict UNREACHABLE and the reason recorded, the VM appears in the summary but never in the upgrade set, and the audit continues for all other VMs.

---

### User Story 2 - Gated, canaried fleet rollout (Priority: P2)

The operator reviews one summary table of all verdicts, selects which VMs to upgrade (deselecting any), and explicitly approves. Execution then proceeds per VM: the VM's configuration is backed up and the backup verified before anything changes; the configuration is re-validated; the upgrade is applied; and the result is verified (configuration valid, service running, expected version installed, local HTTP — and HTTPS where TLS is used — responds). The first approved VM forms the canary; after it completes, the operator must explicitly choose to proceed (continue to the remaining approved VMs, or complete the run if none remain) or stop (end the run with no further upgrades). The remaining VMs run in parallel with bounded concurrency; a failure stops only that VM, and failed VMs receive one retry round before being marked FAILED.

**Why this priority**: this is the core value — actually upgrading the fleet — but it is only safe on top of Story 1's evidence; the canary and gates keep the blast radius small.

**Independent Test**: With a small approved set, execute the rollout; verify each VM had a verified backup before its first change, passes verification afterward, and that the canary was reviewed before fleet-wide rollout began.

**Acceptance Scenarios**:

1. **Given** audit records for all VMs, **When** the operator views the summary, **Then** VMs are grouped by verdict and the operator can deselect any VM before approving.
2. **Given** an approved upgrade set, **When** execution starts on a VM, **Then** that VM's configuration is backed up and the backup verified (exists and non-empty) before any change is made to that VM.
3. **Given** the canary VM has completed, **When** its result is in, **Then** execution pauses and the operator must explicitly choose to proceed (continue to the remaining approved VMs, or complete the run if none remain) or stop (end the run with no further upgrades).
4. **Given** the operator chooses to proceed after canary review, **When** the fleet rollout runs, **Then** the remaining VMs proceed in parallel with bounded concurrency and per-VM results are collected.
5. **Given** a VM that fails any execution step, **When** the failure occurs, **Then** only that VM is marked FAILED and all other VMs continue unaffected.
6. **Given** a BLOCKED VM, **When** the summary is reviewed, **Then** it is never auto-fixed and cannot be included in the upgrade set; the operator may acknowledge the block, but the VM remains excluded until the blocking issue is resolved in a future run.

---

### User Story 3 - Config rollback for a failed VM (Priority: P3)

If a VM fails after being upgraded, the operator can restore that VM's pre-upgrade configuration from its verified backup, bringing the service back to a healthy state. The package remains at the new version; downgrading the package version is a separate, explicitly operator-approved decision outside this feature.

**Why this priority**: it is the safety net that makes the rollout (P2) acceptable, but it is only needed when something fails, and it depends on the backups created during P2.

**Independent Test**: On a VM with a verified pre-upgrade backup, perform a rollback; verify the restored configuration passes the configuration test and the service is running.

**Acceptance Scenarios**:

1. **Given** a FAILED VM with a verified pre-upgrade backup, **When** rollback runs, **Then** the VM's configuration is restored, the configuration test passes, and the service is running.
2. **Given** a completed rollback, **When** the per-VM record is updated, **Then** it notes the rollback and the package remains at the new version.

---

### User Story 4 - Fleet report and audit trail (Priority: P4)

After execution, the operator receives a final report: one row per processed VM showing old → new version, backup location, verification result, and drift flags (upstream configuration templates left alongside the active config, meaning manual configuration review is needed). A dated summary entry is appended to the project log without altering previous entries.

**Why this priority**: it closes the loop for traceability and is required by the project's per-VM traceability principle, but it only has content once other stories have run.

**Independent Test**: After any execution, verify the report lists every processed VM with its outcome and that the project log contains a new dated summary entry.

**Acceptance Scenarios**:

1. **Given** execution has finished, **When** the report is produced, **Then** every processed VM appears with old → new version, backup location, verification result, and any drift flag.
2. **Given** a VM where the upgrade left upstream configuration templates side-by-side with the active configuration, **When** the report is produced, **Then** the VM is flagged as needing manual configuration update and nothing is auto-merged.
3. **Given** a completed run, **When** the summary is recorded, **Then** a dated entry is appended to the project log and no prior log entries are rewritten.

---

### Edge Cases

- What happens when the fleet inventory changed since the last run (VMs added or removed)? The differences are surfaced to the operator before proceeding.
- What happens when the fleet is empty or no VM is reachable? The report states this (all inventory VMs, if any, are UNREACHABLE in that case); nothing executes.
- What happens when every VM is UP-TO-DATE or SKIP? The approved upgrade set is empty and the report reflects that.
- What happens when a VM's backup file is missing or empty when checked? That VM aborts before any change is made to it.
- How does the system handle locally modified configuration files? The upgrade never hangs and never overwrites them: the existing configuration is preserved and new upstream templates are staged side-by-side, flagged for manual review.
- How does the system handle a VM serving only HTTPS? Verification uses the HTTPS check and records the result.
- What happens when no candidate version can be determined for a VM? The VM receives verdict BLOCKED with reason "no candidate version determined", is recorded and shown in the summary, and is never included in the upgrade set.
- What happens when access credentials are not yet stored? They are collected once, stored securely, and reused for all subsequent connections.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The feature MUST discover the current fleet inventory (active VMs with their names and addresses) and reconcile it against the previously known inventory, surfacing added and removed VMs.
- **FR-002**: The feature MUST collect access credentials once if not already stored, MUST keep them out of version control, and MUST reuse them for all subsequent VM connections.
- **FR-003**: The feature MUST test connectivity to every VM before surveying it. Unreachable VMs MUST receive verdict UNREACHABLE with the connectivity failure reason recorded in a per-VM record, appear in the summary, and be excluded from the upgrade set; they MUST be skipped without blocking other VMs.
- **FR-004**: The feature MUST survey each reachable VM read-only and record: operating system, installed nginx version, available candidate version, package source, held packages, modules (noting third-party or dynamic ones), service running/enabled state, presence of TLS certificates, server block count, and configuration validity.
- **FR-005**: The feature MUST assign every VM in the fleet inventory exactly one verdict: SKIP, UP-TO-DATE, UPGRADE, BLOCKED (with a reason), or UNREACHABLE (with the connectivity failure reason).
- **FR-006**: The feature MUST maintain one per-VM record per inventory VM containing the verdict and, for reachable VMs, all survey evidence and later the execution result; UNREACHABLE records contain the connectivity failure reason and no survey evidence. Records MUST NOT be merged across VMs.
- **FR-007**: The feature MUST present a single summary table of all VMs grouped by verdict and MUST allow the operator to deselect VMs before approving execution. Only VMs with verdict UPGRADE may be included in the approved upgrade set.
- **FR-008**: The feature MUST NOT modify any VM until the operator has explicitly approved the upgrade set at the summary review.
- **FR-009**: The feature MUST back up each VM's nginx configuration before changing that VM, retain a local copy of the backup, and verify it (exists and non-empty) before proceeding with that VM; a failed backup aborts that VM only.
- **FR-010**: The feature MUST refuse to upgrade a VM whose current configuration fails validation, whose package is held, whose package comes from an unexpected source, or whose candidate version cannot be determined; such VMs are BLOCKED, MUST NOT be auto-fixed, and MUST NOT be included in the upgrade set (no operator override in this run).
- **FR-011**: The feature MUST perform upgrades such that locally modified configuration is never overwritten or lost: the existing configuration is preserved and new upstream templates are staged side-by-side and flagged for manual review.
- **FR-012**: The feature MUST pause after the canary (the first approved VM) and require the operator to explicitly choose either to proceed (continue to the remaining approved VMs, or complete the run if none remain) or to stop (end the run with no further upgrades). If the operator chooses to stop, no further VMs are upgraded. If only one VM is approved, that VM is the canary and choosing to proceed completes the run after canary review with no fleet rollout.
- **FR-013**: The feature MUST execute the remaining approved VMs in parallel with bounded concurrency, collect per-VM results, and give failed VMs exactly one retry round before marking them FAILED.
- **FR-014**: After upgrading a VM, the feature MUST verify and record: configuration validity, service running, installed version equals the candidate version, and local HTTP (plus HTTPS when TLS is present) responds.
- **FR-015**: The feature MUST support restoring a failed VM's pre-upgrade configuration from its verified backup such that the configuration test passes and the service runs, leaving the package at the new version.
- **FR-016**: The feature MUST produce a final report listing, per VM: old → new version, backup location, verification result, and drift flags, and MUST append a dated summary to the project log without rewriting prior entries.
- **FR-017**: The feature MUST keep credentials, per-VM access data, and backups out of version control.
- **FR-018**: All steps MUST be safe to re-run against the same fleet: re-running the audit changes nothing, and re-running execution against an already-upgraded VM yields UP-TO-DATE rather than an error.

### Key Entities *(include if feature involves data)*

- **Fleet Inventory**: The set of active VMs (human-readable name, address, reachability, status); refreshed each run and diffed against the previous inventory.
- **Per-VM Record**: One record per VM holding survey evidence, verdict, execution steps and outcomes, verification results, and drift flags.
- **Verdict**: SKIP | UP-TO-DATE | UPGRADE | BLOCKED(reason) | UNREACHABLE(reason) — the single decision label per inventory VM driving the summary and the approved set (BLOCKED and UNREACHABLE VMs are never eligible for the upgrade set).
- **Config Backup**: A per-VM archive of the nginx configuration, stored on the VM and locally, verified before use; the only rollback artifact.
- **Approval Decision**: The operator's confirmed upgrade set at the summary review and the proceed/stop decision at the canary review.
- **Drift Flag**: A marker that the upgrade left upstream configuration templates alongside the active configuration, meaning manual configuration review is needed.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of VMs in the fleet inventory have a per-VM record and a verdict before any VM is modified; reachable VMs include survey evidence and UNREACHABLE VMs include the connectivity failure reason.
- **SC-002**: Zero VMs are modified without a recorded operator approval that includes that VM in the upgrade set.
- **SC-003**: Every upgraded VM has a verified pre-upgrade backup; 100% of upgrades are reversible to the prior configuration state.
- **SC-004**: A failure on any VM never prevents other VMs from completing their upgrade.
- **SC-005**: The operator reviews at most two stopping points per run (summary review, canary review) and can complete each review in a single pass from one table.
- **SC-006**: After a run, the operator can state — from the final report alone — every VM's before/after version, outcome, backup location, and any required follow-up configuration work.
- **SC-007**: Re-running the full flow against an already-upgraded fleet results in zero changes and UP-TO-DATE verdicts for all VMs.

## Assumptions

- The fleet consists of DigitalOcean VMs reachable over SSH; the package manager is apt on a Debian/Ubuntu-family operating system (per project constitution).
- This feature covers the nginx package only; extending the same flow to other tools is future work — the discover → access → survey → gate phases stay tool-agnostic, and each tool adds its own execution playbook.
- Rollback restores configuration only; downgrading the package version is a separate, explicitly operator-approved decision and out of scope.
- Unreachable VMs are skipped and reported, not retried; the only automatic retry is the single retry round for VMs that fail during execution.
- Parallel fleet execution is capped at a small constant concurrency (about 4 VMs at a time) to avoid overwhelming VMs or the operator's visibility.
- The local HTTP(S) check is a smoke test (status code recorded), not full application health validation.
