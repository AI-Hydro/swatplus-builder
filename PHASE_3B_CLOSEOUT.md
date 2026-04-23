# Phase 3B Closeout — Artifact System & Validation Layer

Date: 2026-04-23  
Roadmap reference: `ROADMAP.md` §3B.1–3B.5  
Status: Complete

## What Was Built

Phase 3B delivered an artifact-first validation layer:

1. Typed artifact schemas + deterministic content hashing.
2. Local filesystem `ArtifactStore` (`write/read/exists/query/lineage`).
3. `swat validate --basins <json>` command with artifact writes and report outputs.
4. Curated basin suite file `basins/curated_v1.json`.
5. Benchmark reporting with cross-basin aggregation and comparison plot generation.

## Exit Criteria Evidence (Roadmap 3B.5)

### 1) Artifact store operational; every run from here on writes artifacts

- Implemented:
  - `src/swatplus_builder/artifacts/models.py`
  - `src/swatplus_builder/artifacts/hashing.py`
  - `src/swatplus_builder/artifacts/store.py`
- Verified:
  - `tests/test_artifact_models.py`
  - `tests/test_artifact_hashing.py`
  - `tests/test_artifact_store.py`

### 2) Curated basin suite defined and stored in repo

- Implemented:
  - `basins/curated_v1.json` (6 representative basins with bbox/window/NSE floor/notes)
- Verified:
  - `tests/test_curated_basins.py`

### 3) `swat validate` produces complete benchmark report end-to-end

- Implemented:
  - CLI command in `src/swatplus_builder/cli.py`
  - runner in `src/swatplus_builder/validation/runner.py`
- Local E2E command:
  - `python -m swatplus_builder.cli validate --basins basins/curated_v1.json --artifacts-root tests/_artifacts/validation_curated --runs-root tests/_artifacts/validation_curated_work --engine-version swatplus-61.0.6`
- Generated report artifacts:
  - `tests/_artifacts/validation_curated/validation_reports/summary.csv`
  - `tests/_artifacts/validation_curated/validation_reports/summary.md`
  - `tests/_artifacts/validation_curated/validation_reports/benchmark_report.md`
  - `tests/_artifacts/validation_curated/validation_reports/benchmark_summary.json`
  - `tests/_artifacts/validation_curated/validation_reports/comparison_metrics.png`
  - `tests/_artifacts/validation_curated/validation_reports/comparison_metrics.pdf`

### 4) Content-addressed caching operational (identical config skips engine)

- Verified by test:
  - `tests/test_validation_runner.py::test_run_validation_uses_cache_on_second_run`
- Verified by repeated CLI run:
  - First run: `cache_hits=0`
  - Second run (identical inputs): `cache_hits=6`

## Verification Summary

- `pytest -q tests/test_artifact_models.py tests/test_artifact_hashing.py tests/test_artifact_store.py tests/test_validation_runner.py tests/test_cli_validate.py tests/test_curated_basins.py` -> pass.
- Additional compatibility checks:
  - `pytest -q tests/test_cli_inspect.py tests/test_output_metadata.py tests/test_output_eval.py` -> pass.

## Deviations / Notes

1. The default validate executor currently uses `orchestrate.run_pipeline` (alpha path) and may not emit full hydrological metrics for every basin; benchmark reports still generate structurally and preserve cache/report integrity.
2. Real-engine metric completeness remains an execution-backend quality concern, not an artifact-system blocker.

## Lessons For Phase 3C

1. Artifact schemas and cache keys now provide a stable substrate for calibration sampling and warm starts.
2. Calibration runner should consume the same `ArtifactStore` contract rather than introducing a parallel results structure.
3. Maintain strict separation between structural health checks and skill metrics to avoid masking runtime regressions.

