# Locked calibration protocol

This is the strongest single methods idea in the project:

!!! quote ""
    **Final calibration metrics never come from the optimizer.**
    They come from an independent rerun of a locked artifact.

Most reported calibration numbers in practice are *optimizer-trajectory*
metrics — the best objective value the search happened to see. Those are easy
to inflate and hard to reproduce. swatplus-builder structurally forbids it.

## The chain of custody

```
1. LOCK       baseline TxtInOut + observed flow sealed with content hashes
                 │
2. SEARCH     each candidate runs on a fresh copy; the volume gate runs first
                 │
3. PROMOTE    the best gate-passing candidate is locked as the calibrated TxtInOut
                 │
4. VERIFY     an independent, clean rerun of the locked calibrated artifact
                 │
5. AUTHORITY  only the verified-rerun metrics are final; candidate metrics are
              structurally disallowed as reported values
```

### 1. Lock

`lock_benchmark` snapshots the baseline `TxtInOut` and the observed discharge
series, computes baseline metrics, and seals everything with content hashes
into a benchmark directory. After this point the baseline cannot silently
drift — any change to the inputs is detectable.

### 2. Search

Calibration (real-engine DDS, restricted by default to effective parameters
such as `CN2` and `ALPHA_BF`) evaluates each candidate on a **fresh copy** of
the inputs. A **volume gate runs first**: a candidate that fails gross water
balance is rejected before its skill metric is ever considered. This prevents
the optimizer from chasing a good-looking NSE that is built on a broken mass
balance.

### 3. Promote

The best candidate that passes the gates is promoted: its parameter set is
written into a calibrated `TxtInOut`, which is then itself locked.

### 4. Verify

`verify_calibration` re-runs the promoted, locked artifact from clean — a
*separate* execution from the calibration loop. The metrics from this rerun are
the only ones eligible to be reported.

### 5. Authority

The evidence bundle records the verified-rerun metrics as authoritative and
records the calibration-loop ("candidate") metrics as **non-authoritative**.
Reporting a candidate metric as a final result is exactly the overclaiming the
governance layer exists to block.

## Delta reporting

Calibrated skill is always reported as a **delta against the locked baseline**
(ΔNSE, ΔKGE), not as an absolute number in isolation. This keeps "the
calibration improved the model" separate from "the model is good" — two claims
that gate independently.

## Why the gates run *inside* the loop

Putting the volume gate before the skill metric means the search cannot be
rewarded for physically implausible solutions. The locked verification at the
end means the search cannot be rewarded for non-reproducible ones. Together
they make the reported number both *physically screened* and *independently
reproduced*.

## Where this lives in the code

`src/swatplus_builder/calibration/locked_benchmark.py` —
`lock_benchmark`, `calibrate_against_lock`, `verify_calibration`,
`build_readiness_table`. The real-engine DDS path is in
`calibration/real_engine.py` and `calibration/diagnostic_calibrator.py`.

## Read next

- [Calibration (guide)](../guide/calibration.md) — running it end to end
- [The evidence bundle](evidence-bundle.md) — where provenance is recorded
- [Claim governance](claim-governance.md) — how verified metrics feed the tier
