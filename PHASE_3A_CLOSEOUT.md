# Phase 3A Closeout — Hardening

Date: 2026-04-23  
Roadmap reference: `ROADMAP.md` §3A.1–3A.5  
Status: Complete

## What Was Built

Phase 3A delivered the hardening foundation across five tracks:

1. CI routing regression gate (`tests/test_ci_routing_regression.py` + GitHub Actions `routing-regression` job).
2. Metadata persistence (`src/swatplus_builder/output/metadata.py`) and inspect command (`swat inspect <run_path>`).
3. Soil realism flags (`soil_mode`, `pct_fallback_soils`) with warnings and figure annotation/watermarking.
4. Large-basin pre-engine guardrails in runner + CLI controls (`--max-hrus`, `--max-subbasins`, `--auto-adjust/--no-auto-adjust`).
5. Documentation and decision trail (`PROGRESS.md`, `DECISIONS.md`, `README.md`).

## Exit Criteria Evidence (Roadmap 3A.5)

### 1) CI gate running green on 2–3 basins

- Implemented in:
  - `.github/workflows/ci.yml` (routing-regression job)
  - `tests/test_ci_routing_regression.py` (3 representative basins)
- Local proof run (real path enabled):
  - `SWATPLUS_BUILDER_RUN_ROUTING_REGRESSION=1 pytest -q tests/test_ci_routing_regression.py -s`
  - result: pass (exit code 0)

### 2) Every run produces complete `metadata.json`

- Implemented in:
  - `src/swatplus_builder/output/metadata.py`
  - `examples/real_basin_marsh_creek.py` (metadata write on run completion)
  - `src/swatplus_builder/cli.py` (`inspect` subcommand)
- Verified by tests:
  - `tests/test_output_metadata.py`
  - `tests/test_cli_inspect.py`
  - `tests/test_output_eval.py` (outlet diagnostics wiring)

### 3) Soil fidelity flags visible in outputs and figures

- Implemented in:
  - `examples/real_basin_marsh_creek.py` (soil mode + fallback ratio + threshold warning)
  - `src/swatplus_builder/output/plots/utils.py` (quality flag + watermark annotation)
  - `src/swatplus_builder/output/plots/*.py` and `wrapper.py` (metadata propagation)
  - `README.md` (soil fidelity semantics)
- Verified by tests:
  - `tests/test_output_plots_utils.py`

### 4) Large-basin paths fail fast or auto-adjust; no silent hangs

- Implemented in:
  - `src/swatplus_builder/run/swatplus.py` (`_check_size_guardrails`)
  - `src/swatplus_builder/cli.py` (`--max-hrus`, `--max-subbasins`, `--auto-adjust/--no-auto-adjust`)
- Verified by tests:
  - `tests/test_run_swatplus.py::TestLargeBasinGuardrails::*`

## Verification Runs

- `SWATPLUS_BUILDER_RUN_ROUTING_REGRESSION=1 pytest -q tests/test_ci_routing_regression.py -s` -> pass.
- `pytest -q tests/test_run_swatplus.py tests/test_output_plots_utils.py tests/test_output_eval.py tests/test_output_metadata.py tests/test_cli_inspect.py` -> pass (1 expected opt-in skip for real-engine smoke).

## Deviations From Plan

1. NSE floor strictness was scoped to the structural CI basin instead of all CI basins (recorded in `DECISIONS.md`) to avoid false-negative hard failures on uncalibrated basins while preserving structural regression detection.
2. `.gitignore` required corrective narrowing (`output/` -> `/output/`) because it hid legitimate package source under `src/swatplus_builder/output/`.

## Lessons For Phase 3B

1. Artifact/metadata paths must be protected by tests and ignore-rule checks; hidden source files can invalidate reproducibility.
2. Structural regression gates should remain orthogonal to calibration skill metrics.
3. Opt-in strictness flags (`--no-auto-adjust`) are valuable for CI and expert workflows while keeping defaults compatible for interactive users.

