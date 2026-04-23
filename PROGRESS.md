# Progress Log

## Active Phase

Phase 3A — Hardening

## Current Sprint Focus

Complete Phase 3A.3 soil realism flags end-to-end (metadata, warnings, figure annotations, docs), then move to Phase 3A.4 large-basin guardrails.

## Completed Since Last Update

- [2026-04-23] [pre-commit] — Completed Phase 3A kickoff reconnaissance against authoritative `ROADMAP.md`; verified current repository is structurally stabilized but missing 3A deliverables (CI routing gate, metadata schema, soil realism signaling, basin guardrails).
- [2026-04-23] [pre-commit] — Added `PHASE_3A_PLAN.md` mapping roadmap sections 3A.1-3A.5 to isolated PRs with tests and risks.
- [2026-04-23] [pre-commit] — Added `BACKLOG.md` as append-only deferred-work register.
- [2026-04-23] [pre-commit] — Established this root `PROGRESS.md` as canonical tracked progress log for roadmap execution.
- [2026-04-23] [pre-commit] — Added CI routing regression test `tests/test_ci_routing_regression.py` to execute multi-basin E2E (`01547700`, `01491000`, `03339000`) with assertions for engine success, non-zero terminal channel flow, alignment output existence, and outlet auto-detection behavior on dry `gis_id=1` basin.
- [2026-04-23] [pre-commit] — Updated `.github/workflows/ci.yml` with `routing-regression` job (Ubuntu, timeout budget, full dependency install, pinned SWAT+ Linux engine asset bootstrap).
- [2026-04-23] [pre-commit] — Validated regression test both skip-path and full real run path locally (`SWATPLUS_BUILDER_RUN_ROUTING_REGRESSION=1`).
- [2026-04-23] [pre-commit] — Recorded explicit decision to scope strict `NSE > -1` floor assertion to the structural regression basin (`03339000`) while requiring finite NSE on all fast CI basins (see `DECISIONS.md`).
- [2026-04-23] [pre-commit] — Implemented typed run metadata schema and helpers in `src/swatplus_builder/output/metadata.py`.
- [2026-04-23] [pre-commit] — Extended `evaluate_run` with optional diagnostics return (`requested_outlet_gis_id`, `selected_outlet_gis_id`, `outlet_autodetected`, `outlet_selection_reason`, `sim_source_file`) while preserving backward compatibility.
- [2026-04-23] [pre-commit] — Added `swat inspect <run_path>` command to print `metadata.json`.
- [2026-04-23] [pre-commit] — Updated `examples/real_basin_marsh_creek.py` to persist `metadata.json` on successful runs with outlet diagnostics, soil mode/fallback ratio, engine path, git SHA, weather flags, and key input hashes.
- [2026-04-23] [pre-commit] — Added tests:
  - `tests/test_output_metadata.py`
  - `tests/test_cli_inspect.py`
  - enhanced `tests/test_output_eval.py` diagnostics assertions.
- [2026-04-23] [pre-commit] — Implemented Phase 3A.3 soil realism signaling:
  - propagated `soil_mode` + `pct_fallback_soils` into plotting metadata,
  - added configurable fallback warning threshold (`SWATPLUS_SOIL_FALLBACK_WARN_THRESHOLD`, default `0.25`) in real-basin run path,
  - added visible fallback/synthetic quality annotation in figure titles and watermark footer.
- [2026-04-23] [pre-commit] — Added plot utility regression test `tests/test_output_plots_utils.py` covering quality-flag rendering and publication save path behavior.
- [2026-04-23] [pre-commit] — Updated README with soil fidelity level semantics and `swat inspect` usage.
- [2026-04-23] [pre-commit] — Fixed source-control ignore rule to stop hiding package source modules under `src/swatplus_builder/output/` by narrowing `output/` to `/output/`.

## In Flight

- [2026-04-23] — Phase 3A finalization path:
  - run CI once on branch to verify Linux engine bootstrap + regression gate behavior in GitHub Actions runtime,
  - implement Phase 3A.4 large-basin guardrails with CLI controls and fail-fast policy.

## Next Up

- [1] Implement Phase 3A.4 large-basin guardrails (`--max-hrus`, `--max-subbasins`, fail-fast/auto-adjust policy).
- [2] Prove Phase 3A.1-3A.4 in CI and write `PHASE_3A_CLOSEOUT.md` with exit-criteria evidence.
- [3] Normalize roadmap doc-location references (`docs/ROADMAP.md` vs `ROADMAP.md`) without losing historical docs.

## Open Questions / Blockers

- [2026-04-23] Confirm CI basin data strategy:
  - pinned fixtures/artifacts for determinism, or
  - live online fetch in CI with retry + timeout safeguards.
- [2026-04-23] Legacy historical logs remain in `docs/PROGRESS.md` (gitignored). If needed, port selected historical milestones into this tracked file incrementally.
