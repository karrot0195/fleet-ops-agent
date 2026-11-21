# speckit-implement experience

- **2026-11-20 (001-nginx-fleet-upgrade)**: Implemented the nginx-fleet-upgrade skill
  (12 Python modules, 78 unittest tests, SKILL.md, config/record references). Useful
  findings for future implement runs:
  - The skill lives at `.agents/skills/nginx-fleet-upgrade/` as a real directory;
    `.agents/skills/*` otherwise contains symlinks into the `agent-skills` submodule.
  - Tests run with `python3 -m unittest discover -s tests -t .` from the skill's
    `scripts/` directory, which requires `tests/__init__.py`; multiple `-k` filters
    work with OR semantics.
  - Fake `doctl`/`ssh`/`scp` executables on `PATH` (scenario JSON + command log +
    applied/counter files) exercise real subprocess boundaries without VMs. This made
    gate/retry/rollback flows testable end to end.
  - `write_file` and `chmod` in the same parallel tool batch race: run chmod after the
    files exist.
  - `TEMPLATE` path bug: from `scripts/fleetkit/cli.py`, `parents[2]` is the skill root,
    not `parent.parent`.
  - CLI global flags (`--json`, `--root`) must precede the subcommand; quickstart
    examples and tests use that order.
  - Case-sensitive name sorting reorders `ip.txt` oddly (`prd-REDIS` before `prd-espx`);
    sort inventory case-insensitively for human-stable output.
  - Execution re-checks the remote installed version before backup so a re-run on an
    already-upgraded VM records `SUCCEEDED` without apt/tar (FR-018).
  - Add optional `rollback.error` to the state schema; failure detail needs a home that
    `additionalProperties: false` allows.
  - `git rm --cached ip.txt` plus `plan/` and `.fleet/` ignores satisfy the constitution;
    verify with `git check-ignore` and `git grep` for fleet IPs.
  - Verification recipes registered in `.specific/project.yaml` are test-only, so they
    run without operator SSH credentials; live `doctor`/`survey` stay gated.
  - Post-execution hooks: `.specific/extensions.yml` has `hooks: {}` — nothing to run.
