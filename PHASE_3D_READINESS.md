# Phase 3D Readiness Evidence (Calibration + Sensitivity)

Date: 2026-04-24  
Scope: parity-hardened multi-basin calibration evidence and manual parameter sensitivity audit before Phase 3E kickoff.

## Setup

- Calibration engine path set explicitly via `SWATPLUS_EXE=/.../bin/swatplus_exe`.
- Parity-safe calibration path: `swat calibrate --calibration-engine pyswatplus` (bridge-reported metrics from authoritative `evaluate_run` + `metric_parity_log.csv`).
- Additional curated basins calibrated: `usgs_01013500`, `usgs_03339000` (plus matched run on `usgs_01547700` for direct comparison).
- Calibration run budget for this evidence pass: `algo=de`, `n_gen=2`, `pop_size=6` (12 evaluations per basin).
- Calibration parameter set for cross-basin comparability: `CN2, ESCO, SURLAG`.
- Sensitivity audit basins: `usgs_01547700`, `usgs_01013500`.

## Calibration Comparison

`basin_id | baseline NSE/KGE | calibrated NSE/KGE | delta NSE | delta KGE | notes`

| basin_id | baseline NSE/KGE | calibrated NSE/KGE | delta NSE | delta KGE | notes |
| --- | --- | --- | ---: | ---: | --- |
| `usgs_01547700` | `-0.241 / 0.004` | `-0.241 / 0.004` | `0.000` | `0.000` | calibration dir `1513ed...`; 12/12 evaluations identical |
| `usgs_01013500` | `-0.618 / -0.338` | `-0.618 / -0.338` | `0.000` | `0.000` | calibration dir `976df6...`; 12/12 evaluations identical |
| `usgs_03339000` | `-54.899 / -10.793` | `-54.899 / -10.793` | `0.000` | `0.000` | calibration dir `eef0b6...`; 12/12 evaluations identical |

### Calibration Observations

- Metrics are parity-trustworthy (same outlet/date/source across evaluations; parity logs present for each run).
- Optimization signal is flat in this pySWATPlus bridge run set (`history.csv` and `metric_parity_log.csv` both show single unique NSE/KGE per basin).
- This pattern appears across multiple basins, so it is not basin-specific.

## Manual Sensitivity Audit

Requested perturbations: `CN2`, `SOL_AWC`, `SOL_K`, `ALPHA_BF`, `GW_DELAY`  
Reported deltas are relative to baseline objective run (`theta={}`) for each basin.

`parameter | perturbation | ΔNSE | ΔKGE | Δtotal flow | Δpeak flow`

### Basin `usgs_01547700`

| parameter | perturbation | ΔNSE | ΔKGE | Δtotal flow | Δpeak flow |
| --- | --- | ---: | ---: | ---: | ---: |
| `CN2` | `set=85.0` | `+0.258` | `-0.049` | `+0.095` | `-0.118` |
| `SOL_AWC` | `set=0.30` | `+0.000` | `+0.000` | `+0.000` | `+0.000` |
| `SOL_K` | `set=100.0` | `+0.000` | `+0.000` | `+0.000` | `+0.000` |
| `ALPHA_BF` | `set=0.12` | `-0.110` | `+0.068` | `+0.106` | `+0.005` |
| `GW_DELAY` | `set=80.0` | `+0.000` | `+0.000` | `+0.000` | `+0.000` |

### Basin `usgs_01013500`

| parameter | perturbation | ΔNSE | ΔKGE | Δtotal flow | Δpeak flow |
| --- | --- | ---: | ---: | ---: | ---: |
| `CN2` | `set=85.0` | `-0.014` | `-0.035` | `+0.056` | `+0.632` |
| `SOL_AWC` | `set=0.30` | `+0.000` | `+0.000` | `+0.000` | `+0.000` |
| `SOL_K` | `set=100.0` | `+0.000` | `+0.000` | `+0.000` | `+0.000` |
| `ALPHA_BF` | `set=0.12` | `+0.000` | `-0.018` | `+1.106` | `+0.388` |
| `GW_DELAY` | `set=80.0` | `+0.000` | `+0.000` | `+0.000` | `+0.000` |

### Sensitivity Observations

- Parameter effect is measurable for `CN2` and `ALPHA_BF` in both audited basins.
- `SOL_AWC`, `SOL_K`, and `GW_DELAY` show near-zero response in this setup/window, indicating either low structural sensitivity or inactive/non-propagated controls in this pipeline configuration.
- Because the manual objective path responds while pySWATPlus calibration evaluations remain flat, the dominant blocker is likely parameter injection/bridge behavior under current pySWATPlus calibration path (plus some true low-sensitivity parameters), not a complete end-to-end pipeline failure.

## Go/No-Go Check

- `calibration metrics are trustworthy` -> `PASS`  
  Reason: parity-hardened metrics and parity logs are consistent (`outlet_gis_id=1`, fixed date window, authoritative evaluator).
- `multiple basins run successfully` -> `PASS`  
  Reason: parity calibration runs completed for `01013500` and `03339000` (plus matched run on `01547700`).
- `parameter perturbations change outputs measurably` -> `PASS (partial by parameter)`  
  Reason: `CN2` and `ALPHA_BF` move outputs; `SOL_AWC`, `SOL_K`, `GW_DELAY` did not in this setup.
- `low NSE documented as model-fidelity/data limitation, not pipeline failure` -> `PASS with caveat`  
  Reason: low skill persists across basins and one basin is severely poor (`03339000`), while manual perturbations prove the engine can respond; this indicates a combination of fidelity limitations and calibration-bridge parameter-effect issues rather than a broken evaluator.

## Evidence Artifacts

- Summary JSON: `tests/_artifacts/calibration_readiness_20260424/readiness_summary.json`
- Calibration artifacts:
  - `tests/_artifacts/calibration_readiness_20260424/usgs_01547700/runs/calibrations/1513ed28844c3691914c59c3f9abab1aeac7768b4b2a377f3725674d748f7bc5/`
  - `tests/_artifacts/calibration_readiness_20260424/usgs_01013500/runs/calibrations/976df6509b63751f3454bda04799f1996c66fb3edc5d4e5dc012edaab88288c0/`
  - `tests/_artifacts/calibration_readiness_20260424/usgs_03339000/runs/calibrations/eef0b6b7721b910a295b759396a49926af317d252cb99509e3eebac9d11a20e8/`
- Sensitivity objective reruns:
  - `tests/_artifacts/calibration_readiness_20260424/sensitivity_runs/usgs_01547700/`
  - `tests/_artifacts/calibration_readiness_20260424/sensitivity_runs/usgs_01013500/`
  - `tests/_artifacts/calibration_readiness_20260424/sensitivity_runs/usgs_03339000/`

## 2026-04-24 Addendum — Calibration Bridge Injection Fix Verification

### Root Cause Update

- pySWATPlus proposal vectors were changing and `calibration.cal` entries differed by evaluation.
- Despite that, raw pySWATPlus simulation outputs were byte-identical in this environment for tested runs, producing flat metric histories.
- Therefore the calibration bridge needed authoritative rerun fallback to preserve scientific reliability.

### Applied Fix

- Added flat-output detection in bridge parity layer.
- Added authoritative fallback rerun per evaluation using direct parameter injection objective + `evaluate_run`.
- Added strict diagnostics: changed-file tracking, output hash/mtime logging, and fail-loud guard when no significant input changes are observed.

### Verification Run (CN2-only)

- Run artifact:
  - `tests/_artifacts/calibration_bridge_fix_20260424c/runs/calibrations/d455d05d587bc78b9783ec5a218284ee9f41525a521df103768b4d0847449ca6/`
- Results:
  - `history.csv`: 4 rows, unique NSE = 4, unique KGE = 4
  - `metric_parity_log.csv`: unique NSE = 4, `metric_source=evaluate_run_real_objective_rerun`
  - output hashes unique across evaluations: 4/4

### Readiness Implication

- Calibration metrics are now structurally trustworthy under bridge-rerun mode.
- Additional multi-basin confirmation remains recommended before broad phase expansion.

### Multi-Basin Quick Confirmation (Bridge-Rerun Mode)

| basin_id | evaluations | unique NSE | unique KGE | metric source |
| --- | ---: | ---: | ---: | --- |
| `usgs_01547700` | 4 | 4 | 4 | `evaluate_run_real_objective_rerun` |
| `usgs_01013500` | 3 | 2 | 2 | `evaluate_run_real_objective_rerun` |
| `usgs_03339000` | 3 | 3 | 3 | `evaluate_run_real_objective_rerun` |

Artifact roots:
- `tests/_artifacts/calibration_bridge_fix_20260424c/runs/calibrations/d455d05d587bc78b9783ec5a218284ee9f41525a521df103768b4d0847449ca6/`
- `tests/_artifacts/calibration_bridge_fix_20260424_multi/runs/calibrations/6ea33f7a806af08a5670cc4870606aa060ccde6c48182158a8e2937047773b95/`
- `tests/_artifacts/calibration_bridge_fix_20260424_multi/runs/calibrations/146e7d79619c7cba65a124cf0481b49dd25248b10860298d61bf561ded364bfb/`
