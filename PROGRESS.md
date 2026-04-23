# Progress Log

## Active Phase

Phase 3A — Hardening

## Current Sprint Focus

Kick off Phase 3A execution discipline and establish mergeable implementation plan before touching runtime behavior. Immediate focus is Phase 3A.1 CI routing-regression gate, then 3A.2 metadata persistence, then 3A.3 soil realism flags.

## Completed Since Last Update

- [2026-04-23] [pre-commit] — Completed Phase 3A kickoff reconnaissance against authoritative `ROADMAP.md`; verified current repository is structurally stabilized but missing 3A deliverables (CI routing gate, metadata schema, soil realism signaling, basin guardrails).
- [2026-04-23] [pre-commit] — Added `PHASE_3A_PLAN.md` mapping roadmap sections 3A.1-3A.5 to isolated PRs with tests and risks.
- [2026-04-23] [pre-commit] — Added `BACKLOG.md` as append-only deferred-work register.
- [2026-04-23] [pre-commit] — Established this root `PROGRESS.md` as canonical tracked progress log for roadmap execution.

## In Flight

- [2026-04-23] — Phase 3A.1 implementation prep:
  - define 2-3 CI representative basins,
  - implement routing-regression assertions and timeout budget,
  - finalize CI strategy for pinned vs live input data.

## Next Up

- [1] Implement Phase 3A.1 CI Routing Regression Gate and wire into GitHub Actions.
- [2] Implement Phase 3A.2 `metadata.json` schema/persistence and `swat inspect <run_id>`.
- [3] Implement Phase 3A.3 soil realism flags (`soil_mode`, `pct_fallback_soils`, output visibility).

## Open Questions / Blockers

- [2026-04-23] Confirm CI basin data strategy:
  - pinned fixtures/artifacts for determinism, or
  - live online fetch in CI with retry + timeout safeguards.
- [2026-04-23] Roadmap file location is currently inconsistent in working tree (`docs/ROADMAP.md` deleted, root `ROADMAP.md` untracked). This will be normalized in early Phase 3A housekeeping to prevent link drift.
- [2026-04-23] Legacy historical logs remain in `docs/PROGRESS.md` (gitignored). If needed, port selected historical milestones into this tracked file incrementally.

