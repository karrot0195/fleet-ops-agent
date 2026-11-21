# Quickstart Validation: nginx Fleet Upgrade

Runnable validation scenarios for the `nginx-fleet-upgrade` skill. Commands assume
the repository root; `fleet.py` is shorthand for
`python3 .agents/skills/nginx-fleet-upgrade/scripts/fleet.py`. Contracts are referenced, not
duplicated: [CLI](./contracts/cli.md), [config schema](./contracts/config.schema.yaml),
[state schema](./contracts/state.schema.json), [record format](./contracts/record.md).

**Safety**: scenarios 1–3 are offline/read-only. Scenarios 5–7 mutate VMs and require
the operator GATE and `--yes`. Never point the mutation scenarios at production VMs
before the canary drill is approved.

## Prerequisites

- Python 3.11+ (host: 3.14.10), PyYAML, OpenSSH client, `doctl` authenticated.
- Operator access to the fleet in `ip.txt` and a usable SSH key.
- `.personal/ssh.env` exists (`SSH_USER`, `SSH_KEY`, `SSH_PORT`, mode `0600`).
- `plan/`, `backups/`, `.fleet/`, and `ip.txt` are not committed (constitution).

## 1. Unit and integration suite (offline)

```bash
cd .agents/skills/nginx-fleet-upgrade/scripts
python3 -m compileall -q fleet.py fleetkit
python3 -m unittest discover -s tests -t . -v
```

Expected: all tests pass. The suite covers Debian version comparison, `apt-cache
policy`/`nginx -V` parsing, verdict precedence, inventory reconciliation, config/state
validation, record rendering, approval guards, backup verification abort, retry-once,
concurrency cap, and append-only logging. Integration tests use fake
`doctl`/`ssh`/`scp` executables from `tests/fixtures/bin`; no network is used.

Maps to: SC-001, SC-004, SC-007 (deterministic portions).

## 2. Preflight and configuration (read-only, no VMs)

```bash
fleet.py --root . doctor
fleet.py --root . config --init          # only if .specific/nginx-fleet.yaml is absent
fleet.py --root . doctor
```

Expected: `doctor` validates `.specific/nginx-fleet.yaml` against the schema, confirms
`ssh`/`scp`/`doctl` and the SSH env file, and exits 0. `config --init` refuses to
overwrite an existing config.

Maps to: FR-002, FR-017.

## 3. Discover and reconcile (read-only)

```bash
fleet.py --root . discover --json | tee /tmp/discover.json
cat ip.txt
```

Expected: `ip.txt` contains `Name,IP` lines sorted by name and deduped by IP; the JSON
reports `added` and `removed` versus the previous snapshot. No VM is contacted.
Re-running produces no changes.

Maps to: FR-001, SC-007.

## 4. Audit the fleet (read-only)

```bash
fleet.py --root . survey --all --json | tee /tmp/survey.json
fleet.py --root . summary
ls plan/
```

Expected: every inventory IP has `plan/{ip}.md` and exactly one verdict. Reachable VMs
show the full evidence table; `UNREACHABLE` records show `Connectivity` and no
evidence; every `BLOCKED` record has a reason. The summary groups VMs by verdict and
lists only `UPGRADE` VMs as eligible. Spot-check one record against the
[record contract](./contracts/record.md). Confirm no VM was modified (`systemctl`
status and `nginx -t` timestamps unchanged).

Maps to: FR-003, FR-004, FR-005, FR-006, SC-001.

## 5. Approval gate and dry run (no mutation)

```bash
fleet.py --root . summary --json          # build the GATE question from `eligible`
fleet.py --root . execute --phase canary --approve <first-ip> --dry-run --json
```

Expected: `summary --json` exposes `eligible`; the dry run prints the exact per-VM
steps (backup → precheck → upgrade → verify → drift) and changes nothing. Attempting
to approve a `BLOCKED`/`UNREACHABLE`/`SKIP`/`UP-TO-DATE` IP exits 3 with no mutation.

Maps to: FR-007, FR-008, SC-002, SC-005.

## 6. Canary, gate, and fleet rollout (mutating; operator-approved)

After the operator explicitly approves the canary IP:

```bash
fleet.py --root . execute --phase canary --approve <canary-ip> --yes
fleet.py --root . summary                # show canary outcome
fleet.py --root . gate --decision proceed --note "canary healthy"
fleet.py --root . execute --phase fleet --approve <ip,ip,...> --yes
```

Expected:

- Before any change, `backups/{ip}/nginx-*.tar.gz` exists, is non-empty, and the
  checksum is verified; a missing/empty backup aborts that VM with no change.
- The canary record shows old → new, verification results, and any drift flags.
- `execute --phase fleet` refuses (exit 3) without a recorded `proceed`.
- Fleet VMs run with bounded concurrency; a failing VM is retried exactly once and
  isolated from the rest.
- Choosing `stop` at the gate ends the run with no further upgrades.

Maps to: FR-009, FR-010, FR-011, FR-012, FR-013, FR-014, SC-003, SC-004.

## 7. Rollback drill (mutating; operator-approved)

On the canary (or a disposable VM) after a simulated or real failure:

```bash
fleet.py --root . rollback --ip <canary-ip> --dry-run
fleet.py --root . rollback --ip <canary-ip> --yes
```

Expected: the local verified backup is restored, the current config is archived as
`*-pre-rollback`, `nginx -t` passes, the service is running, the package remains at the
new version, and `plan/{ip}.md` records the rollback.

Maps to: FR-015, SC-003.

## 8. Report and audit trail

```bash
fleet.py --root . report
fleet.py --root . report --log
tail -n 4 LOGS.md
fleet.py --root . report --log   # repeat: no duplicate entry
git diff --stat LOGS.md
```

Expected: the report lists every processed VM with old → new, backup location,
verification result, and drift flags. `--log` appends exactly one dated entry; a repeat
does not duplicate it; prior entries are untouched.

Maps to: FR-016, SC-006.

## Re-run / idempotency check

```bash
fleet.py --root . survey --all
fleet.py --root . execute --phase canary --approve <already-upgraded-ip> --yes
```

Expected: the re-audit changes nothing; the already-upgraded VM is recorded
`UP-TO-DATE` and no upgrade command runs.

Maps to: FR-018, SC-007.

## Failure-path checks (offline fixtures)

| Scenario | Expected |
|---|---|
| `ssh` unreachable for one fixture VM | `UNREACHABLE` record with reason; other VMs surveyed |
| `nginx -t` fails | `BLOCKED` with config-test reason; never approved |
| held `nginx` package | `BLOCKED` with held-package reason |
| candidate version `(none)` | `BLOCKED` with "no candidate version determined" |
| backup file empty after download | VM aborts before upgrade; recorded failure |
| canary failure | gate cannot `proceed` to fleet; operator may record `stop` |
| fleet VM fails then succeeds on retry | one retry only; final `SUCCEEDED` |
| HTTP 502 from upstream | recorded status; VM still verified if nginx responds |

## Troubleshooting

- `exit 2`: invalid config/flags — run `doctor` and check
  [config.schema.yaml](./contracts/config.schema.yaml).
- `exit 3`: a gate was not satisfied — re-read the approval/gate requirements in
  [cli.md](./contracts/cli.md); nothing was mutated.
- `exit 4`: inspect `.fleet/logs/<run_id>/<ip>.log` and the VM's `plan/{ip}.md`; roll
  back if the VM failed after the upgrade.
- `exit 5`: `doctl` auth, SSH env file, or reachability problem — fix access before
  re-running.
