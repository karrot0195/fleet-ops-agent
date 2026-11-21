---
name: nginx-fleet-upgrade
description: Audit, upgrade, and roll back nginx across the DigitalOcean fleet with per-VM evidence, verified config backups, explicit approval gates, and a canary-first rollout. Use when the user asks to audit or upgrade nginx on the fleet, review per-VM upgrade readiness, or roll back a failed nginx upgrade.
---

# nginx Fleet Upgrade

Gated fleet operations: read-only audit first, explicit approval before any change,
verified backup before every upgrade, canary then bounded parallel rollout, and
configuration-only rollback.

## When to use

- The user asks which fleet VMs can upgrade nginx today.
- The user approves an upgrade set and wants it executed with backups.
- A VM failed after an upgrade and its configuration must be restored.
- The user wants a fleet report or a per-VM audit record.
- The user wants VMs moved from distro nginx packages to the official
  nginx.org repository (`--mode migrate`) to reach versions the distro
  does not ship.

## When NOT to use

- Provisioning new VMs, changing application configs, or upgrading non-apt installs.
- Package downgrades (out of scope; configuration rollback only).
- Any VM outside the `ip.txt` inventory.

## Files

| Path | Role |
|---|---|
| `.specific/nginx-fleet.yaml` | Non-secret operator config (`config --init` seeds it). |
| `.personal/ssh.env` | `SSH_USER`, `SSH_KEY`, `SSH_PORT`; mode 0600; never committed. |
| `ip.txt` | Fleet roster, `Name,IP` per line. |
| `plan/{ip}.md` | Per-VM record rendered from state. |
| `backups/{ip}/` | Verified local config archives. |
| `.fleet/state.json` | Run state (source of truth). |
| `.fleet/logs/<run_id>/` | Per-VM command logs. |

Resolve this skill's directory and invoke the CLI by absolute path:
`python3 "$SKILL_DIR/scripts/fleet.py"`.

## Procedure

1. **Preflight** — `doctor`; if `.personal/ssh.env` is missing, GATE: ask for
   `SSH_USER`, `SSH_KEY`, `SSH_PORT`, write the file with mode 0600.
2. **Discover** — `discover`; show added/removed IPs.
3. **Audit** — `survey --all`; every VM gets a verdict and `plan/{ip}.md`. Nothing is
   modified.
4. **Summary GATE** — show the grouped table; ask which `UPGRADE` VMs to include.
   BLOCKED/UNREACHABLE VMs can never be approved.
5. **Canary** — after approval, `execute --phase canary --approve <ip> --yes`.
   Use `--mode migrate` to first bootstrap the upstream nginx.org repo
   (signing key verified against `migration.key_fingerprint`, sources.list.d
   entry with `repo_dist`, apt pinning, `conf.d/default.conf` stub, apt-get
   update), then upgrade from it. Migrate mode approves reachable VMs with a
   healthy nginx install (config test passes, no holds, no third-party
   modules) whose distro codename is in `migration.apply_to_dists`; a
   `BLOCKED` verdict caused only by the distro package origin does not block
   migration because migration replaces the source.
6. **Canary GATE** — show the result; ask proceed or stop. Record with
   `gate --decision proceed|stop`.
7. **Fleet** — `execute --phase fleet --approve <ips> --yes` with bounded concurrency
   and one retry round.
8. **Report** — `report --log` (one appended `LOGS.md` entry).

## Commands

```bash
fleet.py --root . doctor
fleet.py --root . discover [--source doctl|file] [--file PATH]
fleet.py --root . survey --all [--parallel N] | --ip IP [--ip IP]
fleet.py --root . summary
fleet.py --root . execute --phase canary --mode distro|migrate --approve IP[,IP] --yes [--dry-run]
fleet.py --root . gate --decision proceed|stop [--note TEXT]
fleet.py --root . execute --phase fleet --mode distro|migrate --approve IP[,IP] --yes [--dry-run]
fleet.py --root . rollback --ip IP --yes [--dry-run]
fleet.py --root . report [--log]
fleet.py --root . config --init [--force]
```

All commands accept `--json` before the subcommand. Exit codes: `0` success,
`2` config/usage, `3` gate refused, `4` VM failure, `5` preflight/discovery.

## Gates

- No mutation without `--yes` plus an approved set of `UPGRADE` IPs.
- No fleet execution without a recorded canary `proceed`.
- A missing or empty backup aborts that VM before any change.

## Performance notes

- SSH connection multiplexing (`ssh.multiplex`, default on) reuses one authenticated
  connection per VM across the many commands of an execute run (ControlPersist 300 s).
- Verification and drift scanning run as a single remote script per VM during execute.
- Survey retries an unreachable VM once before recording the `UNREACHABLE` verdict.
- Execute saves state and the per-VM plan record as each VM finishes, so an
  interrupted run keeps completed work and re-runs skip `SUCCEEDED` VMs.

## Failure modes

| Failure | Behavior |
|---|---|
| Config missing/invalid | Exit 2 before any network call; run `config --init` |
| SSH env missing | Exit 5; collect credentials at the access GATE |
| `doctl` auth/output unusable | Exit 5 from `doctor`/`discover` |
| VM unreachable | `UNREACHABLE` record with reason after one retry; other VMs continue |
| nginx absent | `SKIP`; no change |
| Config test fails, package held, unexpected origin, third-party module, no candidate | `BLOCKED` with reason; never approvable |
| Non-UPGRADE IP approved | Exit 3 before any VM is contacted |
| Non-migratable IP in `--mode migrate` (wrong distro, unhealthy nginx) | Exit 3 before any VM is contacted |
| Fleet without canary `proceed` | Exit 3 |
| Backup missing/empty, checksum command fails, or local sha256 != remote sha256 | That VM aborts before any change |
| Repo bootstrap fails (key, sources, apt update, nginx.org not active) | VM `FAILED`; no upgrade attempted |
| Upgrade fails | VM `FAILED`; fleet continues; one retry round |
| Verification fails | VM `FAILED`; drift info still recorded |
| Rollback refused (no verified backup, checksum mismatch, not in a failed state) | Exit 4; no VM contacted |
| Rollback precheck fails | No restart; rollback recorded `FAILED` |
| Repeated `report --log` | No duplicate entry; warning emitted |

## Verification

```bash
python3 -m unittest discover -s .agents/skills/nginx-fleet-upgrade/scripts/tests \
  -t .agents/skills/nginx-fleet-upgrade/scripts -v
```

Fixture-based tests cover verdict logic, parsing, ledger/guards, dry runs, canary and
fleet flow, retry-once, rollback, and append-only reporting. Live fleet checks remain
read-only until the operator approves a canary.

## Safety rules

- Read-only until the summary GATE; never auto-fix BLOCKED VMs.
- Preserve local configuration (`--force-confold`); stage upstream templates only.
- Never run `dist-upgrade`, remove packages, or use `--fix-broken`.
  Exception: `--mode migrate` intentionally lets apt replace distro packaging
  (Ubuntu's `nginx-common` is removed and replaced by the monolithic nginx.org
  package) via `migration.upgrade_command`; this is confined to the nginx
  package replacement and logged per VM.
- Configuration-only rollback; the package stays at the new version.
- Never commit credentials, `ip.txt`, `plan/`, `backups/`, or `.fleet/`.
