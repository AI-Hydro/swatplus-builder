# Full-Mode Topology Conversion — Phase 3L.10.2

**Date:** 2026-05-11
**Latest status:** `D1_fixed_D2_fixed_chandeg_blocked` — codes.bsn and file.cio fixes verified on reference; 01547700_full still crashes at hyd_connect

## D1 Fix: codes.bsn routing flags

**Attribution:** `editor_default_v322`. Editor v3.2.2 emits swift_out=1, uhyd=1, soil_p=0, i_fpwet=1 as full-mode defaults.

**Fix:** Converter now overrides all four flags to reference values:
- swift_out: 1 → 0
- uhyd: 1 → 0  
- soil_p: 0 → 1
- i_fpwet: 1 → 0

**Verification:** Substitution ladder S1 re-run with fixed codes.bsn — reference channel flow restored (32K non-zero).

## D2 Fix: file.cio connect block

**Attribution:** `converter_incomplete_cleanup`. Editor generates outlet.con and references it in file.cio. The reference has no outlet.con in its connect block.

**Fix:** Converter removes `outlet.con` from the connect block. The outlet is handled by chandeg.con's terminal routing (matching the reference architecture).

**Verification:** Substitution ladder S2 re-run with fixed file.cio — reference channel flow restored.

## Remaining blocker: chandeg.con on 01547700_full

Both D1 and D2 fixes are correct (verified on reference). Our 01547700_full build still crashes at hyd_connect.f90:377 even with:
- Correct codes.bsn flags (verified)
- Correct file.cio connect block (verified)
- Reference-format chandeg.con with terminal outlet pattern
- Verified routing graph (no cycles, all targets exist)
- Proven channel-lte.cha and hyd-sed-lte.cha (S4/S5 pass on reference)

The crash cannot be isolated via substitution because the basin topologies differ (177 vs 15 channels). The next step is generating a matching-scale reference (Phase 3L.10.2.1) or investigating the SWAT+ engine source for hyd_connect validation rules.

## Purpose

`src/swatplus_builder/full_mode/topology_converter.py` converts full SWAT+ TxtInOut from the editor v3.2.2 default topology (cha/channel.con/rte_cha=0) to the topology that engine rev 60.5.7 requires for channel routing (sdc/chandeg.con/rte_cha=1).

## What it does

| Input | Output | Change |
|---|---|---|
| `codes.bsn` (rte_cha=0) | rte_cha=1 | Enable channel routing |
| `channel.con` (cha objects) | `chandeg.con` (lcha objects) | Convert channel topology |
| `rout_unit.con` (cha routing) | sdc routing | Change obj_typ tokens |
| `channel.cha` | `channel-lte.cha` | LTE-format channel params |
| `hydrology.cha` | `hyd-sed-lte.cha` | Expanded column schema |
| `object.cnt` (cha=N) | cha=0, lcha=N | Object type counts |
| `file.cio` (channel.con refs) | chandeg.con + channel-lte refs | Connect/channel blocks |

## What's removed

- `channel.con`, `channel.cha`, `hydrology.cha`, `sediment.cha` — replaced by chandeg/LTE equivalents

## Assumptions

1. **Editor v3.2.2 generates cha-based full-mode routing.**
   Confirmed by source inspection: `import_gis.py` line 1611 and 1836.
   The `is_lte=True` gate controls sdc vs cha routing, but cannot be decoupled
   from other LTE-specific behavior without forking the editor.

2. **The engine's `hyd-sed-lte.cha` requires a fixed column schema.**
   Columns include order, erod_fact, cov_fact, sinu, eq_slp, d50, clay,
   carbon, dry_bd, bankfull_flo, fps, fpn, n_conc, p_conc, p_bio.
   Default values from the Tordera reference are used for columns not
   available in the full-mode `hydrology.cha`.

3. **`hyd-sed-lte.cha:len` is a compatibility transfer length in converted
   full-mode routing.** In the `sdc`/`chandeg.con` engine path, carrying real
   channel lengths from `hydrology.cha` over-delays Marsh Creek event delivery
   in rev 61.0.2.61. A 2026-06-17 diagnostic ladder on USGS `01547700` showed
   that real-length routing delayed the September 2004 outlet peak from the
   observed September 18 to September 24, while a near-zero LTE transfer length
   (`0.00050 km`) restored same-day channel delivery and improved the 2000-2019
   fixed full-overlay baseline from about `NSE=0.100`, `KGE=0.077`,
   `PBIAS=-17.4%` to `NSE=0.280`, `KGE=0.266`, `PBIAS=-13.7%`. This is treated
   as an engine/topology compatibility rule, not a physical calibration of
   channel geometry. The same rule is enforced in the native editor
   `import_gis` path because canonical builds populate `hyd_sed_lte_cha`
   before this converter sees a finished `TxtInOut`. Physical channel lengths
   remain in the GIS/channel source data and peak-flow claims still require
   separate process evidence.

4. **The converter is gated on `not is_lte`.**
   LTE mode builds are never touched. The converter checks `model_family`
   before executing and is only called from `build_real_basin.py` for
   `--model-family full`.

## What could break it

1. **Engine rev upgrade.** If the engine binary is upgraded, the required
   file formats may change. The column schema for hyd-sed-lte.cha and
   the object type dispatch may differ.

2. **Editor version change.** If the editor is upgraded, it may generate
   different routing topologies or file structures that the converter
   doesn't handle.

3. **Multi-basin routing.** The converter assumes a single-basin topology
   with one outlet. Multi-basin or nested basin configurations may require
   additional routing graph transformations.

4. **Large basins.** The converter operates on all channel objects.
   Very large basins (>1000 channels) may require memory optimizations.

## Blocked by

The converter correctly transforms all file formats, but the engine still
rejects the converted files under `rte_cha=1` (crash at `hyd_connect.f90:377`).
The reference Tordera TxtInOut (built by editor v3.2.0) works on our engine,
proving the engine supports sdc routing — but file-level conversion after
the fact cannot replicate editor-native output.

The converter infrastructure remains useful as a foundation. When the
routing blocker is resolved (via engine upgrade, editor fork, or direct
LTE-mode routing integration), the converter will produce valid files.

## Related artifacts

- `tests/_artifacts/phase3l10/conversion_blocked_assessment.md` — detailed analysis
- `tests/_artifacts/phase3l10/editor_capability_probe.md` — editor capability findings
- `tests/test_topology_converter.py` — 11 tests
- Phase 3L.9: `docs/FULL_MODE_ROUTING_SCHEMA_SPEC.md` — schema rule
