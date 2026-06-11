# Calibration

swatplus-builder calibrates through the **locked-benchmark protocol**: lock a
baseline, search candidates on fresh copies behind a volume gate, promote the
best, and report only an independently verified rerun. The
[concept page](../concepts/locked-calibration.md) explains *why*; this page
shows *how*.

## The authoritative path

```
1. swat lock-benchmark     # snapshot baseline metrics + alignment CSV
       ↓
2. swat locked-calibrate   # real-engine DDS on effective parameters
       ↓                   # (calls verify automatically unless --skip-verify)
3. metrics reported        # delta NSE/KGE vs locked baseline, independently verified
```

`swat workflow run --calibrate` runs this whole chain for you. The standalone
commands exist for when you already have a `TxtInOut` and want to calibrate it
directly.

### Lock the baseline

```bash
swat lock-benchmark \
  --txtinout TxtInOut/ \
  --observed-csv observed.csv \
  --out-dir artifacts/locks/my_basin \
  --basin-id usgs_01547700
```

### Calibrate against the lock

```bash
swat locked-calibrate \
  --benchmark-dir artifacts/locks/my_basin/benchmark \
  --base-txtinout TxtInOut/ \
  --out-dir artifacts/calibration/my_basin \
  --parameters CN2,ALPHA_BF \
  --json
```

## Rules enforced by the toolchain

- **Restricted scope.** Parameters default to the *effective* set (`CN2`,
  `ALPHA_BF`) — no silent scope expansion. Expanding scope is an explicit,
  recorded choice.
- **Delta reporting.** Calibrated skill is always reported as a delta against
  the locked baseline (ΔNSE, ΔKGE).
- **Mandatory verification.** `verify_calibration` re-runs the best solution
  independently; its metrics — not the optimizer's — are authoritative.
- **`evaluate_run` is the only metric source.** All reported hydrologic metrics
  are routed through `evaluate_run` for parity.

## The Python API

```python
from swatplus_builder.calibration.locked_benchmark import (
    lock_benchmark,
    calibrate_against_lock,
    verify_calibration,
    build_readiness_table,
)

lock = lock_benchmark(txtinout_dir, obs_series, out_dir,
                      basin_id="usgs_01547700", outlet_gis_id=1)
evidence = calibrate_against_lock(lock, base_txtinout, out_dir,
                                  parameters=["CN2", "ALPHA_BF"])
result = verify_calibration(lock, evidence.best_solution_json, base_txtinout, out_dir)
rows = build_readiness_table(locks_root)
```

## The bridge path is non-authoritative

A secondary **pySWATPlus bridge** path exists
(`swat calibrate --calibration-engine pyswatplus`). It is **non-authoritative**
and fail-loud: on failure it writes a structured `bridge_failure_diagnostic.json`
(timestamp, traceback, staged-file manifest, failure stage) and exits non-zero.
Do not report raw bridge objective values — the bridge metric-parity layer
redirects reported metrics through `evaluate_run`, and the real-engine path is
the reliable authoritative route.

!!! tip "Readiness across a suite"
    `swat readiness-table --locks-root artifacts/locks/ --json` summarizes lock
    + calibration + verification status across many basins at once.

## Read next

- [Reading the evidence](reading-evidence.md) — interpret the calibrated bundle
- [Locked calibration protocol](../concepts/locked-calibration.md) — the why
