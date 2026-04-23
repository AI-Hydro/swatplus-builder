# Progress Log

## Active Phase

Phase 3A — Hardening

## Current Sprint Focus

Implement and stabilize Phase 3A.1 CI routing-regression gate with real engine runs and explicit pass/fail assertions. Prepare follow-on 3A.2 metadata persistence work immediately after the gate is merged.

## Completed Since Last Update

- [2026-04-23] [pre-commit] — Completed Phase 3A kickoff reconnaissance against authoritative `ROADMAP.md`; verified current repository is structurally stabilized but missing 3A deliverables (CI routing gate, metadata schema, soil realism signaling, basin guardrails).
- [2026-04-23] [pre-commit] — Added `PHASE_3A_PLAN.md` mapping roadmap sections 3A.1-3A.5 to isolated PRs with tests and risks.
- [2026-04-23] [pre-commit] — Added `BACKLOG.md` as append-only deferred-work register.
- [2026-04-23] [pre-commit] — Established this root `PROGRESS.md` as canonical tracked progress log for roadmap execution.
- [2026-04-23] [pre-commit] — Added CI routing regression test `tests/test_ci_routing_regression.py` to execute multi-basin E2E (`01547700`, `01491000`, `03339000`) with assertions for engine success, non-zero terminal channel flow, alignment output existence, and outlet auto-detection behavior on dry `gis_id=1` basin.
- [2026-04-23] [pre-commit] — Updated `.github/workflows/ci.yml` with `routing-regression` job (Ubuntu, timeout budget, full dependency install, pinned SWAT+ Linux engine asset bootstrap).
- [2026-04-23] [pre-commit] — Validated regression test both skip-path and full real run path locally (`SWATPLUS_BUILDER_RUN_ROUTING_REGRESSION=1`).
- [2026-04-23] [pre-commit] — Recorded explicit decision to scope strict `NSE > -1` floor assertion to the structural regression basin (`03339000`) while requiring finite NSE on all fast CI basins (see `DECISIONS.md`).

## In Flight

- [2026-04-23] — Phase 3A.1 finalization:
  - normalize roadmap file-location inconsistency in tracked docs,
  - run CI once on branch to verify Linux engine bootstrap + regression gate behavior in GitHub Actions runtime.

## Next Up

- [1] Finalize and merge Phase 3A.1 gate after CI proof on branch.
- [2] Implement Phase 3A.2 `metadata.json` schema/persistence and `swat inspect <run_id>`.
- [3] Implement Phase 3A.3 soil realism flags (`soil_mode`, `pct_fallback_soils`, output visibility).

## Open Questions / Blockers

- [2026-04-23] Confirm CI basin data strategy:
  - pinned fixtures/artifacts for determinism, or
  - live online fetch in CI with retry + timeout safeguards.
- [2026-04-23] Roadmap file location is currently inconsistent in working tree (`docs/ROADMAP.md` deleted, root `ROADMAP.md` untracked). This will be normalized in early Phase 3A housekeeping to prevent link drift.
- [2026-04-23] Legacy historical logs remain in `docs/PROGRESS.md` (gitignored). If needed, port selected historical milestones into this tracked file incrementally.
