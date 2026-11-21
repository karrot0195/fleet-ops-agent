# LOGS

Append-only change log. `speckit-log` appends one entry per change; never rewrite
or reorder existing entries.

Each entry is a heading line with a timestamp and a short title, followed by a
one-line summary:

```text
YYYY-MM-DD HH:MM: <short title>
<one-line summary>
```

## Entries

2026-11-21 12:00: User Story 4 — Organized Output: Reports and Logging
Report rendering with per-VM before/after tables, wiki report output, LOGS.md append with dedup guard, and record template created; report unit tests pass.


2026-11-21 12:00: User Story 3 — Gated Canary Rollout and Rollback
Execute engine with canary/serial fleet rollout, retry-once, verify approvals guard, full rollback (config + package restore), migration mode, and gate decision recording; execute and rollback tests added.


2026-11-21 12:00: User Story 2 — Choose a Provider
Doctl, vultr-cli, and manual providers implemented with discovery, auth check, reconciliation, and inventory file I/O; provider config templates and unit tests added.


2026-11-20 13:29: Refactor PLAN.md into fleet upgrade runbook
Rewrote PLAN.md as an agent-executable runbook: phases discover/access/survey/review-GATE/execute/report/rollback, config-only rollback with backups under backups/{ip}/, SSH creds persisted once to .personal/ssh.env, canary-then-parallel execution with capped concurrency, and a per-tool playbook section for extending to other tools.

2026-11-20 14:17: Read-only fleet audit
Implemented discover/survey/summary in the nginx-fleet-upgrade skill: doctl inventory reconciliation, per-VM evidence, verdict precedence, and plan/{ip}.md records; 28 audit tests pass.

2026-11-20 14:18: Gated canary and fleet rollout
Implemented fail-closed approval guards, verified config backups, first-approved canary, recorded proceed/stop gate, bounded concurrency, one retry, and post-upgrade verification/drift flags; 19 rollout tests pass.

2026-11-20 14:19: Configuration-only rollback
Implemented rollback from a verified local backup with a pre-rollback archive, precheck-gated restart, package version left unchanged, and per-VM record updates; 6 rollback tests pass.

2026-11-20 14:20: Fleet report and audit trail
Implemented the final per-VM report and one-shot append to LOGS.md with a duplicate guard; 4 report tests pass and the full suite is 78 tests.

2026-11-20 16:54: Optimize fleet skill execution safety and speed
Per-future state/plan persistence for crash-safe resume, SSHError containment at backup/rollback transfers, survey/report gate on actually-loaded state (race fix), remote-vs-local backup sha256 verification, SSH ControlMaster multiplexing (ssh.multiplex), batched verify+drift remote script, survey retry before UNREACHABLE, newline-safe table cells, candidate-aware apt-policy origin, and shared-helper cleanups; 102 tests pass.

2026-11-21 10:16: nginx fleet upgrade 20261120T090606Z-50dfb9
Processed 5 VM(s): 4 succeeded, 1 failed, 0 rolled back; drift flags on 5 VM(s).

## 2026-11-21 12:00 — User Story 1 — Register a New Tool (MVP)

Tool registration, config validation, verdict computation, survey flow, and CLI commands implemented. 67 tests pass covering all verdict scenarios, tool registry, providers, execute/rollback, and report generation.

---


## Fleet Report: nginx

Run completed with 1 records.

