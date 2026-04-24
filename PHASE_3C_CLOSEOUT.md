# Phase 3C Closeout — Revised Calibration Path

Date: 2026-04-23  
Scope authority: `CALIBRATION_PLAN_REVISED.md` (supersedes legacy Phase 3C text in `ROADMAP.md`)

## What was built

1. pySWATPlus calibration runtime and bridge
- Runtime guards for `pySWATPlus`, `pymoo`, `SALib`.
- Typed `Calibrator` bridge with calibration artifacts persisted under:
  - `runs/calibrations/<hash>/history.csv`
  - `runs/calibrations/<hash>/summary.md`
  - `runs/calibrations/<hash>/best_solution.json`
- CLI integration:
  - `swat calibrate --calibration-engine pyswatplus ...`

2. Registry compatibility
- Parameter registry extended with pySWATPlus-compatible `change_type`.
- Conversion helpers to pySWATPlus parameter/bounds dicts.

3. Sensitivity bridge
- `swat sensitivity` command with artifact persistence.

4. Diagnostic layer
- Typed rule engine + CLI `swat diagnose`.
- Rule-based hypotheses for peak lag, volume bias, baseflow/flashiness, snow timing, etc.

5. Calibration presets (3C.6)
- `--preset quick|standard|thorough` added to `swat calibrate`.

6. Metric parity hardening (critical)
- Bridge now computes reported calibration metrics from authoritative `evaluate_run` for each evaluation.
- Added `metric_parity_log.csv` with per-eval alignment and metric stats:
  - `aligned_days`
  - `obs_mean/std/min/max`
  - `sim_mean/std/min/max`
  - `first_date`, `last_date`
  - `outlet_gis_id`
  - `bridge_reported_nse`, `bridge_reported_kge`
  - `pyswatplus_raw_objective_nse` (traceability only)

## Revised 3C.7 evidence run

Curated-basin quick preset run completed on pySWATPlus path:
- Basin: `usgs_01547700`
- Engine: `pyswatplus`
- Preset: `quick`
- Evaluations: `160`
- Artifact root:
  - `tests/_artifacts/calibration_metric_parity_quick_20260423/runs/calibrations/d445b749d0d5b65dad7deb6d5ed70be1c0cd15e4b74af5becf0e2f3ecbaeb65d`
- Parity log:
  - `tests/_artifacts/calibration_metric_parity_quick_20260423/runs/calibrations/d445b749d0d5b65dad7deb6d5ed70be1c0cd15e4b74af5becf0e2f3ecbaeb65d/metric_parity_log.csv`

## Exit-criteria status (revised Phase 3C)

1. `swat calibrate` operational via pySWATPlus  
Status: Met

2. Parameter registry wired for pySWATPlus input semantics  
Status: Met

3. Sensitivity bridge available (`swat sensitivity`)  
Status: Met

4. Diagnostics available (`swat diagnose`)  
Status: Met

5. Preset workflows available (`quick`, `standard`, `thorough`)  
Status: Met

6. Curated-basin end-to-end calibration evidence on pySWATPlus path  
Status: Met (with metric parity enforced in reporting layer)

7. Remaining risk
- Raw pySWATPlus objective values may remain numerically distorted for this setup.
- Mitigation in place: authoritative bridge metric pass + parity logs.
- Follow-up recommended: investigate low parameter responsiveness in the current one-year setup.

## Tests and verification added

- `tests/test_calibration_calibrator.py`
  - parity log schema + metric overwrite guard
- `tests/test_cli_calibrate.py`
  - preset behavior + pySWATPlus CLI path

Verified locally:
- `pytest -q tests/test_calibration_calibrator.py tests/test_cli_calibrate.py`

