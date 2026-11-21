# speckit-plan experience

- **2026-11-20 (001-nginx-fleet-upgrade)**: Planned an ops/runbook feature where the
  deliverable was ambiguous. Asked one focused question; the operator chose **Agent
  Skill + Python scripts**, confirming a skill-bundled CLI over documented commands.
  Key findings and decisions:
  - `.agents/skills/*` are symlinks into the `agent-skills` submodule; create
    project-specific skills as **real directories** under `.agents/skills/` so the
    shared submodule is not modified. `server-deploy` is the local pattern to copy
    (SKILL.md + `scripts/*.py` + `.specific/*.yaml` config).
  - `setup_plan.py` copies `plan-template.md` over `plan.md`; the template has no
    phase checklist, so the plan itself must add coverage mapping and post-design
    re-check.
  - Resolved all Technical Context unknowns in Phase 0 rather than leaving markers:
    Python 3.11+ stdlib + PyYAML; subprocess `ssh`/`scp`/`doctl` (no paramiko);
    `unittest` only (pytest/ruff/mypy absent); JSON state as source of truth with
    deterministic Markdown records.
  - Verdict precedence is a real design decision: `UNREACHABLE → SKIP → BLOCKED →
    UP-TO-DATE → UPGRADE` so block conditions are never hidden by a current version.
    Document it in the plan, data model, and tests.
  - Gate model must be non-interactive for agents: explicit `--approve`/`--yes` flags
    plus a recorded `gate --decision proceed|stop`, validated fail-closed before any
    mutation.
  - Constitution gate surfaced a repo violation: `ip.txt` is tracked despite
    `.gitignore`; add `plan/` and `.fleet/` ignores and `git rm --cached ip.txt` as a
    task. Mark the gate "PASS contingent on remediation", not a design violation.
  - Validated generated artifacts by parsing the YAML/JSON schemas and grepping for
    leftover template placeholders. `.specific/extensions.yml` had `hooks: {}` — no
    pre/post hooks to dispatch.
  - Next: `/speckit-tasks`.
