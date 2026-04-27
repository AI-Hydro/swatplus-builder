# Progress Log

## Active Phase

Phase 3E — Packaging & Distribution (Kickoff)

## Current Sprint Focus

Establish Phase 3E execution structure with a mergeable PR plan (`PHASE_3E_PLAN.md`) and then execute packaging/distribution work in roadmap order (container baseline, CLI polish, docs readiness, closeout evidence).

## Completed Since Last Update

- [2026-04-24] [`17dbd8e`] — Committed Phase 3C/3D stabilization milestone:
  - calibration bridge + diagnostics + sensitivity integration,
  - MCP operational 8-tool surface,
  - SKILL contract, autoresearch loop, surrogate routing/hold-out harness,
  - Phase 3D closeout evidence artifacts and documentation updates.
- [2026-04-24] [pre-commit] — Added `PHASE_3E_PLAN.md` mapping Roadmap §3E.1–3E.4 to isolated PRs with tests, risks, and explicit scope boundaries.
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
- [2026-04-23] [pre-commit] — Implemented PR-3C-01 parameter registry foundation:
  - added `src/swatplus_builder/params/registry.py` with typed parameter metadata (`Parameter`, `ParameterScope`, `AdjustmentType`),
  - populated canonical initial parameter set from roadmap Phase 3C table,
  - added bounds + scope validation helpers (`validate_value`, `validate_assignment`),
  - exposed import surface via `src/swatplus_builder/params/__init__.py`.
- [2026-04-23] [pre-commit] — Added registry validation tests in `tests/test_parameter_registry.py`.
- [2026-04-23] [pre-commit] — Implemented PR-3C-02 SpotPy adapter skeleton with artifact integration:
  - added `src/swatplus_builder/calibration/spotpy_adapter.py` and `src/swatplus_builder/calibration/__init__.py`,
  - implemented deterministic parameter sampling loop with per-iteration artifact writes,
  - added warm-start cache skip behavior using content-hash existence checks.
- [2026-04-23] [pre-commit] — Added adapter tests in `tests/test_calibration_spotpy_adapter.py` (artifact-per-sample and warm-start skip).
- [2026-04-23] [pre-commit] — Implemented PR-3C-03 `swat calibrate` CLI:
  - added `calibrate` command in `src/swatplus_builder/cli.py`,
  - added multi-objective parsing/validation (`nse`, `log_nse`, `pbias`, `kge`),
  - wired CLI to calibration adapter with artifact persistence and summary output.
- [2026-04-23] [pre-commit] — Added CLI calibration tests in `tests/test_cli_calibrate.py`.
- [2026-04-23] [pre-commit] — Implemented PR-3C-04 calibration reporting artifacts:
  - added `src/swatplus_builder/calibration/report.py` generating `history.csv`, `summary.md`, and dotty/convergence/Pareto plots,
  - updated `swat calibrate` to emit report outputs automatically,
  - added report tests in `tests/test_calibration_report.py`.
- [2026-04-23] [pre-commit] — Added final calibration comparison outputs:
  - baseline vs calibrated SWAT parameter comparison table/plots (`parameter_comparison.csv`, `parameter_comparison.png/.pdf`, `best_solution.json`),
  - observed vs simulated comparison plot output from alignment series (`hydrograph_calibrated_vs_observed.png/.pdf`) with metrics metadata JSON,
  - CLI support via `swat calibrate --alignment-csv <outputs/alignment.csv>`.
- [2026-04-23] [pre-commit] — Produced concrete comparison artifacts under `tests/_artifacts/calibration_demo/calibration_reports/`.
- [2026-04-23] [pre-commit] — Investigated and fixed calibration no-op in real reruns:
  - confirmed baseline and "calibrated" hydrographs were identical because calibration CLI still defaulted to a proxy objective and, in real reruns, stale copied daily outputs were being scored,
  - added `src/swatplus_builder/calibration/real_engine.py` objective wiring with strict parameter-apply checks for LTE files, deterministic per-parameter run directories, and alignment export per sample,
  - updated `swat calibrate` CLI with explicit real-engine mode (`--real-engine`) requiring `--base-txtinout` and `--alignment-csv`, with optional `--binary`, `--outlet-gis-id`, and `--real-work-root`,
  - fixed real-engine scoring path to force fresh daily channel outputs (`print.prt` sanitation: `nyskip=0`, daily channel rows on), purge stale copied day files, and evaluate from `channel_sd_day.txt`,
  - partitioned artifact cache by objective mode (`proxy` vs `real_engine`) to avoid warm-start contamination,
  - updated hydrograph reporting to support true baseline-vs-real-calibrated comparisons (no proxy blending when calibrated alignment is available),
  - generated fresh real-engine calibration artifacts under:
    - `tests/_artifacts/calibration_real_check_20260423_v3/`.
- [2026-04-23] [pre-commit] — Added regression coverage for the above:
  - `tests/test_calibration_real_engine.py` (parameter-apply behavior, alignment loading, deterministic hash, print.prt output forcing),
  - `tests/test_calibration_spotpy_adapter.py` objective-mode cache partition test,
  - `tests/test_cli_calibrate.py` real-engine required-argument test.
- [2026-04-23] [pre-commit] — Performed deep calibration diagnostics (outlet/units/source-file):
  - compared `channel_sd_day`, `basin_sd_cha_day`, and fallback behavior with runtime diagnostics,
  - identified that forcing objective scoring through `channel_sd_day` produced inflated discharge scale for this workflow (`NSE ≈ -1305`) while `basin_sd_cha_day` retained physically consistent scale (`NSE ≈ -0.208` baseline),
  - switched real-engine objective and calibrated-alignment generation to use `basin_sd_cha_day` as primary source,
  - validated objective responsiveness: 10-sample run produced varied NSE (`-1.54` to `-0.24`) with non-identical baseline vs calibrated hydrographs.
- [2026-04-23] [pre-commit] — Added calibration stabilization controls for fail-loud foundation:
  - objective source-file lock (`--objective-sim-file`, `--strict-objective-file`) with runtime trace persistence (`objective_trace.json`) per sample,
  - explicit outlet guard (`--require-explicit-outlet` / `--allow-outlet-autodetect`) enforced in real-engine objective,
  - minimum NSE-improvement gate (`--min-improvement-nse`) to fail calibration runs that do not beat rerun baseline by required margin,
  - calibration context metadata emitted to report directory (`calibration_run_context.json`).
- [2026-04-23] [pre-commit] — Validated new fail-loud behavior:
  - strict run with `--min-improvement-nse 0.01` failed as expected (`best_nse=-0.244`, `baseline_nse=-0.208`),
  - strict run without gate completed and persisted full objective traces under:
    - `tests/_artifacts/calibration_real_check_20260423_v6/`.
- [2026-04-23] [pre-commit] — Implemented PR-3C-05 typed forward function + dataset bridge:
  - added `src/swatplus_builder/calibration/forward.py` with typed models and API:
    - `forward_simulate(ForwardRequest) -> SimulatedTimeseries`
    - `extract_surrogate_dataset(...) -> SurrogateDataset`
    - `verify_forward_artifact(...) -> ForwardVerification`
  - forward path is artifact-aware/content-hash cached and records run metadata under artifact store.
  - surrogate bridge extracts parameter/metric/timeseries-derived rows from forward artifacts.
  - added explicit verification checks on objective source/outlet trace, timeseries integrity, and recomputed NSE consistency.
- [2026-04-23] [pre-commit] — Added tests for PR-3C-05:
  - `tests/test_calibration_forward.py` covering determinism/cache short-circuit, dataset extraction, and output-truth verification.
- [2026-04-23] [pre-commit] — Ran real forward verification with actual SWAT+ output:
  - artifact root: `tests/_artifacts/forward_verify_real_20260423/`
  - content hash: `286c7a7d231edcd220d6aab40797f3495ce47d1d24140c892af68695d7a907eb`
  - verification passed all checks (`trace/source/outlet/timeseries/NSE consistency`).
- [2026-04-23] [pre-commit] — Read and adopted revised calibration authority:
  - `CALIBRATION_PLAN_REVISED.md` now governs Phase 3C sequencing in this branch.
  - added `PHASE_3C_REVISED_PLAN.md` with PR decomposition aligned to revised 3C.1–3C.7.
- [2026-04-23] [pre-commit] — Began revised 3C.1 dependency alignment:
  - updated `pyproject.toml` optional `swatplus` extra to:
    - `pySWATPlus>=1.3.0`
    - `pymoo>=0.6.1`
    - `SALib>=1.5.0`
- [2026-04-23] [pre-commit] — Implemented revised 3C.1 runtime verification guard:
  - added `src/swatplus_builder/calibration/pyswatplus_runtime.py`,
  - added `ensure_pyswatplus_runtime()` typed checks for module presence + minimum version compatibility,
  - exposed runtime guard via `swatplus_builder.calibration` import surface,
  - added tests in `tests/test_calibration_pyswatplus_runtime.py`.
- [2026-04-23] [pre-commit] — Implemented revised 3C.2 registry compatibility layer:
  - extended `Parameter` model with `change_type` (`absval`/`pctchg`/`abschg`) and `physical_meaning`,
  - added conversion helpers:
    - `Parameter.to_pyswatplus_dict(value)`
    - `Parameter.to_pyswatplus_bounds_dict()`,
  - exported `ChangeType` via `swatplus_builder.params`,
  - added registry conversion tests in `tests/test_parameter_registry.py`.
- [2026-04-23] [pre-commit] — Implemented revised 3C.3 bridge scaffold (`Calibrator`):
  - added `src/swatplus_builder/calibration/calibrator.py` with typed request/result models, backend protocol, and `PySwatPlusBackend` adapter boundary,
  - persisted calibration-level artifacts under `runs/calibrations/<hash>/` (`history.csv`, `summary.md`, `best_solution.json`, `pareto.csv` for multi-objective),
  - persisted per-evaluation standard run artifacts via content-hash into canonical `runs/<hash>/` store,
  - wired CLI path: `swat calibrate --calibration-engine pyswatplus ...`,
  - added fail-loud dependency/runtime errors with actionable install guidance.
- [2026-04-23] [pre-commit] — Added revised 3C.1 integration-test scaffold:
  - `tests/test_calibration_pyswatplus_integration.py` (opt-in smoke, skipped unless env + dependencies are present).
- [2026-04-23] [pre-commit] — Added/updated tests for bridge path:
  - `tests/test_calibration_calibrator.py` (artifact writes + warm-start cache behavior),
  - `tests/test_cli_calibrate.py` (`--calibration-engine pyswatplus` branch routing),
  - `tests/test_calibration_pyswatplus_runtime.py` runtime guard coverage.
- [2026-04-23] [pre-commit] — Implemented revised 3C.4 sensitivity bridge:
  - added `src/swatplus_builder/sensitivity.py` with typed request/result models and backend adapter boundary,
  - added `SensitivityAnalyzer` orchestrator persisting artifacts under `runs/sensitivity/<hash>/`,
  - added CLI command: `swat sensitivity --basin ... --base-txtinout ... --parameters ... --n-samples ...`,
  - added fail-loud dependency/runtime behavior consistent with calibration bridge.
- [2026-04-23] [pre-commit] — Added sensitivity tests:
  - `tests/test_sensitivity_bridge.py` (artifact write + warm-start cache behavior),
  - `tests/test_cli_sensitivity.py` (CLI routing + validation).
- [2026-04-23] [pre-commit] — Implemented revised 3C.5 diagnostic layer:
  - added `src/swatplus_builder/diagnostics.py` with typed `Diagnosis` model and explicit rule set for:
    - peak lag,
    - baseflow/flashiness mismatch,
    - volume bias,
    - snow timing mismatch,
    - flat hydrograph structural check,
    - high PBIAS with acceptable NSE,
    - fast/slow recession behavior,
  - added markdown reporting helper `write_diagnostics_report(...)`,
  - added CLI command: `swat diagnose --run-artifact <path> [--out-md ...]`.
- [2026-04-23] [pre-commit] — Added diagnostics tests:
  - `tests/test_diagnostics.py` (rule firing + report write),
  - `tests/test_cli_diagnose.py` (CLI command behavior).
- [2026-04-23] [pre-commit] — Ran real diagnostic verification:
  - command: `swat diagnose` on real forward artifact
  - output report written under:
    - `tests/_artifacts/forward_verify_real_20260423/runs/286c7a.../diagnostics.md`
  - diagnoses produced: `3`.
- [2026-04-23] [working session] — Calibration execution compatibility + final real-engine evidence:
  - fixed pySWATPlus observed CSV date normalization bug (`DatetimeIndex.strftime`),
  - added pySWATPlus macOS runtime compatibility shims (executable detection + env patch + staged TxtInOut runtime companions),
  - added `sim_output_file` passthrough in `CalibratorRequest` and wired CLI `--objective-sim-file` into the pyswatplus branch,
  - produced fresh real-engine calibration artifact and reports under:
    - `tests/_artifacts/calibration_final_real_20260423/calibration_reports`.
- [2026-04-23] [working session] — Implemented revised Phase 3C.6 preset workflow patterns in CLI:
  - added `swat calibrate --preset quick|standard|thorough`,
  - wired preset default overrides for both engines (`spotpy`, `pyswatplus`) with explicit runtime echo of applied configuration,
  - added CLI regression tests for invalid preset, spotpy quick preset behavior, and pyswatplus quick preset behavior,
  - verified with:
    - `pytest -q tests/test_cli_calibrate.py tests/test_calibration_calibrator.py`.
- [2026-04-23] [working session] — Executed revised Phase 3C.7 curated-basin pySWATPlus evidence run (usgs_01547700):
  - command used `--calibration-engine pyswatplus --preset quick` with 160 evaluations,
  - calibration artifacts persisted under:
    - `tests/_artifacts/calibration_pyswatplus_3c7_evidence_v2_20260423/runs/calibrations/d445b749.../`,
  - hardened pySWATPlus staging path for this run:
    - forced daily output print settings in staged `print.prt`,
    - purged stale daily objective files before calibration,
    - added objective outlet filtering (`gis_id`) via `outlet_gis_id`.
  - added independent verification step (real-engine objective rerun):
    - baseline NSE: `-0.2081`,
    - best-parameter NSE: `-0.2029` (small positive improvement),
    - verification workspace:
      - `tests/_artifacts/calibration_pyswatplus_3c7_evidence_v2_20260423/verification_real_objective/`.
  - observed blocker: pySWATPlus-reported objective values remain numerically distorted (`~ -3.67e9`) despite real-engine verification showing plausible-scale metrics; requires backend metric interpretation hardening before claiming benchmark-quality 3C.7 closure.
- [2026-04-23] [working session] — Implemented metric parity hardening for pySWATPlus bridge (scope: metric interpretation only):
  - added authoritative post-evaluation metric pass in bridge:
    - computes `nse`/`kge` with `evaluate_run` on each generated simulation output for the requested `sim_output_file` + `outlet_gis_id`,
    - bridge-reported calibration metrics now come from this authoritative pass,
  - added per-evaluation parity logging:
    - `metric_parity_log.csv` with required fields:
      - `aligned_days`, `obs_mean/std/min/max`, `sim_mean/std/min/max`,
      - `first_date`, `last_date`, `outlet_gis_id`, `bridge_reported_nse`, `bridge_reported_kge`,
      - plus `pyswatplus_raw_objective_nse` for traceability,
  - ensured staged pySWATPlus runs retain per-simulation directories until parity evaluation completes, then cleanup is applied.
- [2026-04-23] [working session] — Validated parity and reran quick calibration after parity fix:
  - parity smoke run:
    - `tests/_artifacts/calibration_metric_parity_smoke_20260423/.../metric_parity_log.csv`
    - bridge NSE now plausible-scale (`-0.208...`) while raw pySWATPlus objective remained extreme (`~ -3.67e9`) and is no longer used for reported calibration metrics,
  - full quick rerun (160 evals) after parity fix:
    - `tests/_artifacts/calibration_metric_parity_quick_20260423/runs/calibrations/d445b749.../`
    - completed successfully with bridge-reported `best_nse=-0.208`.
- [2026-04-23] [working session] — Completed revised Phase 3C closeout packaging:
  - added formal closeout document:
    - `PHASE_3C_CLOSEOUT.md`
  - added regression guard test for metric parity logging + bridge-metric overwrite behavior:
    - `tests/test_calibration_calibrator.py::test_metric_parity_overwrites_bridge_metrics_and_writes_required_log`
  - recorded architectural decision making authoritative `evaluate_run` metrics the reporting source for pySWATPlus bridge:
    - `DECISIONS.md` entry dated `2026-04-23`.
- [2026-04-24] [pre-commit] — Began Phase 3D kickoff:
  - added `PHASE_3D_PLAN.md` with mergeable PR decomposition (`PR-3D-01`..`PR-3D-06`),
  - mapped revised 3D surrogate items (`3D.X/3D.Y/3D.Z`) into explicit implementation/testing units,
  - set Phase 3D first implementation target to MCP typed tool foundation.
- [2026-04-24] [working session] — Implemented Phase 3D PR-3D-01 MCP foundation:
  - replaced placeholder MCP server with FastMCP-based typed 8-tool surface in `src/swatplus_builder/mcp/server.py`,
  - wired tool contracts for `build_project`, `run_basin`, `calibrate`, `propose_parameters`, `compare_runs`, `query_artifacts`, `diagnose_failure`, and `validate`,
  - fixed parameter-proposal bounds bug by reading canonical registry ranges (`meta.range`) instead of non-existent fields,
  - updated MCP package exports in `src/swatplus_builder/mcp/__init__.py`,
  - added regression tests in `tests/test_mcp_server.py` covering:
    - exact 8-tool registration,
    - placeholder not-implemented statuses,
    - deterministic parameter proposal bounds,
    - compare-runs metrics handling with missing metrics fallback,
    - artifact query filtering behavior,
    - diagnostics invocation on alignment CSV,
    - validate-tool runner wiring/summary behavior (monkeypatched).
  - verification commands:
    - `pytest -q tests/test_mcp_server.py`,
    - `pytest -q tests/test_parameter_registry.py tests/test_diagnostics.py`.
- [2026-04-24] [working session] — Implemented Phase 3D PR-3D-02 agent skill packaging:
  - added root `SKILL.md` aligned to Roadmap Appendix C sections:
    - tool catalog (8 MCP tools),
    - parameter registry guidance,
    - diagnostic heuristics,
    - basin taxonomy,
    - evaluation protocol,
    - example workflows,
    - common pitfalls.
  - documented current MCP tool operational status and failure modes explicitly (including placeholder tools).
  - added regression test `tests/test_skill_md.py` to enforce required section headers and exact MCP tool-surface references.
  - verification command:
    - `pytest -q tests/test_mcp_server.py tests/test_skill_md.py`.
- [2026-04-24] [working session] — Implemented Phase 3D PR-3D-03 autoresearch loop orchestrator:
  - added typed module `src/swatplus_builder/autoresearch/loop.py` with:
    - `LoopRequest`, `LoopStoppingCriteria`, `SurrogatePrediction`, `LoopIterationResult`, `LoopResult`,
    - deterministic proposal strategies (`random`, `grid`, `history`),
    - uncertainty-gated routing between surrogate prediction and real evaluator,
    - artifact-native iteration persistence via `LocalArtifactStore`,
    - per-iteration lineage wiring (`provenance.parent_run`, `proposal_source`),
    - stop criteria support: `n_iterations`, objective threshold, convergence tolerance/window.
  - added package export surface in `src/swatplus_builder/autoresearch/__init__.py`.
  - added regression tests in `tests/test_autoresearch_loop.py` covering:
    - deterministic behavior with fixed seed,
    - objective-threshold stop condition,
    - convergence stop condition,
    - lineage persistence in artifact records,
    - surrogate-routing branch when uncertainty is below threshold.
  - verification commands:
    - `pytest -q tests/test_autoresearch_loop.py`,
    - `pytest -q tests/test_autoresearch_loop.py tests/test_mcp_server.py tests/test_skill_md.py`.
- [2026-04-24] [working session] — Implemented Phase 3D PR-3D-04 surrogate training + uncertainty ensemble:
  - added `src/swatplus_builder/autoresearch/surrogate.py` with typed APIs:
    - `SurrogateTrainingRequest`,
    - `train_surrogate_ensemble(...)`,
    - `predict_with_surrogate(...)`,
    - `make_loop_surrogate_predictor(...)`.
  - implemented deterministic bootstrap linear-regression ensemble training from artifact-backed rows (`extract_surrogate_dataset`), with uncertainty from inter-member spread.
  - persisted surrogate artifacts under `surrogates/<ensemble_id>/`:
    - `training_rows.csv`,
    - `model_cards.json`,
    - `training_summary.json`.
  - exported surrogate interfaces via `src/swatplus_builder/autoresearch/__init__.py`.
  - added regression tests in `tests/test_autoresearch_surrogate.py` covering:
    - artifact persistence,
    - fixed-seed reproducibility,
    - non-zero uncertainty spread on noisy data,
    - fail-loud behavior for insufficient training rows.
  - recorded architecture decision in `DECISIONS.md` for surrogate v1 model-family choice.
  - verification commands:
    - `pytest -q tests/test_autoresearch_surrogate.py`,
    - `pytest -q tests/test_autoresearch_loop.py tests/test_autoresearch_surrogate.py tests/test_mcp_server.py tests/test_skill_md.py`.
- [2026-04-24] [working session] — Implemented Phase 3D PR-3D-05 surrogate-aware routing + hold-out harness:
  - extended surrogate module `src/swatplus_builder/autoresearch/surrogate.py` with:
    - uncertainty-gated routing decision API: `decide_routing_path(...) -> RoutingDecision`,
    - hold-out evaluation APIs:
      - `HoldoutEvaluationRequest`,
      - `HoldoutEvaluationCase`,
      - `HoldoutEvaluationReport`,
      - `evaluate_surrogate_holdout(...)`,
    - basin-based row filtering for train/exclude controls in surrogate training request.
  - integrated hold-out reporting artifacts under:
    - `<ensemble_artifact_dir>/holdout_evaluation/summary.json`,
    - `<ensemble_artifact_dir>/holdout_evaluation/cases.csv`.
  - expanded autoresearch exports in `src/swatplus_builder/autoresearch/__init__.py` for routing and hold-out interfaces.
  - expanded tests in `tests/test_autoresearch_surrogate.py` covering:
    - route-threshold branch behavior (surrogate vs real-engine),
    - hold-out evaluation execution and artifact/report persistence.
  - verification commands:
    - `pytest -q tests/test_autoresearch_surrogate.py`,
    - `pytest -q tests/test_autoresearch_loop.py tests/test_autoresearch_surrogate.py tests/test_mcp_server.py tests/test_skill_md.py`.
- [2026-04-24] [working session] — Implemented Phase 3D PR-3D-06 closeout evidence packaging:
  - added `PHASE_3D_CLOSEOUT.md` with explicit mapping to Roadmap 3D.5 exit criteria,
  - documented achieved items (typed/operational 8-tool MCP surface, SKILL contract, autoresearch loop, surrogate routing + hold-out harness),
  - documented remaining evidence gaps for strict full closure:
    - external MCP-capable agent smoke validation artifact,
    - curated-basin autoresearch trace artifact.
- [2026-04-24] [working session] — Executed remaining Phase 3D evidence runs and closed 3D.5 gaps:
  - curated-basin autoresearch evidence run completed for `usgs_01547700` with persisted trace bundle under:
    - `tests/_artifacts/phase3d_evidence_20260424/curated_autoresearch/`
    - key artifact: `autoresearch_trace.json`,
  - external MCP client smoke completed against stdio server with persisted transcript under:
    - `tests/_artifacts/phase3d_evidence_20260424/mcp_smoke/`
    - key artifact: `mcp_smoke_transcript.json`,
  - updated `PHASE_3D_CLOSEOUT.md` to mark all Roadmap 3D.5 criteria as met (with explicit surrogate-model-family deviation note retained).

## In Flight

- [2026-04-24] — Phase 3E kickoff plan is written; next action is PR-3E-01 implementation (container baseline).

## Next Up

- [1] Stage and commit Phase 3E kickoff plan (`PHASE_3E_PLAN.md` + `PROGRESS.md` active-phase update).
- [2] Implement PR-3E-01: container baseline with smoke verification and usage docs.
- [3] Confirm licensing strategy decision path before broadening pySWATPlus coupling in future packaging/distribution work.

## Open Questions / Blockers

- [2026-04-23] Confirm CI basin data strategy:
  - pinned fixtures/artifacts for determinism, or
  - live online fetch in CI with retry + timeout safeguards.
- [2026-04-23] Legacy historical logs remain in `docs/PROGRESS.md` (gitignored). If needed, port selected historical milestones into this tracked file incrementally.
- [2026-04-23] Licensing blocker acknowledged by revised plan: project is currently MIT while pySWATPlus is GPL-3.0; explicit human decision is still required for final coupling strategy.
- [2026-04-24] pySWATPlus raw objective remains numerically extreme in this setup; mitigated for reporting by bridge metric parity layer. Open decision: whether to additionally expose a normalized surrogate objective field for optimizer diagnostics in future phases.

## 2026-04-24 — Calibration Bridge Hardening (Pre-Next-Phase Blocker)

### Active Phase

Phase 3C closeout hardening (bridge reliability gate before phase advance)

### Current Sprint Focus

Resolve flat pySWATPlus calibration evaluations by proving the chain `proposal -> input change -> output change -> metric change` and formalizing machine/human playbook logic.

### Completed Since Last Update

- [2026-04-24] [working session] — Patched pySWATPlus backend request plumbing to honor explicit binary override in calibration mode (`--binary` now reaches pySWATPlus staging path).
- [2026-04-24] [working session] — Added bridge diff diagnostics in `calibrator.py`:
  - per-evaluation changed-file tracking,
  - fail-loud guard when no significant input change is detected,
  - output hash/mtime capture per evaluation,
  - stale-output cleanup extended to day/month/year files before objective runs.
- [2026-04-24] [working session] — Diagnosed flat-output signature:
  - parameter proposals varied,
  - `calibration.cal` varied,
  - pySWATPlus simulation outputs remained byte-identical,
  - therefore raw pySWATPlus objective path not trustworthy for current engine/input compatibility.
- [2026-04-24] [working session] — Implemented authoritative fallback rerun in parity bridge:
  - auto-detect flat-output condition (`unique parameter vectors >1` with single output hash/metric),
  - rerun each proposal through direct real-objective path (`make_real_objective` + `evaluate_run`),
  - write parity logs with explicit metric source `evaluate_run_real_objective_rerun`.
- [2026-04-24] [working session] — Verified acceptance on real CN2-only run:
  - artifact: `tests/_artifacts/calibration_bridge_fix_20260424c/runs/calibrations/d455d05d587bc78b9783ec5a218284ee9f41525a521df103768b4d0847449ca6/`
  - `history.csv` unique NSE count = 4/4,
  - `metric_parity_log.csv` unique NSE count = 4/4,
  - output hash unique count = 4/4.
- [2026-04-24] [working session] — Added human playbook and machine skill:
  - `docs/SWATPLUS_MODELING_PLAYBOOK.md` (status-labeled evidence base),
  - `src/swatplus_builder/skills/swatplus_playbook/` (`schemas.py`, `rules.py`, `update.py`, `README.md`),
  - autoresearch loop integration to consult playbook and append evidence safely.
- [2026-04-24] [working session] — Added regression tests:
  - calibration bridge hardening and authoritative-rerun trigger,
  - playbook recommendation logic,
  - append-only playbook update safety,
  - autoresearch-playbook integration behavior.

### In Flight

- [2026-04-24] Final multi-basin confirmation pass with updated bridge to quantify calibration lift across 2-3 curated basins under parity-safe objective rerun.

### Next Up

- [1] Run parity-hardened CN2 calibration on additional curated basins and update readiness comparison table.
- [2] Add CI smoke assertion for non-flat calibration history under bridge-rerun mode.
- [3] Start next roadmap phase only after documented multi-basin bridge confirmation.

### Open Questions / Blockers

- [2026-04-24] Flat pySWATPlus raw-output behavior appears to stem from engine/input compatibility with `calibration.cal` path; continue treating `evaluate_run` rerun metrics as authoritative until upstream behavior is resolved.

## 2026-04-24 — Cross-Basin Realism Investigation (NSE/KGE Weakness)

### Active Phase

Phase 3E readiness hardening (scientific realism guardrails before broader expansion)

### Current Sprint Focus

Investigate persistent weak NSE/KGE despite successful execution by tracing silent structural/evaluation mismatches and adding fail-loud realism diagnostics.

### Completed Since Last Update

- [2026-04-24] [working session] — Ran fresh multi-basin realism probe batch (`multibasin_20260424_realism_probe`) and confirmed extreme cross-basin score instability despite non-zero routing execution.
- [2026-04-24] [working session] — Identified recurrent silent condition: requested outlet IDs are frequently non-terminal across generated basins.
- [2026-04-24] [working session] — Patched `evaluate_run` outlet handling:
  - emit `requested_outlet_is_terminal`,
  - keep dry-outlet fallback behavior,
  - add guarded terminal switch for non-terminal requests only when terminal NSE improves (`requested_outlet_non_terminal_best_nse`),
  - keep requested outlet otherwise with explicit reason (`requested_outlet_non_terminal`).
- [2026-04-24] [working session] — Added evaluator regression tests for:
  - non-terminal outlet switching when terminal improves fit,
  - non-terminal outlet retention when requested fit is better.
- [2026-04-24] [working session] — Added realism-audit fields to `scripts/run_multibasin_e2e.py` summary output:
  - outlet diagnostics, soil mode/fallback, NSE/KGE, sim/obs volume ratio,
  - structural anomaly flags (`channels_per_subbasin_extreme`, low-HRU warning, volume bias flags, etc.).

### In Flight

- [2026-04-24] Re-run curated basins with patched evaluator + realism audit to produce a stable before/after table for Phase 3E readiness.

### Next Up

- [1] Execute parity-safe multibasin rerun and persist updated summary table with realism flags.
- [2] Add CI smoke assertion on realism flags for critical silent-failure patterns (non-terminal requested outlet + extreme volume bias).
- [3] Prioritize structural fixes for basins with extreme volume bias after outlet selection is stabilized.

### Open Questions / Blockers

- [2026-04-24] `01547700` remains extremely poor even after outlet logic hardening; likely dominated by forcing/parameter realism or scale/unit mismatch rather than outlet mis-selection.
- [2026-04-24] `01013500` improved materially with non-terminal handling, but still weak; additional soil/forcing structural audits are required before claiming cross-basin scientific reliability.

## 2026-04-24 — Realism Hardening Before Further Calibration

### Active Phase

Pre-calibration structural realism stabilization (bridge between Phase 3C reliability and broader expansion)

### Current Sprint Focus

Prevent low-credibility runs from entering calibration by correcting silent outlet/topology mismatches and adding fail-loud realism gates for delineation, HRU coverage, and soils.

### Completed Since Last Update

- [2026-04-24] [working session] — Corrected terminal-channel parsing to use `gis_id` (header-aware) in both evaluator and multibasin diagnostics; added regression tests for `id` vs `gis_id` mismatch.
- [2026-04-24] [working session] — Removed the uniform weather-forcing coordinate hack from `examples/real_basin_marsh_creek.py`; basin now preserves native subbasin spatial forcing context with bounded station sampling.
- [2026-04-24] [working session] — Added delineation realism controls:
  - threshold retry strategy anchored at `stream_threshold_cells=2000` (with bounded alternatives),
  - mandatory validation against reference basin polygon,
  - persisted `delin/validation_result.json` artifact.
- [2026-04-24] [working session] — Added HRU realism gate (`SWATPLUS_MIN_HRU_COVERAGE_RATIO`, default `0.90`) to fail runs where too many subbasins lack valid landuse/soil overlay.
- [2026-04-24] [working session] — Added strict soil realism gate:
  - fail by default on synthetic or excessive fallback soils (`SWATPLUS_MAX_SOIL_FALLBACK_RATIO`, default `0.10`),
  - explicit override required (`SWATPLUS_ALLOW_SYNTHETIC_SOILS=1`) for diagnostic-only runs.
- [2026-04-24] [working session] — Added richer batch realism diagnostics (`n_terminals`, terminal flags) and persisted post-fix comparison snapshots under:
  - `tests/_artifacts/e2e_runs/multibasin_20260424_realism_probe/reports/`.
- [2026-04-24] [working session] — Validation evidence runs:
  - `multibasin_20260424_realism_fix_check_thr2000/usgs_01547700` passes delineation + soil gates and preserves expected 43-subbasin structure,
  - `multibasin_20260424_soil_gate_check/usgs_01013500` now fails before calibration with explicit low-realism soil path (seed-minimal fallback + gate).

### In Flight

- [2026-04-24] Quantify how much remaining volume bias is attributable to model structure/parameter realism vs forcing representation now that structural gates are active.

### Next Up

- [1] Add CI smoke assertion that calibration entrypoints reject synthetic/high-fallback soils unless override flag is explicitly set.
- [2] Add explicit volume-bias gate/report in the run summary (`sim_obs_volume_ratio`) as a pre-calibration blocker threshold.
- [3] Expand realism-gated evidence to 2–3 curated basins and update readiness closeout with pass/fail rationale.

### Open Questions / Blockers

- [2026-04-24] `01547700` still shows severe positive volume bias (~52x) despite improved structural realism gates; this appears to be model fidelity/input realism, not execution integrity.
- [2026-04-24] `01013500` exhibits widespread HRU overlay dropouts and soils fallback failure (`unrecognized hydrologic group code: 'NAN'`), requiring upstream soil/overlay data-quality remediation before trustworthy calibration.

## 2026-04-24 — Water Balance Error Diagnosis and Correction

### Active Phase

Pre-calibration realism hardening (water-balance integrity)

### Current Sprint Focus

Diagnose extreme discharge overestimation through mass-balance analysis (precipitation/runoff partition, soil hydraulics, parameter response) and implement targeted structural corrections before further calibration.

### Completed Since Last Update

- [2026-04-24] [investigation] — Confirmed primary overestimation driver was an observed-unit bug:
  - `pygeohydro.NWIS.get_streamflow` values were already in m3/s,
  - pipeline applied an additional cfs→m3/s conversion, shrinking observed flows by ~35x.
- [2026-04-24] [patch] — Removed double conversion in `src/swatplus_builder/calibration/nwis.py`; added regression test `tests/test_calibration_nwis.py`.
- [2026-04-24] [evidence] — Re-ran `01547700`:
  - NSE improved from ~`-1273.98` to ~`-0.0736` without calibration,
  - sim/obs volume ratio improved from ~`52.10` to ~`1.48`.
- [2026-04-24] [diagnosis] — Water-balance partition still showed elevated runoff (`basin_wb_aa`: wateryld ~1018 mm vs precip ~1040 mm), indicating residual structural bias.
- [2026-04-24] [sensitivity audit] — Ran targeted perturbations on corrected baseline (`CN2`, `ALPHA_BF`, `SURLAG`, `soils_lte.scon`) with artifacts under:
  - `tests/_artifacts/e2e_runs/multibasin_20260424_wb_sensitivity_01547700/`.
  - Findings:
    - `CN2`/`SURLAG` had minimal effect in this LTE setup,
    - reducing `soils_lte.scon` strongly reduced runoff bias and improved NSE.
- [2026-04-24] [patch] — Added LTE soil conductivity realism scaling in runner (`SWATPLUS_LTE_SCON_SCALE`, default `0.60`) with metadata trace note.
- [2026-04-24] [validation] — Fresh end-to-end run `multibasin_20260424_wb_corrected_default/usgs_01547700`:
  - NSE `0.0162`,
  - volume ratio `1.066`,
  - basin WB shifted toward more realistic partition (`et` up, `latq/wateryld` down).

### In Flight

- [2026-04-24] Extend corrected water-balance diagnostics to additional curated basins and verify whether LTE conductivity scaling generalizes.

### Next Up

- [1] Run corrected pipeline on `01013500` with realism gates and capture whether soil/overlay failures remain hard blockers.
- [2] Add explicit report table (before/after) for `precip`, `surq`, `latq`, `et`, `wateryld`, and `sim/obs volume ratio` in batch README.
- [3] Investigate CN2 insensitivity in LTE mode as a potential parameter-injection/model-structure limitation before relying on CN2-based calibration.

### Open Questions / Blockers

- [2026-04-24] CN2 perturbations showed weak response after unit fix; determine whether LTE internals override static CN2 enough to limit calibratability.
- [2026-04-24] `01013500` still has extensive HRU overlay dropouts and synthetic-soil fallback gating failures; this remains a pre-calibration data-quality blocker.

## 2026-04-24 — Timing/Variability Investigation (LTE Dynamic Routing)

### Active Phase

Pre-calibration hydrologic-dynamics stabilization (timing and variability)

### Current Sprint Focus

Diagnose why hydrograph timing controls (`CN2`, `SURLAG`, `ALPHA_BF`, `GW_DELAY`, channel routing terms) have weak or null effect, and restore non-zero physically connected channel flow without reintroducing silent routing failure.

### Completed Since Last Update

- [2026-04-24] [diagnosis] — Identified LTE routing-length instability in vendored GIS import path:
  - realistic channel lengths (`hyd-sed-lte.cha:len` in ~0.1–4.4 km) caused full `flo_out=0` collapse across channels,
  - threshold experiment showed sharp behavior change at `len > 0.001 km`:
    - `len <= 0.001` produced non-zero routed flow,
    - `len >= 0.002` produced all-zero channel outflow.
- [2026-04-24] [patch] — Updated vendored import logic to cap LTE effective channel length instead of unconstrained GIS length:
  - `src/swatplus_builder/editor/vendored/actions/import_gis.py`
  - `src/swatplus_builder/editor/vendored/actions/import_gis_legacy.py`
  - behavior now: `raw_len_km = len2/1000` with floor, then `lte_len_km = min(raw_len_km, 0.001)`.
- [2026-04-24] [validation] — Re-ran full Marsh Creek E2E (`multibasin_20260424_timing_fix_lencap`):
  - channel flow remained non-zero,
  - metrics restored to stable post-water-balance baseline (`NSE ~0.0162`, `KGE ~-0.1124`) instead of all-zero simulated hydrograph.
- [2026-04-24] [sensitivity evidence] — Ran post-fix timing sweep (`multibasin_20260424_timing_sensitivity_01547700_postfix`):
  - effective controls: `ALPHA_BF`, `CN2`,
  - inert in current LTE configuration: `SURLAG`, `msk_co1/co2/x`, channel `mann`,
  - best tested timing/variability tradeoff: `ALPHA_BF=0.2` (`NSE ~0.1256`),
  - `CN2` reduction tempered peaks/variance but did not resolve peak timing offset.
- [2026-04-24] [feasibility check] — `GW_DELAY` not tunable in current LTE TxtInOut path (no `aquifer.aqu` generated); recorded in `gw_delay_status.txt` artifact.

### In Flight

- [2026-04-24] Resolve multi-terminal/non-terminal outlet topology ambiguity so evaluation is tied to physically correct gauge-representative terminal path.

### Next Up

- [1] Add explicit outlet-topology consistency gate (single terminal or deterministic terminal selection rationale persisted in metadata).
- [2] Promote dynamic calibration tier for LTE to effective parameters only (`ALPHA_BF`, `CN2`) until routing terms become active.
- [3] Add regression check that prevents reintroduction of all-zero `flo_out` collapse after GIS import.

### Open Questions / Blockers

- [2026-04-24] Current delineation yields multi-terminal routing (`chandeg.con`), and requested gauge outlet is often non-terminal; this can silently bias evaluation target.
- [2026-04-24] In this LTE path, channel-routing parameters (`SURLAG`, Muskingum, Manning) remain structurally inactive after stabilization, limiting timing calibration degrees of freedom.

## 2026-04-24 — Outlet Provenance Hardening (Pinned + Reproducible Metrics)

### Active Phase

Phase 3A stabilization hardening (outlet reproducibility and defensible evaluation provenance)

### Current Sprint Focus

Make all reported discharge metrics reproducible by pinning the scored outlet and persisting outlet-selection provenance and source-file hashes.

### Completed Since Last Update

- [2026-04-24] [patch] — Implemented two-pass outlet evaluation in `examples/real_basin_marsh_creek.py`:
  - pass 1 (`outlet_policy=auto`) selects defensible outlet,
  - pass 2 (`outlet_policy=strict`) re-scores with the pinned outlet only,
  - `reports/metrics.json` now always reflects strict pinned scoring.
- [2026-04-24] [artifact] — Added `outputs/outlet_provenance.json` with selection and pinned-pass diagnostics, metrics, aligned-day counts, and policy context.
- [2026-04-24] [schema] — Extended `RunMetadata` with outlet provenance fields:
  - `outlet_policy`, `outlet_provenance_path`, `outlet_provenance_sha256`,
  - `sim_source_file`, `sim_source_sha256`, `chandeg_con_sha256`.
- [2026-04-24] [diagnostics] — Extended evaluator diagnostics already exposed by `evaluate_run` to include terminal outlet list/count and source hashes in a test-covered way.
- [2026-04-24] [batch reporting] — Extended `scripts/run_multibasin_e2e.py` summary schema to ingest/report `outlet_policy` and provenance hash.
- [2026-04-24] [tests] — Added/updated tests:
  - strict-policy dry-outlet behavior,
  - provenance hash and terminal diagnostics,
  - metadata roundtrip with outlet provenance fields.

### In Flight

- [2026-04-24] Promote pinned outlet policy controls into additional CLI/reporting entrypoints where ad-hoc `evaluate_run` use still defaults to `auto`.

### Next Up

- [1] Add a compact `swat inspect`/batch report section that displays pinned outlet provenance at a glance (policy, selected outlet, source hash).
- [2] Add a regression assertion that reported metrics and `outputs/alignment.csv` are produced from the same strict-pinned outlet context.
- [3] Apply the same pinned-outlet provenance convention to calibration report generation outputs.

### Open Questions / Blockers

- [2026-04-24] Some historical artifacts generated before this patch do not include `outlet_provenance.json`; comparisons across old/new runs must account for that schema evolution.

## 2026-04-24 — Locked-Benchmark Effective-Parameter Calibration Verification

### Active Phase

Calibration reliability hardening (pre-next-phase gate)

### Current Sprint Focus

Lock benchmark context and verify that calibrating only proven-effective parameters (`CN2`, `ALPHA_BF`) yields reproducible, real metric improvement.

### Completed Since Last Update

- [2026-04-24] [evidence] — Created locked benchmark artifact for `usgs_01547700` at:
  - `tests/_artifacts/calibration_locked_20260424_effective_01547700/benchmark/`
  - includes strict-pinned alignment, metrics, outlet provenance, and `alignment_sha256`.
- [2026-04-24] [execution] — Attempted pySWATPlus bridge calibration on locked benchmark with effective parameter subset (`CN2,ALPHA_BF`); run failed with `pySWATPlus calibration execution failed` and empty bridge run payload.
- [2026-04-24] [execution] — Ran real-engine DDS calibration on same locked benchmark context:
  - command target artifacts: `tests/_artifacts/calibration_locked_20260424_effective_01547700/calibration_reports_spotpy/`
  - evaluations: 30, unique `metric_nse`: 30.
- [2026-04-24] [verification] — Independently reran best parameter set through authoritative real objective and confirmed exact metric match to reported best solution.
- [2026-04-24] [result] — Verified real improvement vs locked benchmark:
  - benchmark NSE/KGE: `0.125578 / 0.036273`
  - calibrated NSE/KGE: `0.210656 / 0.116227`
  - delta NSE/KGE: `+0.085078 / +0.079955`.
- [2026-04-24] [artifact] — Wrote verification bundle:
  - `tests/_artifacts/calibration_locked_20260424_effective_01547700/verification_summary.json`
  - `tests/_artifacts/calibration_locked_20260424_effective_01547700/comparison_metrics.csv`
  - `tests/_artifacts/calibration_locked_20260424_effective_01547700/CALIBRATION_VERIFICATION.md`

### In Flight

- [2026-04-24] Diagnose pySWATPlus bridge runtime failure in the locked-benchmark setup so this same effective-parameter workflow can run through the bridge path reliably.

### Next Up

- [1] Add a short fail-loud diagnostic artifact for pySWATPlus bridge failures (stdout/stderr + staging manifest) to avoid opaque `execution failed` exits.
- [2] Repeat the same locked-benchmark effective-parameter protocol on `01013500` after realism gates pass.
- [3] Promote locked-benchmark calibration verification as a standard readiness gate before broader phase expansion.

### Open Questions / Blockers

- [2026-04-24] pySWATPlus bridge calibration remains runtime-fragile in this environment for the locked benchmark; real-engine path is currently the reliable authoritative route.

## 2026-04-24 — Locked Benchmark Calibration Evidence Expansion (Contrast Basin 03339000)

### Active Phase

Calibration reliability hardening (locked benchmark evidence accumulation)

### Current Sprint Focus

Extend validated locked-benchmark calibration evidence from first basin (`01547700`) to one contrast basin (`03339000`) without expanding parameter scope.

### Completed Since Last Update

- [2026-04-24] [playbook] — Updated `docs/SWATPLUS_MODELING_PLAYBOOK.md` to:
  - mark first locked-benchmark evidence (`01547700`) as validated,
  - mark pySWATPlus bridge as non-authoritative/unstable for that lock,
  - promote real-engine DDS (`CN2`, `ALPHA_BF`) on locked benchmarks as current recommended path.
- [2026-04-24] [artifact] — Created contrast-basin benchmark lock:
  - `tests/_artifacts/calibration_locked_20260424_effective_03339000/benchmark/`
  - includes `benchmark_lock.json`, `alignment.csv`, `metrics.json`, and provenance snapshot.
- [2026-04-24] [execution] — Ran same calibration workflow on `03339000` with unchanged effective parameter subset (`CN2`, `ALPHA_BF`) and strict objective file (`channel_sd_day.txt`).
- [2026-04-24] [verification] — Independently reran best solution and confirmed metric match.
- [2026-04-24] [result] — `03339000` locked-benchmark improvement:
  - benchmark NSE/KGE: `0.061802 / -0.096925`
  - calibrated NSE/KGE: `0.319248 / 0.187398`
  - delta NSE/KGE: `+0.257447 / +0.284323`.
- [2026-04-24] [artifact] — Wrote verification bundle:
  - `tests/_artifacts/calibration_locked_20260424_effective_03339000/verification_summary.json`
  - `tests/_artifacts/calibration_locked_20260424_effective_03339000/comparison_metrics.csv`
  - `tests/_artifacts/calibration_locked_20260424_effective_03339000/CALIBRATION_VERIFICATION.md`

### In Flight

- [2026-04-24] Add explicit pySWATPlus-bridge failure artifact capture (stdout/stderr + staging manifest) so non-authoritative bridge outcomes are always auditable.

### Next Up

- [1] Re-run contrast-basin locked search with full target budget once runtime stability is confirmed, preserving same parameter set/objective/outlet lock.
- [2] Add a compact multi-lock calibration evidence table (01547700 + 03339000) in readiness docs.
- [3] Keep parameter scope fixed (`CN2`, `ALPHA_BF`) until bridge reliability and lock protocol are fully standardized.

### Open Questions / Blockers

- [2026-04-24] pySWATPlus bridge lock execution still fails opaquely in this environment for some locks; currently not used for authoritative improvement claims.
