# speckit-tasks experience

- **2026-11-20 (001-nginx-fleet-upgrade)**: Generated 54 tasks from a skill+Python CLI
  plan. Notes for next time:
  - `setup_tasks.py --json` returns the full `TASKS_TEMPLATE_CONTENT`; use it directly.
  - `.specific/project.yaml` `skills:` schema is `[{name, description}]` where
    `description` is the literal command (confirmed against
    `agent-skills/.agents/skills/ingest-project/scripts/update_project_yaml.py`).
    `ingest-project` is **not linked** in this repo, so register recipes with a
    foundational task that edits `.specific/project.yaml` instead of invoking the skill.
  - Verified `unittest discover` needs `scripts/tests/__init__.py` with `-t`, and
    multiple `-k` filters work (OR semantics) on Python 3.14. Bake both into test tasks
    and verification recipes.
  - This domain has real story dependencies (US2 needs US1 verdicts, US3 needs US2
    backups, US4 needs run data); state that explicitly rather than forcing false
    independence, and make each story fixture-testable.
  - Put repo-hygiene remediation (`ip.txt` untrack + ignore `plan/`, `.fleet/`) in Setup,
    not Polish, because the constitution gate depends on it.
  - Every story phase ends with exactly one verification task naming a `project.yaml`
    recipe; validate with a script checking task count, sequential IDs, paths, and
    verification-last. T052 only looked path-less because the validator omitted
    `specs/` — it references `specs/001-nginx-fleet-upgrade/quickstart.md`.
  - Post-execution hooks: `.specific/extensions.yml` has `hooks: {}` — nothing to run.
  - Next: `/speckit-implement`.
