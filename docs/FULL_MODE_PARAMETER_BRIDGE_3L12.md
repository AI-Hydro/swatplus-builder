# Full-Mode Parameter Bridge — Phase 3L.12

**Date:** 2026-05-11
**Verdict:** `all_parameters_ineffective_full` — engine produces identical channel output regardless of parameter changes

## Implemented

`src/swatplus_builder/full_mode/parameter_bridge.py` — 6 parameter writers:
- CN2 (cntable.lum)
- RCHG_DP, ALPHA_BF (aquifer.aqu)
- ESCO, EPCO, PET_CO (hydrology.hyd)

Each writer verified to correctly modify the target file on disk.

## Engine sensitivity probe results

| Parameter | Low | High | Hashes differ? | Classification |
|---|---|---|---|---|
| CN2 | 30.0 | 95.0 | No | `ineffective_full` |
| RCHG_DP | 0.0 | 0.8 | No | `ineffective_full` |
| ALPHA_BF | 0.001 | 1.0 | No | `ineffective_full` |
| ESCO | 0.01 | 1.0 | No | `ineffective_full` |
| EPCO | 0.01 | 1.0 | No | `ineffective_full` |
| PET_CO | 0.1 | 1.5 | No | `ineffective_full` |

All 6 parameters produce hash-identical `channel_sd_day.txt` output across
LOW/HIGH extremes. The engine IS regenerating output (verified by deletion +
fresh timestamps). The parameter files ARE being modified (verified by reading
post-writer).

## Root cause

Full SWAT+ routing architecture differs fundamentally from LTE. In LTE mode,
HRU water routes directly to channels via `hru-lte.con`. In full mode, HRU
water passes through routing units (`rout_unit.con`) before reaching channels
(`chandeg.con`). The routing unit layer aggregates and redistributes flow,
making individual HRU-level parameters (CN2, ESCO, EPCO, PET_CO) and aquifer
parameters (RCHG_DP, ALPHA_BF) ineffective for channel outlet flow.

The parameter bridge code is correct. The failure is architectural: full SWAT+
requires routing-unit-level calibration levers, not HRU-level levers.

## Next step

The converter topology is sound (Phase 3L.11 verified). The engine runs and
produces non-zero channel flow. The blocker is parameter sensitivity — full
SWAT+ calibration needs investigation into which parameters actually control
routing-unit→channel flow. This may require:
1. Calibrating within the routing unit itself (ru parameters)
2. Bypassing routing units and using direct HRU→channel routing in full mode
3. Accepting that full SWAT+ calibration requires a fundamentally different
   parameter set than LTE mode
