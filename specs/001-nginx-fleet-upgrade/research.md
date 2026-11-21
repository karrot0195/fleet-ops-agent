# Phase 0 Research: nginx Fleet Upgrade

All technical unknowns are resolved below. No `NEEDS CLARIFICATION` items remain.
The deliverable shape was confirmed with the operator during planning: an **Agent Skill
plus Python scripts**.

## D1 — Deliverable composition

- **Decision**: Ship an Agent Skill containing the procedure/gates plus bundled Python
  scripts, with non-secret settings in `.specific/nginx-fleet.yaml`.
- **Rationale**: The skill carries the conversational gates (summary review, canary
  proceed/stop) and the operator-facing runbook; the Python CLI carries deterministic,
  testable mechanics. This matches the existing `server-deploy` pattern in this repo
  (skill + `scripts/*.py` + config in `.specific/`).
- **Alternatives considered**:
  - Documented commands only — rejected: no enforceable approval guard, weaker
    idempotency and state.
  - Full standalone CLI outside a skill — rejected: gates and procedure would have no
    agent-facing home.
  - Bash scripts — rejected: fragile JSON/YAML parsing, harder unit testing, poorer
    structured state handling.

## D2 — Skill location

- **Decision**: Create `.agents/skills/nginx-fleet-upgrade/` as a real directory owned
  by this repository.
- **Rationale**: `.agents/skills/*` currently contains symlinks into the `agent-skills`
  submodule (a separate shared repository). This workflow is project-specific; editing
  the submodule would create cross-repo coupling and an uncommitted-submodule state.
- **Alternatives considered**:
  - Add the skill to `agent-skills/common-skills/` — rejected: shared repo, unrelated
    to this project's fleet.
  - `.specific/skills/...` with a discovery symlink — rejected: adds indirection with
    no benefit; real directories are already valid skill locations.

## D3 — Language, dependencies, and execution model

- **Decision**: Python 3.11+ using only the standard library plus PyYAML; invoke
  `doctl`, `ssh`, and `scp` as subprocesses. No `paramiko`, Ansible, or local `nginx`.
- **Rationale**: Verified host Python 3.14.10, `doctl` 1.179.0, OpenSSH, and PyYAML.
  Subprocess invocation keeps behavior transparent and testable with fake executables;
  no credentials enter a Python SSH library.
- **Alternatives considered**:
  - Ansible — rejected: heavy dependency, harder to enforce the custom gate/state model.
  - `paramiko` — rejected: adds a dependency and duplicates OpenSSH key/agent behavior.
  - Runtime chosen must also work on Python 3.11 (common operator baseline).

## D4 — Gating model

- **Decision**: No interactive prompts inside the CLI. Mutating commands require an
  explicit approval artifact on the command line (`--approve <ips>` for execution,
  `--yes` to confirm), and canary decisions are recorded with
  `gate --decision proceed|stop`. The skill performs the human GATEs and only then
  invokes the CLI.
- **Rationale**: Agents and CI run non-interactively; explicit flags are auditable and
  replayable. Validating the entire approved set before any mutation makes the CLI
  fail closed (mixing in a BLOCKED/UNREACHABLE IP aborts the run).
- **Alternatives considered**:
  - `input()`/TTY prompts — rejected: cannot be driven reliably by the agent.
  - Environment-variable approval — rejected: easy to leak or inherit accidentally.
  - Approval file only — rejected: unnecessary for a 12-VM fleet; comma-separated IPs
    are reviewable in one line.

## D5 — State and record representation

- **Decision**: `.fleet/state.json` is the machine source of truth (atomic
  temp-file+rename writes, schema versioned). `plan/{ip}.md` is rendered
  deterministically from state after survey and after execution.
- **Rationale**: Enables resume, idempotent re-runs, and reliable reporting without a
  database. Markdown remains the human/traceability artifact required by the
  constitution.
- **Alternatives considered**:
  - Markdown as source of truth — rejected: brittle parsing and merge conflicts.
  - SQLite — rejected: overkill for one operator and ~12 VMs.

## D6 — Inventory discovery

- **Decision**: Parse `doctl compute droplet list --output json`, keep droplets with
  `status == "active"` and a public IPv4, write `ip.txt` as `Name,IP` one per line
  (sorted by name, deduped by IP), and diff against the previous inventory snapshot
  stored in state.
- **Rationale**: JSON is stable to parse; the `Name,IP` format keeps fleet files
  human-readable (project convention); `ip.txt` is overwritten only with the IP column
  preserved for iteration.
- **Alternatives considered**:
  - Parsing `doctl` table output — rejected: column/format drift.
  - Terraform/tag discovery — rejected: no such source in this project.

## D7 — Verdict precedence

- **Decision**: Evaluate in this order and stop at the first match:
  `UNREACHABLE` → `SKIP` → `BLOCKED` → `UP-TO-DATE` → `UPGRADE`.
- **Rationale**: Unreachable VMs cannot be surveyed. A block condition (failed config
  test, held package, unexpected origin/source build, third-party module risk,
  undeterminable candidate) must surface even when no version change is needed;
  otherwise a broken-but-current VM would be silently reported healthy.
- **Alternatives considered**:
  - Upgrade availability first (PLAN.md's loose ordering) — rejected: hides actionable
    block conditions on current VMs.

## D8 — Debian version comparison

- **Decision**: Implement the Debian version comparison algorithm in Python (epoch,
  upstream, revision; `~` ordering; digit/non-digit runs) and unit-test it against
  known ordered pairs. Do not shell out to `dpkg --compare-versions` locally (host is
  Fedora and has no `dpkg`).
- **Rationale**: Pure function, fast, testable, and avoids an extra SSH round trip in
  the survey.
- **Alternatives considered**:
  - Remote `dpkg --compare-versions` — rejected: per-VM extra call, harder to unit test.
  - Naive string comparison — rejected: wrong for epochs, revisions, and `~`.

## D9 — Package origin and module risk detection

- **Decision**: Record the installed source from `apt-cache policy nginx` and classify
  it against `tool.allowed_origin_patterns`. Treat a working `nginx` binary with no
  dpkg package as a source build (`BLOCKED`, unexpected origin). Parse `nginx -V` for
  `--with-*_module`/`--add-dynamic-module` and scan `load_module` directives; dynamic
  modules outside allowed directories or non-core static modules are flagged
  `BLOCKED` with reason `third-party module requires review`.
- **Rationale**: FR-010 requires blocking unexpected sources and unavailable
  third-party modules. A conservative allowlist avoids guessing compatibility; the
  operator resolves the block in a future run.
- **Alternatives considered**:
  - Attempt automatic module compatibility analysis — rejected: out of scope and
    unsafe.
  - Ignore modules — rejected: violates FR-010.

## D10 — Upgrade mechanics

- **Decision**: `DEBIAN_FRONTEND=noninteractive apt-get install --only-upgrade nginx`
  with `-o Dpkg::Options::="--force-confdef" --force-confold`. No `dist-upgrade`, no
  removal, no `--fix-broken`.
- **Rationale**: FR-011 requires preserving locally modified configuration; conffile
  forcing keeps the existing config and stages new templates as `*.dpkg-dist`.
  `--only-upgrade` prevents new package installs.
- **Alternatives considered**:
  - `apt-get upgrade`/`dist-upgrade` — rejected: wider blast radius.
  - Direct `dpkg -i` — rejected: bypasses dependency resolution.

## D11 — Backup and rollback

- **Decision**: On each VM, create `/var/backups/nginx-<ts>.tar.gz` over
  `/etc/nginx`, download it to `backups/{ip}/`, and verify local existence, non-zero
  size, and checksum before any change. Rollback re-uploads the local archive,
  archives the current config first (`*-pre-rollback`), extracts over `/`, runs
  `nginx -t`, and restarts only if the test passes.
- **Rationale**: The constitution requires a local backup and rollback path; a local
  copy protects against VM loss. Archiving the pre-rollback config makes rollback
  itself reversible.
- **Alternatives considered**:
  - Remote-only backups — rejected: no protection if the VM is lost.
  - etc-keeper/git-managed config — rejected: not present on the fleet.

## D12 — Parallelism and retries

- **Decision**: `concurrent.futures.ThreadPoolExecutor` capped at
  `execution.concurrency` (default 4); per-VM subprocess timeouts; results merged in
  the main thread. Failed execution VMs get exactly one retry round, then `FAILED`.
- **Rationale**: Bounded concurrency matches the spec assumption and keeps per-VM
  logs/state writes race-free. Isolation prevents one VM from blocking the fleet.
- **Alternatives considered**:
  - Unbounded threads/asyncio — rejected: unnecessary complexity and load.
  - GNU `parallel`/`xargs -P` — rejected: weaker structured result collection.

## D13 — Post-upgrade verification semantics

- **Decision**: Verify `nginx -t`, `systemctl is-active nginx`, installed version equals
  candidate, and a local HTTP probe (plus HTTPS when TLS directives are present). Any
  HTTP response proves nginx responds; the status code is recorded and non-2xx/3xx is
  flagged for review. `require_status` can be configured to enforce specific codes.
- **Rationale**: The spec defines this as a smoke test, not application health; upstream
  apps can legitimately return 4xx/5xx while nginx itself is healthy.
- **Alternatives considered**:
  - Require HTTP 200 — rejected: false failures for sites returning redirects/errors.
  - External URL checks — rejected: DNS/firewall variance makes them unreliable.

## D14 — Testing strategy

- **Decision**: `unittest` unit tests for pure logic (version compare, parsers,
  verdict precedence, config/state validation, record rendering, approval guards,
  retry counting) and integration tests that put fake `doctl`/`ssh`/`scp` executables
  on `PATH` with scenario fixtures. Live validation is read-only (`discover`, `survey`)
  plus an operator-gated canary and rollback drill.
- **Rationale**: pytest/ruff/mypy are not installed; adding dependencies would burden
  the operator. Fake executables exercise subprocess boundaries without touching VMs.
- **Alternatives considered**:
  - Add pytest — rejected: unnecessary dependency for this size.
  - Live-only testing — rejected: cannot prove failure paths or safety guards.

## D15 — Secret handling

- **Decision**: SSH access comes from `.personal/ssh.env` (`SSH_USER`, `SSH_KEY`,
  `SSH_PORT`), created once at a GATE, mode `0600`, never committed. Config and state
  store paths only. Logs never print env contents. `doctor` warns if the key file is
  group/world-readable.
- **Rationale**: FR-002/FR-017 and the constitution's operational constraints.
- **Alternatives considered**:
  - Store credentials in `.specific/` — rejected: not a personal/secrets location.
  - Agent/SSH config inheritance only — rejected: not reproducible or auditable.

## D16 — Repository hygiene remediation

- **Decision**: Add `plan/` and `.fleet/` to `.gitignore` and untrack the already
  committed `ip.txt` (`git rm --cached ip.txt`), keeping the working file.
- **Rationale**: IP data must not be committed; the file is currently tracked despite
  being listed in `.gitignore`. `.personal/` and `backups/` are already ignored.
- **Alternatives considered**:
  - Leave `ip.txt` tracked — rejected: violates the constitution and FR-017.

## Resolved unknowns summary

| Technical Context item | Resolution |
|---|---|
| Language/version | Python 3.11+, stdlib + PyYAML (D3) |
| Primary dependencies | OpenSSH client, `doctl`, PyYAML (D3) |
| Storage | JSON state + Markdown records + tarball backups (D5, D11) |
| Testing | `unittest` + fake executables; gated live drills (D14) |
| Target platform | Operator Linux → Debian/Ubuntu VMs over SSH (D3) |
| Project type | Agent Skill + CLI (D1, D2) |
| Performance goals | Bounded pool of 4, timeouts (D12) |
| Constraints | Gated, backed-up, idempotent, secret-free (D4, D7, D11, D15) |
| Scale/scope | 12 VMs, batches of 4, one canary (D12) |
