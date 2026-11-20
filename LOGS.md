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

2026-11-20 13:29: Refactor PLAN.md into fleet upgrade runbook
Rewrote PLAN.md as an agent-executable runbook: phases discover/access/survey/review-GATE/execute/report/rollback, config-only rollback with backups under backups/{ip}/, SSH creds persisted once to .personal/ssh.env, canary-then-parallel execution with capped concurrency, and a per-tool playbook section for extending to other tools.
