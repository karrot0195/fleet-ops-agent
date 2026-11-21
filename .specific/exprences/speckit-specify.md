# speckit-specify — Experience

## 2026-11-20 — specs/001-nginx-fleet-upgrade
- Input was `@PLAN.md` (an ops runbook), not a prose feature request: the spec had to be translated from HOW (commands) to WHAT/WHY (operator outcomes). Worked well: map runbook phases → user stories (audit → gated rollout → rollback → report), keep command-level detail out of the spec.
- Template resolution: project-local `.harness/templates/spec-template.md` wins over `agent-skills/.harness/templates/`; skill dir itself bundles no template.
- `.harness/init-options.json` `feature_numbering: sequential` → scan `specs/` for next NNN (no specs dir → 001).
- This repo's constitution principles (safety-first, gates, per-VM traceability, idempotency) map directly onto FRs — reuse them as the FR backbone for future specs here.
- Zero [NEEDS CLARIFICATION] markers: when the input doc is detailed, prefer Assumptions over clarification questions.
- Remember: write `.harness/feature.json` with the resolved feature dir so downstream speckit skills can find it.
