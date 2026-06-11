# Full SWAT+ Engine Compatibility Audit

**Date:** 2026-05-10
**Phase:** 3L.8
**Classification:** `reference_runs_with_builder_engine`

## Verdict

The official Tordera reference TxtInOut (built by SWAT+ editor v3.2.0 for engine rev 61.0.2.61) **runs successfully on our builder's engine** (rev 60.5.7). Channel flow is produced (32,213 non-zero flo_out values). This proves the engine CAN route water from routing units to channels. The failure in `01547700_full` is caused by **builder full-routing generation incompleteness**, not engine/editor version mismatch.

## Evidence

| Engine | TxtInOut | rc | Channel flow | Notes |
|---|---|---|---|---|
| Builder engine (rev 60.5.7) | Tordera reference (v3.2.0, rev 61) | 0 | ✅ 32,213 non-zero | Reference works on our engine |
| Builder engine (rev 60.5.7) | 01547700_full (v3.2.2, rev 60.5.7) | 0 | ❌ All zeros | Our build fails on same engine |
| Builder engine (rev 60.5.7) | 01547700_full + sdc routing | 174 | ❌ Crash | `sdc` not supported on rev 60.5.7 |

## Key structural differences (reference vs our build)

| Component | Reference (Tordera) | Our build (01547700_full) |
|---|---|---|
| rout_unit.con rows | 354 with multi-entry quads (tot/sur/rhg) | 15 with single tot entries |
| rout_unit.def | elem_tot=2 (positive + negative IDs) | elem_tot=1 |
| rout_unit.ele | Multiple HRUs per RU, fractional areas | 1 HRU per RU, frac=1.0 |
| Channel routing type | sdc (straight-to-drainage) | cha (channel) |
| object.cnt lcha | 177 | 0 |
| object.cnt cha | 0 | 15 |
| object.cnt rtu | 354 | 15 |
| object.cnt aqu | 67 | 30 |

## Fix-attempt history

| Attempt | Result |
|---|---|
| Add rhg entries to rout_unit.con | Engine runs, zero channel flow |
| Change cha → sdc | Engine crashes (rc=174) |
| rout_unit.def: 2 elements (positive + negative) | Zero channel flow |
| Direct HRU→channel in hru.con | Zero channel flow |
| Negative outlet IDs in rout_unit.def | Zero channel flow |

## What this means

1. **Engine CAN route water to channels** — proven by reference run
2. **`sdc` not available on our engine** — crashes at `hyd_connect.f90`
3. **Our rout_unit→cha connection is broken** — editor v3.2.2 generates files that don't connect
4. **The fix is on the builder side** — generate routing files that the engine accepts

## Recommended next path

**Implement rout_unit→channel routing in the builder's post-processing.** The reference proves the engine can route RU→channel when the routing files are correct. Options:

1. **Writer fix (preferred)**: Post-process editor-generated rout_unit files to add the missing `cha` routing connections that the engine needs. The reference format provides the template.
2. **Engine bundling**: Bundle engine rev 61.0.2.61 and use `sdc` routing — bypasses the cha connectivity issue but introduces a new engine dependency.
3. **Direct HRU→channel**: Investigate why `hru.con` with `obj_typ=cha` is ignored in full mode — may require a different column or object type.

## Artifacts

- `multibasin_test/tordera_ref_1yr/` — Reference TxtInOut run on builder engine (WORKING)
- `multibasin_test/01547700_full/reports/rout_unit_root_cause.md` — Detailed root cause analysis
- `tests/_artifacts/phase3l8/run_tordera_builder_engine/` — Engine run logs
- `tests/_artifacts/phase3l8/audit.json` — Machine-readable verdict
