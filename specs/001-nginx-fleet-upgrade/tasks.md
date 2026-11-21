# Tasks: nginx Fleet Upgrade

**Input**: Design documents from `/specs/001-nginx-fleet-upgrade/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included because `plan.md` and `quickstart.md` define the verification strategy
(stdlib `unittest` + fake `doctl`/`ssh`/`scp` fixtures); the specification itself does not
request TDD.

**Organization**: Tasks are grouped by user story so each story can be implemented and
tested as an independent increment.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US4)
- Include exact file paths in descriptions

## Path Conventions

- Skill root: `.agents/skills/nginx-fleet-upgrade/`
- Python CLI: `.agents/skills/nginx-fleet-upgrade/scripts/` (`fleet.py`, `fleetkit/`)
- Tests: `.agents/skills/nginx-fleet-upgrade/scripts/tests/`
- Runtime config: `.specific/nginx-fleet.yaml`
- Runtime artifacts: `ip.txt`, `plan/`, `backups/`, `.fleet/`, `LOGS.md`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the skill skeleton, configuration/reference seeds, and repository hygiene.

- [X] T001 Create the skill directory tree and `SKILL.md` frontmatter skeleton (`name: nginx-fleet-upgrade`, description of gated fleet audit/upgrade/rollback) at `.agents/skills/nginx-fleet-upgrade/SKILL.md`, with `references/` and `scripts/` subdirectories.
- [X] T002 [P] Create `.agents/skills/nginx-fleet-upgrade/references/fleet-config.template.yaml` matching `specs/001-nginx-fleet-upgrade/contracts/config.schema.yaml`, including defaults: `execution.canary_size: 1` (const), `execution.retry_rounds: 1` (range 0..1), `execution.concurrency: 4` (range 1..16), and the nginx tool playbook.
- [X] T003 [P] Create `.agents/skills/nginx-fleet-upgrade/references/record-template.md` with the fixed section order from `specs/001-nginx-fleet-upgrade/contracts/record.md` (header, Survey evidence, Connectivity for UNREACHABLE, Execution, Verification, Drift, Rollback).
- [X] T004 [P] Add `plan/` and `.fleet/` to `.gitignore`, then untrack the already-committed `ip.txt` with `git rm --cached ip.txt` (keep the working file; confirm with the user before running the index change).
- [X] T005 Create the CLI entry `scripts/fleet.py` (argparse global options `--root`, `--config`, `--json`, `--log-level`) and the package marker `scripts/fleetkit/__init__.py` under `.agents/skills/nginx-fleet-upgrade/`.

**Checkpoint**: Skill scaffolding exists; no behavior yet.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared infrastructure every user story depends on.

**⚠️ CRITICAL**: No user-story work can begin until this phase is complete.

- [X] T006 [P] Implement config loading/validation in `scripts/fleetkit/config.py`: apply schema defaults, reject unknown keys (exit 2), require `execution.canary_size == 1`, `0 <= retry_rounds <= 1`, `1 <= concurrency <= 16`, and `{package}` in `upgrade_command`; resolve all paths relative to `--root`.
- [X] T007 [P] Implement the atomic JSON state store in `scripts/fleetkit/state.py`: `schema_version: 1`, run ID `YYYYMMDDTHHMMSSZ-<6 alnum>`, temp-file+rename writes, reject unknown schema versions, and provide read/update helpers for inventory, records, approvals, gates, and report markers.
- [X] T008 [P] Implement the SSH command runner in `scripts/fleetkit/ssh.py`: `ssh`/`scp` subprocesses with `BatchMode=yes`, `ConnectTimeout`, `StrictHostKeyChecking=accept-new`, `sudo -n` when `ssh.privilege: auto` and UID ≠ 0, per-command timeout, and captured stdout/stderr/exit code.
- [X] T009 [P] Implement inventory handling in `scripts/fleetkit/inventory.py`: parse `Name,IP` (no comma/newline in name, IPv4 validation), dedupe by IP, sort by name, write `ip.txt`, and diff against the previous snapshot as `added`/`removed` keyed on IP.
- [X] T010 Implement CLI dispatch in `scripts/fleetkit/cli.py`: subcommand routing, the JSON envelope `{schema_version, ok, command, run_id, data, warnings, error}`, and stable exit codes `0/1/2/3/4/5` per `contracts/cli.md`.
- [X] T011 [P] Implement the deterministic record renderer in `scripts/fleetkit/records.py` for the header and Survey evidence sections; render `unknown` for missing values and create `plan/` on demand.
- [X] T012 [P] Build the test fixtures in `scripts/tests/fixtures/`: fake `bin/doctl`, `bin/ssh`, `bin/scp` that read `scenarios/*.json`, plus the four-VM scenario (upgradable, up-to-date, blocked, unreachable).
- [X] T013 Create `scripts/tests/__init__.py` (required for `unittest discover -t .`) and unit tests `test_config.py`, `test_state.py`, `test_inventory.py`, `test_ssh.py` covering defaults, unknown-key rejection, atomic writes, dedupe/sort/diff, and SSH argv construction.
- [X] T014 [P] Implement `doctor` (config validity, `ssh`/`scp`/`doctl` presence, `doctl auth`, SSH env file existence and mode warning) and `config --init` (refuse overwrite without `--force`) in `scripts/fleetkit/cli.py` and `scripts/fleetkit/config.py`.
- [X] T015 [P] Implement per-run logging in `scripts/fleetkit/ssh.py`: write `.fleet/logs/<run_id>/<ip>.log`, redact configured `logging.redact` substrings, and never log `.personal/` contents.
- [X] T016 Register the verification recipes in `.specific/project.yaml` `skills:` (name + literal command): `verify-audit`, `verify-rollout`, `verify-rollback`, and `verify-report` using the commands listed in the Verification tasks below.

**Checkpoint**: Config, state, SSH, inventory, CLI, rendering, fixtures, and logging are ready; user stories can start.

---

## Phase 3: User Story 1 - Read-only fleet audit with per-VM verdicts (Priority: P1) 🎯 MVP

**Goal**: Assign every inventory VM exactly one verdict with recorded evidence, changing nothing.

**Independent Test**: Run the audit against the fleet; no VM is modified, every inventory IP has `plan/{ip}.md` plus one verdict, reachable VMs show full evidence, and every `BLOCKED`/`UNREACHABLE` record carries a reason.

### Implementation for User Story 1

- [X] T017 [P] [US1] Implement `scripts/fleetkit/verdict.py`: Debian version comparison (epoch/upstream/revision, `~` ordering, digit vs non-digit runs) and the fixed precedence `UNREACHABLE → SKIP → BLOCKED → UP-TO-DATE → UPGRADE`; a current-but-failing-config VM is `BLOCKED`, not `UP-TO-DATE`.
- [X] T018 [P] [US1] Implement `discover` in `scripts/fleetkit/inventory.py` and `scripts/fleetkit/cli.py`: parse `doctl compute droplet list --output json`, keep `status == "active"` droplets with a public IPv4, write `ip.txt`, persist the snapshot, and report `added`/`removed`; an empty fleet is a successful discovery.
- [X] T019 [P] [US1] Implement evidence collectors in `scripts/fleetkit/survey.py`: OS (`PRETTY_NAME`), installed version (`tool.version_query`), candidate version and source (`apt-cache policy`), holds (`apt-mark showhold`), static/dynamic modules (`nginx -V`, `load_module`), third-party module detection, service active/enabled, TLS directives, server-block count, and `tool.precheck` result.
- [X] T020 [US1] Implement connectivity preflight and `UNREACHABLE` handling in `scripts/fleetkit/survey.py`: record the connectivity failure reason, collect no evidence, and continue surveying other VMs.
- [X] T021 [US1] Implement `survey --all|--ip|--parallel` in `scripts/fleetkit/survey.py` and `scripts/fleetkit/cli.py`: bounded `ThreadPoolExecutor` fan-out, merge results in the main thread, write state, and return exit 0 when some VMs are `BLOCKED`/`UNREACHABLE`.
- [X] T022 [US1] Implement `summary` rendering in `scripts/fleetkit/survey.py` and `scripts/fleetkit/cli.py`: grouped verdict table plus JSON `groups` and `eligible` (only `UPGRADE` IPs).
- [X] T023 [P] [US1] Unit tests in `scripts/tests/test_verdict.py` and `scripts/tests/test_survey.py`: ordered version pairs (`1:1.0-1` > `1.0`, `1.0~rc1` < `1.0`), apt-policy/`nginx -V` parsing, verdict matrix, BLOCKED precedence, and reason text for held package, failed config test, unexpected origin, third-party module, and no candidate version.
- [X] T024 [P] [US1] Integration test `scripts/tests/test_audit_flow.py` with the four-VM fixture fleet: run `discover` then `survey --all`, assert one record and one verdict per IP, `UNREACHABLE` has no evidence, no mutating SSH command is invoked, and `summary --json` lists only `UPGRADE` in `eligible`.
- [X] T025 [US1] Extend `scripts/fleetkit/records.py` to render `plan/{ip}.md` for every verdict: full evidence table for reachable VMs; `Connectivity` section (result, reason, no evidence) for `UNREACHABLE`; non-empty `Reason` for `BLOCKED`/`UNREACHABLE`.
- [X] T026 [US1] Verify read-only audit via skill `verify-audit`: `python3 -m unittest discover -s .agents/skills/nginx-fleet-upgrade/scripts/tests -t .agents/skills/nginx-fleet-upgrade/scripts -k verdict -k survey -k inventory -k audit_flow` — expected: all audit tests pass, including the fixture fleet proving one record/verdict per IP and zero mutating commands; live `survey --all` remains an operator-gated read-only step.

**Checkpoint**: US1 is independently functional and is the MVP.

---

## Phase 4: User Story 2 - Gated, canaried fleet rollout (Priority: P2)

**Goal**: Backup, verify, upgrade, verify again — gated by explicit approval and a canary decision.

**Independent Test**: With a small approved set, each VM has a verified backup before its first change, the canary pauses for proceed/stop, verification passes, failures are isolated, and failed VMs get exactly one retry.

**Note**: US2 consumes US1's verdicts and records; it is testable with fixtures without a live fleet.

### Implementation for User Story 2

- [X] T027 [P] [US2] Implement backup creation/download/verification in `scripts/fleetkit/backup.py`: remote `tar czf /var/backups/nginx-<epoch>.tar.gz` over `tool.config_paths`, `scp` to `backups/{ip}/`, then require `size_bytes > 0` and a 64-hex `sha256` match before any change; abort that VM only on failure.
- [X] T028 [US2] Implement execution step builders in `scripts/fleetkit/execute.py` for `backup → precheck → upgrade → verify → drift`, using `execution.upgrade_command` (containing `{package}`) with `--force-confdef --force-confold`; never run `dist-upgrade`, package removal, or `--fix-broken`.
- [X] T029 [US2] Implement fail-closed approval validation in `scripts/fleetkit/execute.py`: require `--yes`, a non-empty deduplicated `--approve` list, every IP present in inventory, and every IP verdict exactly `UPGRADE`; otherwise exit 3 without contacting a VM.
- [X] T030 [US2] Implement `execute --phase canary` in `scripts/fleetkit/execute.py`: process exactly the first approved VM not already terminal in this run, persist `phase: canary`, and exit 4 if that VM fails (state still recorded).
- [X] T031 [US2] Implement `gate --decision proceed|stop` in `scripts/fleetkit/state.py` and `scripts/fleetkit/cli.py`: refuse (exit 3) unless the canary is terminal; record `decision`, `decided_at`, `note`; `stop` ends the run and `proceed` is required before fleet execution.
- [X] T032 [US2] Implement `execute --phase fleet` in `scripts/fleetkit/execute.py`: refuse (exit 3) without a recorded canary `proceed`, run remaining approved VMs in a `ThreadPoolExecutor` capped by `execution.concurrency`, isolate failures, and retry a failed VM exactly once (`attempts <= 2`) before marking `FAILED`.
- [X] T033 [US2] Implement post-upgrade verification and drift in `scripts/fleetkit/execute.py`: `tool.precheck` (0), `systemctl is-active <tool.service>`, installed version equals candidate, HTTP probe (and HTTPS when `ssl_certificate` is present), record status codes; any HTTP response counts unless `verify.require_status` is non-empty; flag `*.dpkg-dist`/`*.dpkg-new`/`*.ucf-dist` as drift without merging.
- [X] T034 [US2] Implement `--dry-run` (print exact per-VM commands, no SSH, no state change) and idempotent skip (already-`SUCCEEDED` in this run, or installed version ≥ candidate → `UP-TO-DATE`, no upgrade) in `scripts/fleetkit/execute.py`.
- [X] T035 [P] [US2] Unit tests in `scripts/tests/test_execute.py`: approval guards (exit 3 for BLOCKED/UNREACHABLE/SKIP/UP-TO-DATE, missing `--yes`, duplicate IPs), retry counting capped at 2, concurrency cap honored, dry-run performs no SSH, and backup verification aborts before upgrade.
- [X] T036 [P] [US2] Integration test `scripts/tests/test_rollout_flow.py` with fake `ssh`/`scp`: full canary → `gate proceed` → fleet across the fixture fleet, including one VM failing then succeeding on retry, one VM failing both attempts, and one VM unaffected; assert canary `stop` prevents all fleet upgrades.
- [X] T037 [P] [US2] Extend `scripts/fleetkit/records.py` with Execution and Verification sections: phase, state, old → new, attempts, backup path/size/sha256, per-step results, and HTTP/HTTPS status codes.
- [X] T038 [US2] Verify rollout via skill `verify-rollout`: `python3 -m unittest discover -s .agents/skills/nginx-fleet-upgrade/scripts/tests -t .agents/skills/nginx-fleet-upgrade/scripts -k execute` — expected: approval guards, canary gate, retry-once, failure isolation, and dry-run tests all pass.

**Checkpoint**: US1 and US2 work independently; canary/fleet rollout is gate-enforced.

---

## Phase 5: User Story 3 - Config rollback for a failed VM (Priority: P3)

**Goal**: Restore a failed VM's pre-upgrade configuration from a verified backup; package stays new.

**Independent Test**: On a VM with a verified pre-upgrade backup, rollback restores the config, the configuration test passes, the service runs, and the package version is unchanged.

**Note**: US3 depends on the verified backup artifact produced by US2.

### Implementation for User Story 3

- [X] T039 [P] [US3] Implement rollback restoration in `scripts/fleetkit/rollback.py`: upload the verified local archive, archive the current config as `*-pre-rollback`, extract over `tool.config_paths`, run `tool.precheck`, and restart `<tool.service>` only when the precheck passes; never downgrade the package.
- [X] T040 [US3] Implement `rollback --ip` in `scripts/fleetkit/cli.py`: require a recorded `FAILED` execution, a verified backup, and `--yes`; support `--dry-run`; exit 3 on unmet preconditions and 4 when the VM does not return to a healthy state; persist the rollback result.
- [X] T041 [P] [US3] Unit tests in `scripts/tests/test_rollback.py`: preconditions (no failure, unverified/missing backup, missing `--yes`), restore argv construction, no restart when precheck fails, and package version left unchanged.
- [X] T042 [P] [US3] Integration tests in `scripts/tests/test_rollback.py` with fake `ssh`/`scp`: successful restore records `ROLLED_BACK`; failing precheck leaves the service un-restarted and records failure; rollback is repeatable.
- [X] T043 [US3] Extend `scripts/fleetkit/records.py` with the Rollback section: state, pre-rollback archive path, config test after restore, service state, and "package unchanged at `<new_version>`".
- [X] T044 [US3] Verify rollback via skill `verify-rollback`: `python3 -m unittest discover -s .agents/skills/nginx-fleet-upgrade/scripts/tests -t .agents/skills/nginx-fleet-upgrade/scripts -k rollback` — expected: guard, restore, precheck-failure, and idempotency tests pass.

**Checkpoint**: US3 provides the safety net; US1–US3 are independently testable.

---

## Phase 6: User Story 4 - Fleet report and audit trail (Priority: P4)

**Goal**: Produce the final per-VM report and append exactly one dated log entry.

**Independent Test**: After execution, the report lists every processed VM with old → new, backup location, verification, and drift; `LOGS.md` gains one dated entry and prior entries are untouched.

**Note**: US4 renders data produced by US1–US3; fixture-based tests make it independently testable.

### Implementation for User Story 4

- [X] T045 [P] [US4] Implement final report rendering in `scripts/fleetkit/report.py`: per-VM rows with old → new version, backup location, verification result, drift flags, plus a JSON shape with the same fields.
- [X] T046 [US4] Implement append-only `LOGS.md` output in `scripts/fleetkit/report.py`: `report --log` appends one dated heading + one-line summary, sets `report.logged_at`, and refuses to duplicate the entry on repeat; never rewrite or reorder prior entries.
- [X] T047 [P] [US4] Unit tests in `scripts/tests/test_report.py`: table/JSON formatting for all verdicts and outcomes, append-only behavior, duplicate-log guard, and empty-fleet/every-VM-UP-TO-DATE reporting.
- [X] T048 [P] [US4] Integration tests in `scripts/tests/test_report.py`: run a fixture audit + rollout, produce the report, append the log, re-run `report --log`, and assert exactly one new entry with prior content byte-identical.
- [X] T049 [US4] Verify report via skill `verify-report`: `python3 -m unittest discover -s .agents/skills/nginx-fleet-upgrade/scripts/tests -t .agents/skills/nginx-fleet-upgrade/scripts -k report` — expected: report tests pass, including every VM row, empty-fleet output, and the duplicate-log guard.

**Checkpoint**: All four user stories are functional and independently verifiable.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Operator-facing documentation, metadata, and end-to-end validation.

- [X] T050 [P] Complete `.agents/skills/nginx-fleet-upgrade/SKILL.md`: when/when-not to use, config contract, GATE flow (access credentials, summary approval, canary proceed/stop), command reference, failure modes table, and safety rules (read-only until GATE, verified backup before change, no auto-fix of BLOCKED VMs).
- [X] T051 [P] Update `.specific/project.yaml` (`architecture.language: Python`, `architecture.unit_test_framework: unittest`) and the corresponding `PROJECTS.md` architecture fields; refresh `.specific/project-features.yaml` summaries for ip-scan, vm-audit, plan-review, and upgrade-execute.
- [X] T052 [P] Run quickstart offline scenarios 1–3 from `specs/001-nginx-fleet-upgrade/quickstart.md`: suite passed (78 tests), `config --init` wrote `.specific/nginx-fleet.yaml`, and file-source discovery reconciled the roster in a temp root. `doctor` correctly exits 5 until the operator supplies `.personal/ssh.env`; live doctl/mutation scenarios remain operator-gated.
- [X] T053 Security review: confirm no secrets or `.personal/` values reach config/state/logs/records, `git check-ignore` covers `ip.txt`, `plan/`, `backups/`, `.fleet/`, `.personal/`, and `ip.txt` is untracked; verify SSH key mode warning works.
- [X] T054 Run the full gate: `python3 -m compileall -q .agents/skills/nginx-fleet-upgrade/scripts/fleet.py .agents/skills/nginx-fleet-upgrade/scripts/fleetkit` and `python3 -m unittest discover -s .agents/skills/nginx-fleet-upgrade/scripts/tests -t .agents/skills/nginx-fleet-upgrade/scripts -v`; fix every failure before reporting completion.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies; start immediately.
- **Foundational (Phase 2)**: Depends on Setup; BLOCKS all user stories.
- **User Stories (Phases 3–6)**: Depend on Foundational.
  - US1 can start immediately after Phase 2.
  - US2 depends on US1's verdict/record/state interfaces.
  - US3 depends on US2's verified backup artifact.
  - US4 depends on US1–US3 data being present.
- **Polish (Phase 7)**: Depends on the desired user stories being complete.

### User Story Dependencies

- **US1 (P1)**: No story dependencies; MVP.
- **US2 (P2)**: Consumes US1 verdicts and records; independently testable via fixtures.
- **US3 (P3)**: Consumes US2 backups; independently testable via fixtures.
- **US4 (P4)**: Consumes US1–US3 state; independently testable via fixtures.

### Within Each User Story

- Implementation foundations before the command wiring.
- Unit and integration tests in the same phase as the code they cover.
- Records rendered from the final model before the verification task.
- Story verification task runs last and must pass before moving on.

### Parallel Opportunities

- Setup: T002, T003, T004 in parallel after T001.
- Foundational: T006, T007, T008, T009, T011, T012 in parallel after T005; then T010; then T013, T014, T015, T016.
- US1: T017, T018, T019 in parallel; T023 and T024 in parallel after implementation.
- US2: T027 in parallel with T028; T035, T036, T037 in parallel after execution logic stabilizes.
- US3: T039 first; T041 and T042 in parallel after T040.
- US4: T045 first; T047 and T048 in parallel after T046.
- Polish: T050, T051, T052, T053 in parallel; T054 last.

---

## Parallel Example: User Story 1

```bash
# Independent implementation modules
Task: "Implement verdict engine in scripts/fleetkit/verdict.py"
Task: "Implement discover in scripts/fleetkit/inventory.py and cli.py"
Task: "Implement evidence collectors in scripts/fleetkit/survey.py"

# After implementation stabilizes
Task: "Unit tests in scripts/tests/test_verdict.py and test_survey.py"
Task: "Integration audit test in scripts/tests/test_audit_flow.py"
```

## Parallel Example: User Story 2

```bash
Task: "Implement backup verification in scripts/fleetkit/backup.py"
Task: "Implement execution step builders in scripts/fleetkit/execute.py"
Task: "Extend execution/verification record sections in scripts/fleetkit/records.py"
Task: "Unit tests in scripts/tests/test_execute.py"
Task: "Rollout integration test in scripts/tests/test_rollout_flow.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 (Setup).
2. Complete Phase 2 (Foundational) — blocks everything.
3. Complete Phase 3 (US1 audit).
4. **STOP and VALIDATE**: run `verify-audit`; confirm every inventory IP has a record and
   verdict, and no VM changed.
5. This is the deliverable value at zero risk.

### Incremental Delivery

1. Setup + Foundational → foundation ready.
2. US1 → read-only fleet visibility (MVP).
3. US2 → gated canary + fleet rollout.
4. US3 → configuration rollback safety net.
5. US4 → report and append-only audit trail.
6. Polish → skill documentation, metadata, security review, full suite.

### Notes

- `[P]` tasks touch different files and have no incomplete dependencies.
- Live validation (real `doctl`, real SSH) is read-only except approved canary and
  rollback drills; never run mutation scenarios without the operator GATE.
- Commit after each task or logical group; keep `LOGS.md` append-only.
