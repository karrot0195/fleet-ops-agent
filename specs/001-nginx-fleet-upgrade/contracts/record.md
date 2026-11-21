# Record Contract: `plan/{ip}.md`

One file per inventory VM, including unreachable VMs. Rendered deterministically from
state; re-rendering an IP replaces only that file. Records are never merged across VMs
(FR-006). All values come from collected evidence; unknowns render as `unknown`, never
as guesses.

## Required structure

```markdown
# <name> (<ip>)

- Run: `<run_id>`
- Verdict: **<SKIP|UP-TO-DATE|UPGRADE|BLOCKED|UNREACHABLE>**
- Reason: <reason or "—">
- Surveyed: <ISO-8601 UTC or "—">

## Survey evidence

| Field | Value |
|---|---|
| OS | ... |
| Installed version | ... |
| Candidate version | ... |
| Package origin | ... |
| Held packages | ... |
| Static modules | ... |
| Dynamic modules | ... |
| Third-party modules | ... |
| Service active / enabled | ... |
| TLS present | ... |
| Server blocks | ... |
| Config test | pass / fail |

Omit the evidence table only for `UNREACHABLE`; then include:

## Connectivity

- Result: unreachable
- Reason: <connectivity failure reason>
- Evidence: none collected

## Execution

- Phase: canary | fleet | —
- State: ... | —
- Old → new: ... | —
- Attempts: ... | —
- Backup: `<local_path>` (verified, <size> bytes, sha256 `<hash>`) | —
- Steps: backup / precheck / upgrade / verify / drift — each `ok|failed: detail`

## Verification

- Config test: pass / fail / not run
- Service active: yes / no / not run
- Version matches candidate: yes / no / not run
- HTTP status: <code> / not run
- HTTPS status: <code> / not run / not applicable

## Drift

- <pattern> — `<path>` — manual review required
- or `none`

## Rollback

- State: succeeded / failed / not requested
- Pre-rollback archive: `<path>` / —
- Config test after restore: pass / fail / —
- Service active after restore: yes / no / —
- Package version: unchanged at `<new_version>` (never downgraded)
```

## Rules

- Headings and section order are fixed; empty sections render `—` or `none`, never
  disappear (except the survey table for `UNREACHABLE`, replaced by `Connectivity`).
- `BLOCKED` and `UNREACHABLE` records must include a non-empty `Reason`.
- `UNREACHABLE` records carry no survey evidence and no execution data.
- Backups named in the record must match an existing, verified local archive.
- No credentials, key contents, or `.personal/` values appear anywhere.
- Timestamps use UTC ISO-8601; version strings are verbatim Debian versions.
- Drift entries are informational only: nothing is auto-merged or auto-fixed.
