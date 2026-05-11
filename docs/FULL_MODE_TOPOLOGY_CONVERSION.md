# Full-Mode Topology Conversion — Phase 3L.10

**Date:** 2026-05-11
**Latest status:** `cha_to_sdc_conversion_implemented_routing_blocked_by_engine`

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

3. **The converter is gated on `not is_lte`.**
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
