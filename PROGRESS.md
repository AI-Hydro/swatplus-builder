# Progress Log

## Active Phase

Phase 3C — Calibration (Kickoff)

## Current Sprint Focus

Kick off Phase 3C with registry-first calibration foundations and mergeable Track 1/Track 2 decomposition.

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
- [2026-04-23] [`b15ebb2`] — Merged Phase 3A.3 implementation commit: soil fidelity flags, plot watermarking, fallback-threshold warning, and README/decision updates plus tracking of previously hidden `src/swatplus_builder/output/*` modules.
- [2026-04-23] [pre-commit] — Implemented Phase 3A.4 large-basin pre-engine guardrails in `run.swatplus.run`:
  - detects `n_subbasins` and `n_hrus` from delineation manifests when available,
  - enforces thresholds (`max_subbasins`, `max_hrus`),
  - warns and continues by default (`auto_adjust=True`), or fails fast on `auto_adjust=False`.
- [2026-04-23] [pre-commit] — Added `swat run` CLI options for guardrails:
  - `--max-hrus`
  - `--max-subbasins`
  - `--auto-adjust/--no-auto-adjust`
- [2026-04-23] [pre-commit] — Added regression coverage in `tests/test_run_swatplus.py` for guardrail warning path and fail-fast path.
- [2026-04-23] [pre-commit] — Verified Phase 3A acceptance tests locally:
  - `SWATPLUS_BUILDER_RUN_ROUTING_REGRESSION=1 pytest -q tests/test_ci_routing_regression.py -s` (pass),
  - `pytest -q tests/test_run_swatplus.py tests/test_output_plots_utils.py tests/test_output_eval.py tests/test_output_metadata.py tests/test_cli_inspect.py` (pass, one expected opt-in skip).
- [2026-04-23] [pre-commit] — Added `PHASE_3A_CLOSEOUT.md` with explicit mapping to Roadmap §3A.5 exit criteria, deviations, and Phase 3B lessons.
- [2026-04-23] [`c1e138a`] — Closed Phase 3A formally with `PHASE_3A_CLOSEOUT.md`.
- [2026-04-23] [pre-commit] — Added `PHASE_3B_PLAN.md` mapping Roadmap §3B.1–3B.5 to isolated PRs with tests, risks, and scope boundaries.
- [2026-04-23] [pre-commit] — Implemented PR-3B-01 foundations:
  - added typed artifact schemas (`config`, `metadata`, `metrics`, `provenance`) in `src/swatplus_builder/artifacts/models.py`,
  - added deterministic canonical JSON + content-hash utilities in `src/swatplus_builder/artifacts/hashing.py`,
  - added tests for schema validation and hash determinism:
    - `tests/test_artifact_models.py`
    - `tests/test_artifact_hashing.py`.
- [2026-04-23] [pre-commit] — Implemented PR-3B-02 local artifact storage:
  - added `ArtifactStore` interface and `LocalArtifactStore` backend in `src/swatplus_builder/artifacts/store.py`,
  - implemented `write/read/exists/query/lineage` operations on `<root>/runs/<content_hash>/...`,
  - added integration tests in `tests/test_artifact_store.py`.
- [2026-04-23] [pre-commit] — Recorded storage-backend decision in `DECISIONS.md` (local FS v1 with pluggable interface).
- [2026-04-23] [pre-commit] — Implemented PR-3B-03 validation runner + CLI:
  - added `src/swatplus_builder/validation/runner.py` with basin spec loading, execution loop, artifact writes, cache-hit short-circuit via `LocalArtifactStore.exists(hash)`, and summary report generation (`summary.csv`, `summary.md`),
  - added `swat validate --basins <file>` command in `src/swatplus_builder/cli.py`,
  - added tests:
    - `tests/test_validation_runner.py`
    - `tests/test_cli_validate.py`.
- [2026-04-23] [pre-commit] — Recorded runner-executor decision in `DECISIONS.md` (injectable executor with orchestrator default during alpha).
- [2026-04-23] [pre-commit] — Implemented PR-3B-04 curated basin suite:
  - added `basins/curated_v1.json` with six representative basins and required metadata (`bbox`, simulation window, expected NSE floor, notes),
  - added schema-validation regression test `tests/test_curated_basins.py`.
- [2026-04-23] [pre-commit] — Implemented PR-3B-05 benchmark-report expansion:
  - upgraded validation outputs with pass/fail accounting and cross-basin aggregation statistics (median/quantiles),
  - added benchmark artifacts in `validation_reports/`: `benchmark_report.md`, `benchmark_summary.json`, and comparison plot outputs (`comparison_metrics.png/.pdf` when matplotlib is available),
  - expanded `tests/test_validation_runner.py` coverage for benchmark artifacts and pass-state persistence.
- [2026-04-23] [pre-commit] — Executed curated-suite validation end-to-end:
  - first run: `cache_hits=0`,
  - second run with identical config: `cache_hits=6`,
  - artifacts persisted under `tests/_artifacts/validation_curated/validation_reports/`.
- [2026-04-23] [pre-commit] — Added `PHASE_3B_CLOSEOUT.md` with explicit 3B.5 exit-criteria evidence and verification commands.
- [2026-04-23] [`f407200`] — Closed Phase 3B formally with cached curated-suite validation evidence and benchmark outputs.
- [2026-04-23] [pre-commit] — Added `PHASE_3C_PLAN.md` mapping 3C.1–3C.7 to isolated PRs with risks and tests.

## In Flight

- [2026-04-23] — Phase 3C implementation kickoff:
  - begin PR-3C-01 parameter registry core implementation.

## Next Up

- [1] Implement PR-3C-01 parameter registry foundation (typed parameter schema + validations).
- [2] Implement PR-3C-02 SpotPy adapter skeleton with artifact-write enforcement.
- [3] Normalize roadmap doc-location references (`docs/ROADMAP.md` vs `ROADMAP.md`) without losing historical docs.

## Open Questions / Blockers

- [2026-04-23] Confirm CI basin data strategy:
  - pinned fixtures/artifacts for determinism, or
  - live online fetch in CI with retry + timeout safeguards.
- [2026-04-23] Legacy historical logs remain in `docs/PROGRESS.md` (gitignored). If needed, port selected historical milestones into this tracked file incrementally.
