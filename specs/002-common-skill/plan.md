# Implementation Plan: Common Fleet Upgrade Skill

**Branch**: `002-common-skill` | **Date**: 2026-11-21 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-common-skill/spec.md`

## Summary

Migrate the nginx-specific fleet upgrade skill into a generic, extensible common skill that supports pluggable discovery providers (doctl, vultr-cli, manual, ...) and pluggable tool registrations (nginx, docker, ...). Each tool and provider is configured via `.specific/{name}.yaml`. The core audit → gate → canary → serial rollout → rollback flow remains, but is now parameterized per tool. All sensitive data stays in `.personal/`, reports go to `wiki/`, and the existing nginx-fleet-upgrade skill remains functional during transition.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: PyYAML (config parsing), argparse (CLI), subprocess (SSH, provider CLIs), json (state), hashlib (backup verification)

**Storage**: YAML config files (`.specific/{tool}.yaml`, `.specific/{provider}.yaml`), JSON state (`.fleet/state.json`), Markdown reports (`wiki/`, `LOGS.md`), local backup archives (`backups/{ip}/`)

**Testing**: unittest (stdlib), fixture-based tests with mock SSH/provider CLIs

**Target Platform**: Linux server (operator workstation SSH-ing into fleet VMs running Debian/Ubuntu)

**Project Type**: CLI skill (Command Code agent skill)

**Performance Goals**: Audit/survey of 100 VMs within 10% of current nginx skill; serial fleet execution (one VM at a time) for safety

**Constraints**: Serial execution post-canary (one VM at a time); full rollback (package + config); zero credentials in version control; all mutations behind explicit approval gates

**Scale/Scope**: 10-100 VMs per fleet; 2+ concurrent tools supported; 3+ discovery providers

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| Safety First (NON-NEGOTIABLE) | PASS | Verified backup before every change; full rollback (package + config) restores exact pre-upgrade state; rollback path exists before execution starts |
| Explicit Confirmation Gates | PASS | Summary GATE + canary GATE preserved; `--yes` flag required for all mutations; per-VM plan shown before approval |
| Per-VM Traceability | PASS | `plan/{ip}.md` records maintained per tool; state.json tracks per-VM per-tool records |
| Change Only What Is Needed | PASS | Config updates justified by audit; minimal diffs; serial execution limits blast radius |
| Scripted and Idempotent | PASS | All steps reproducible; re-run yields UP-TO-DATE for already-upgraded VMs; idempotent by design |

**Post-design re-check**: All principles still pass. The refactored architecture preserves every safety guarantee while generalizing the tool and provider dimensions.

## Project Structure

### Documentation (this feature)

```text
specs/002-common-skill/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── provider-interface.md
│   ├── tool-registry.md
│   └── cli-commands.md
└── tasks.md             # Phase 2 output (NOT created by plan)
```

### Source Code (repository root)

```text
.agents/skills/fleet-upgrade/
├── SKILL.md
├── references/
│   ├── tool-config.template.yaml
│   └── provider-config.template.yaml
└── scripts/
    ├── fleet.py                    # CLI entry point
    └── fleetkit/
        ├── __init__.py
        ├── cli.py                  # Argument parsing, command dispatch
        ├── config.py               # Config loading, validation, tool+provider resolution
        ├── providers/
        │   ├── __init__.py         # Provider base class, registry loader
        │   ├── base.py             # Abstract provider interface
        │   ├── doctl.py            # DigitalOcean provider
        │   ├── vultr.py            # Vultr provider
        │   └── manual.py           # File-based manual inventory
        ├── tools/
        │   ├── __init__.py         # Tool registry loader
        │   └── registry.py         # Tool config loading, validation
        ├── inventory.py            # Reconciliation, IP file I/O (provider-agnostic)
        ├── survey.py               # Read-only audit (tool-aware verdicts)
        ├── verdict.py              # Verdict logic (tool-parameterized)
        ├── execute.py              # Canary + fleet execution (tool-parameterized)
        ├── backup.py               # Config backup + verification
        ├── rollback.py             # Full rollback: package + config
        ├── ssh.py                  # SSH client, multiplexing
        ├── state.py                # State store (JSON)
        ├── records.py              # Per-VM record rendering
        ├── report.py               # Report generation, wiki output
        └── migration.py            # Optional migration mode (tool-specific)

tests/
├── contract/
│   ├── test_provider_interface.py
│   └── test_tool_registry.py
├── integration/
│   └── test_e2e_flow.py
└── unit/
    ├── test_config.py
    ├── test_verdict.py
    ├── test_survey.py
    ├── test_execute.py
    ├── test_rollback.py
    ├── test_inventory.py
    ├── test_report.py
    ├── test_state.py
    └── test_records.py
```

**Structure Decision**: Single skill directory (`.agents/skills/fleet-upgrade/`) with internal modular separation between providers and tools. This mirrors the existing nginx-fleet-upgrade structure but adds `providers/` and `tools/` subpackages for extensibility. Tests split into contract/integration/unit to match the project's verification commands in `project.yaml`.

## Complexity Tracking

> No constitution violations to justify.
