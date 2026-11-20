# nginx Fleet Upgrade Runbook — DigitalOcean

Upgrade nginx on every DigitalOcean droplet with per-VM evidence, confirmation
gates, and config-backup rollback. Agent-executed; no scripts required. Phase 8
explains how to extend the same flow to other tools.

**Principles**

- Read-only until a GATE approves the change.
- Every decision comes from evidence collected on that VM, never guesses.
- One failed VM is isolated; it never blocks the rest of the fleet.
- `GATE` = stop and wait for explicit user confirmation before continuing.

## 0. Layout & conventions

| Path | Role |
|---|---|
| `.personal/ssh.env` | Fleet SSH access: `SSH_USER`, `SSH_KEY`, `SSH_PORT`. Asked once (GATE), gitignored, `chmod 600`. |
| `ip.txt` | Fleet IP list, one per line (refreshed in Phase 1). |
| `plan/{ip}.md` | Per-VM record: Survey → Plan → Execution result. |
| `backups/{ip}/` | Downloaded copy of each VM's `/etc/nginx` tarball. |

If `SSH_USER` is not `root`, prefix privileged commands with `sudo`.

## 1. Discover (read-only)

```bash
doctl auth list                                                        # context exists?
doctl compute droplet list --format Name,PublicIPv4,Status --no-header
```

- Write the `PublicIPv4` of active droplets to `ip.txt` (one per line, sorted, deduped).
- Diff against the previous `ip.txt` and show added / removed IPs.

## 2. Access preflight

- If `.personal/ssh.env` is missing → **GATE**: ask the user for `SSH_USER`,
  `SSH_KEY` path, `SSH_PORT` (defaults: `root`, `~/.ssh/id_ed25519`, `22`).
  Write `.personal/ssh.env` and `chmod 600`.
- For every IP, in parallel:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=5 -i "$SSH_KEY" -p "$SSH_PORT" \
    "$SSH_USER@$IP" \
  'grep PRETTY /etc/os-release; nginx -v 2>&1; systemctl is-active nginx || true'
```

- Record reachable / unreachable per VM. Unreachable VMs are flagged and
  skipped, not retried blindly.

## 3. Survey per VM (read-only) → `plan/{ip}.md`

Collect per VM:

| Field | How |
|---|---|
| OS | `grep PRETTY /etc/os-release` |
| Installed version | `dpkg-query -W -f='${Version}' nginx` |
| Candidate version | `apt-get update -q` then `apt-cache policy nginx` |
| Package origin | `apt-cache policy nginx` — distro repo vs `nginx.org` vs none (source build) |
| Holds | `apt-mark showhold` |
| Modules | `nginx -V 2>&1` — note third-party / dynamic modules |
| Service | `systemctl is-active nginx; systemctl is-enabled nginx` |
| Server blocks | `grep -rlE 'server\s*\{' /etc/nginx/sites-enabled /etc/nginx/conf.d 2>/dev/null \| wc -l` |
| TLS | presence of `ssl_certificate` directives |
| Config test | `nginx -t` |

Verdict per VM:

- `SKIP` — nginx not installed
- `UP-TO-DATE` — installed version ≥ candidate
- `UPGRADE old → new`
- `BLOCKED` — with reason: `nginx -t` fails, package held, unexpected origin
  (nginx.org repo or source build), third-party module missing from distro repo

Write all evidence and the verdict into `plan/{ip}.md`.

## 4. Review GATE

One summary table across all VMs, grouped by verdict:

| IP | Verdict | Installed | Candidate | Note |
|---|---|---|---|---|

The user confirms the upgrade set (VMs may be deselected). BLOCKED VMs need an
explicit user decision — never auto-fixed.

## 5. Execute — canary, then fleet

Identical per-VM procedure for both rounds. A failure at any step stops that VM
only and marks it FAILED.

1. **Backup** (the rollback depends on it):
   ```bash
   ssh ... 'tar czf /var/backups/nginx-$(date +%s).tar.gz /etc/nginx'
   scp ...:/var/backups/nginx-*.tar.gz backups/{ip}/
   # verify the local file exists and is non-empty — else abort this VM
   ```
2. **Pre-check**: `nginx -t` must pass on the current config.
3. **Upgrade**:
   ```bash
   ssh ... 'DEBIAN_FRONTEND=noninteractive apt-get install --only-upgrade nginx \
       -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold"'
   ```
   Never hangs on modified conffiles: existing config is kept, new upstream
   templates land as `*.dpkg-dist` files.
4. **Verify**: `nginx -t` · `systemctl is-active nginx` · installed version equals
   candidate · `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/`
   (and `https://` when TLS) — record the status codes.
5. **Drift check**:
   `find /etc/nginx \( -name '*.dpkg-dist' -o -name '*.dpkg-new' \)`
   → if found, flag **config needs update** in the record; do not auto-merge.

**Canary**: run the first 2 VMs of the approved set → write results into their
`plan/{ip}.md` → **GATE**: review canary outcome with the user.

**Fleet**: run the remaining VMs in parallel, concurrency capped at ~4
(`xargs -P 4` or per-VM background jobs) with per-VM log lines. Collect failures
and give them one retry round before reporting FAILED.

**Rollback (config-only)** — when a VM fails after upgrade:

```bash
ssh ... 'tar xzf /var/backups/nginx-<ts>.tar.gz -C /'
ssh ... 'nginx -t && systemctl restart nginx'
```

The package intentionally stays at the new version. A package downgrade
(`apt-get install nginx=<old-version>`, if still in the apt cache) is a separate
user-approved decision, out of scope here.

## 6. Report

Final table: IP · old → new · backup path · verify result · drift flags.
Append a summary entry to `LOGS.md`.

## 7. Rollback reference (on demand)

Backups live in two places: `backups/{ip}/` (local) and
`/var/backups/nginx-*.tar.gz` (on each VM). Restore = extract over `/etc/nginx`,
`nginx -t`, restart. Same steps as §5 rollback.

## 8. Extending to another tool

Phases 1–4 are tool-agnostic (discover → access → survey → gate). A new tool
adds a per-tool **playbook** that replaces §5 and §7:

```yaml
package: nginx
config_paths: [/etc/nginx]
precheck: nginx -t
upgrade_cmd: DEBIAN_FRONTEND=noninteractive apt-get install --only-upgrade nginx ...
verify:
  - systemctl is-active nginx
  - curl http://127.0.0.1/
blocked_when:
  - precheck fails
  - package held
  - unexpected package origin
```

## Safety rules

- Read-only until GATE approval; never auto-fix BLOCKED VMs.
- No forced package removal, no `--fix-broken`, no `dist-upgrade`.
- Backup verified before any change to a VM.
- `.personal/` and `backups/` are gitignored and never committed.
