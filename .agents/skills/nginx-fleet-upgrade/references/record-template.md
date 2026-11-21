# <name> (<ip>)

- Run: `<run_id>`
- Verdict: **<verdict>**
- Reason: <reason or —>
- Surveyed: <timestamp or —>

## Survey evidence

| Field | Value |
|---|---|
| OS | ... |
| nginx binary | present / absent |
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

## Connectivity

- Result: unreachable
- Reason: ...
- Evidence: none collected

## Execution

- Phase: canary / fleet / —
- State: ... / —
- Old → new: ... / —
- Attempts: ... / —
- Backup: `<path>` (verified, <size> bytes, sha256 `<hash>`) / —
- Steps: ...

## Verification

- Config test: ...
- Service active: ...
- Version matches candidate: ...
- HTTP status: ...
- HTTPS status: ...

## Drift

- none

## Rollback

- State: ...
- Pre-rollback archive: ...
- Config test after restore: ...
- Service active after restore: ...
- Package version: unchanged
