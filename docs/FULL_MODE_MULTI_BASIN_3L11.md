# Full-Mode Multi-Basin Generalization — Phase 3L.11

**Date:** 2026-05-11
**Verdict:** `converter_generalizes` — 2 of 3 basins produce non-zero channel flow

## Per-basin results

| Basin | Channels | Channel flow | Max flo_out (m³/s) | Verdict |
|---|---|---|---|---|
| 01491000 Choptank River, MD | 33 | ✅ 4,188 non-zero days | 13,470 | `full_mode_channel_flow_nonzero` |
| 01547700 Loyalsock Creek, PA | 15 | ✅ 2,215 non-zero days | 7,268 | `full_mode_channel_flow_nonzero` |
| 01654000 Accotink Creek, VA | — | — | — | `full_mode_build_failed` |

## 01654000 failure analysis

Build failed at the **delineation realism gate**, not at the topology converter.
The area difference was -1.01% and IoU was 98.68% — both within acceptable bounds.
The failure was due to `avg_subbasin_area_too_small` (53 subbasins in 61.6 km²,
averaging ~1.16 km² per subbasin). This is a delineation parameter issue
(stream threshold), not a converter issue.

## What was verified

1. **D3 fix**: `file.cio` connect block position 13 correctly set to `chandeg.con`,
   position 7 correctly set to `null` — verified on both succeeding basins.
2. **D4 fix**: `aquifer.con` correctly converts `cha→sdc` — object type
   consistency across all routing files.
3. **Cross-basin consistency**: The converter works identically on two basins
   with different channel counts (15 vs 33) and different geographic regimes
   (Appalachian flashy vs Mid-Atlantic subdued).

## Converter assumptions confirmed

- `object.cnt` must keep `cha=0, lcha=N` (engine uses `sp_ob%chandeg` from `lcha` column)
- `chandeg.con` must be at connect block position 13 (not replacing channel.con at position 7)
- `aquifer.con` must use `sdc` routing type (not `cha`) for object type consistency
- `codes.bsn` must have `swift_out=0, uhyd=0, soil_p=1, i_fpwet=0`
- All four defects (D1-D4) are basin-independent — the converter handles them automatically
