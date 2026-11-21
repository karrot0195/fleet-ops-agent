# nginx-fleet-upgrade — Experience

## 2026-11-20 — first live audit + verdict parse-bug fix
- Access GATE: collected SSH_USER/SSH_KEY/SSH_PORT once, wrote `.personal/ssh.env`
  (mode 0600); `doctor` passed after. SSH key must exist before doctor passes.
- `survey --all` exit 5 "no inventory captured" right after `discover`: state race —
  rerunning `discover --json` (or just retrying `survey`) resolves it.
- Parse bug (fixed): `dpkg-query -W -f='${Version}'` prints NO trailing newline, so
  the `###POLICY` marker glued onto the installed-version line; parse_sections lost
  candidate/origin → false `BLOCKED: unexpected package source: unknown`. Fix: add
  `echo` after the version query in `evidence_script` (survey.py). Verified: preprod
  VM re-surveyed → clean UP-TO-DATE record; 78 tests still pass.
- Verdict reality check on this fleet: preprod-widget-xxx (128.199.149.51) is
  UP-TO-DATE (archive.ubuntu.com); 5 VMs genuinely BLOCKED — origin
  `mirrors.digitalocean.com` not in `allowed_origin_patterns` (operator decision to
  allowlist, never auto-fix); 4 SKIP (no nginx); prd-widget-6 UNREACHABLE
  (publickey denied for root).
- Gate behavior confirmed in code: `validate_approvals` refuses non-UPGRADE IPs
  before contacting any VM, so an UP-TO-DATE VM cannot be canaried.
- Summary/plan tables render raw multi-line POLICY blobs into one cell when evidence
  is stale/corrupt — a glued-marker symptom; fresh survey output renders cleanly.

## 2026-11-21 — first live migrate run + HTTP probe fallback fix
- Live migrate run: 4 questing-distro VMs migrated (1.28.0→1.30.7), 4 blocked by
  unsupported distro (bionic/mantic), 2 skip (no nginx). upload-proxy-01 flagged
  FAILED by tool but verified healthy on :5000 after manual SSH check.
- **Bug**: verification marked upload-proxy-01 FAILED because HTTP probe checked port
  80 where nothing listened; VM was a reverse proxy on :5000. Config test, service,
  version all fine — just wrong listen port for probe.
- **Fix**: `verify_script()` now scans `/etc/nginx/sites-enabled/default` and other
  config paths for `listen <port>` directives via grep. When initial HTTP probe returns
  `000` (not a valid status code), it probes each discovered port automatically, picks
  the first one returning a valid HTTP status, and records which port was used in
  `verification.http_probed_port` / `http_probe_fallback`. Affects execute.py: verify_script(),
  verify_and_drift(). All 102 tests still pass.

## 2026-11-20 — optimization round: persistence, checksums, multiplexing
- Code audit of the skill surfaced 20+ issues; implemented the high-impact set:
  R1 per-future state+plan persistence in execute (crash-safe resume), R2 SSHError
  containment at backup download / rollback upload (one scp timeout no longer aborts
  the whole run), R3 survey/report now gate on `StateStore.loaded` (no more
  existence-probe TOCTOU; report before discover exits 5 instead of fabricating
  state), R4 backup sha256 compared remote-vs-local (+ rollback re-verifies local
  digest), P1 SSH ControlMaster/ControlPersist multiplexing (`ssh.multiplex`,
  sockets under $TMPDIR/fleet-ssh-$UID), P2 verify+drift batched into one
  `###PRECHECK`-marker remote script, R5 survey retries once before UNREACHABLE,
  U1 newline-safe table cells (`records.clean_cell` shared by survey/records/report),
  U2 `[i/n] ip: STATE` stderr progress lines, Q3 `parse_apt_policy` origin now
  candidate-aware (verdict `_version_table_origin`; migration.candidate_origin
  delegates), Q-items (run_vm `_fail` helper, utcnow single-sourced in state.py,
  `_ALLOWED` derived from DEFAULTS, dead `probe()`/digest-len checks removed,
  rollback preconditions raise RollbackError → exit 4, not 3).
- Fixture trap: fake ssh picked `target = first arg containing "@"` — the new
  ControlPath option (`%r@%h-%p`) also contains "@", so the fixture matched the mux
  template instead of user@ip and every VM came back empty-evidence BLOCKED. Fix:
  skip args containing `%` (the ControlPath token). Any future ssh option with "@" or
  "%" must keep the fixture's target detection intact.
- Fixture must also answer the new `sha256sum` remote command and the `###PRECHECK`
  verify script (branch placed BEFORE the generic `systemctl is-active`/`nginx -t`
  substring branches, which a batched script would otherwise hit first).
- Candidate-aware origin required a fixture policy() change too: emit a candidate
  version-table row (real apt-cache policy always has one); without it origin
  fell back to installed and worked, but the new test pins the candidate path.
- Rollback exit-code change is deliberate: operational preconditions (no verified
  backup, checksum mismatch, not-failed) now exit 4 (VM failure); 3 stays
  gate-refused. test_rollback updated accordingly.
- 102 tests green (`python3 -m unittest discover -s tests -t .` from scripts/).
  SKILL.md gained a "Performance notes" section and updated failure-mode rows.
