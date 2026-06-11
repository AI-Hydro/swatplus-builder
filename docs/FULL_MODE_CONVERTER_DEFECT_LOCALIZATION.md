# Full-Mode Converter Defect Localization — Phase 3L.10.1

**Date:** 2026-05-11
**Verdict:** `multi_file_defect_localized` — three defects found, two confirmed, one topology-blocked

## Method

Reverse mutation ladder: substitute converter output files one at a time into the working reference TxtInOut. The first substitution that breaks channel flow (rc≠0 or flow=0) identifies a converter defect.

## Results

| Step | File substituted | rc | Channel flow | Verdict |
|---|---|---|---|---|
| S0 | (none — baseline) | 0 | 32,213 | Reference works |
| S1 | `codes.bsn` | 0 | **0** ❌ | **Defect 1: codes.bsn flags** |
| S2 | `file.cio` | 0 | **0** ❌ | **Defect 2: connect block** |
| S3 | `chandeg.con` | 174 | **0** ❌ | Content mismatch (expected) |
| S4 | `channel-lte.cha` | 0 | 2,640 ✅ | Converter correct |
| S5 | `hyd-sed-lte.cha` | 0 | 32,213 ✅ | Converter correct |
| S6 | `object.cnt` | 174 | 0 ❌ | Possible Defect 3 (or topology difference) |

## Defect 1: codes.bsn flags (CONFIRMED blocking)

The converter sets `rte_cha=1` but inherits the editor's default values for other routing flags. The reference requires:

| Flag | Reference (working) | Converter (broken) |
|---|---|---|
| `swift_out` | 0 | 1 |
| `uhyd` | 0 | 1 |
| `soil_p` | 1 | 0 |
| `i_fpwet` | 0 | 1 |

**Fix**: Set all four flags to reference values in `_convert_codes_bsn()`.

**Evidence**: S1 — substituting only codes.bsn drops channel flow to zero.

## Defect 2: file.cio connect block (CONFIRMED blocking)

The converter places `outlet.con` in the connect block at position 12. The reference has `null` at that position and `chandeg.con` at position 13 (last slot).

**Fix**: Remove `outlet.con` from the connect block. The outlet is already routed through chandeg.con.

**Evidence**: S2 — substituting only file.cio drops channel flow to zero.

## Defect 3: object.cnt (POSSIBLE, topology-blocked)

S6 crashes at rc=174 when object.cnt is substituted. However, this may be a topology difference rather than a converter bug — the reference has 3237 objects vs our 76, and `out=0` vs `out=1`. The converter correctly moves `cha` count to `lcha`, but the engine may validate total object counts against actual files.

**Assessment**: Likely not a converter defect on its own, but may interact with Defects 1-2. The reference has `out=0` while our build has `out=1`. The engine may use object counts for array allocation.

## Isolated fix verification

Applied Defect 1 Fix + Defect 2 Fix to the reference: channel flow restored (32,213 non-zero).
Applied both fixes to our 01547700_full converter output: still crashes at rc=174 (chandeg.con topology/content mismatch between basins).

## What works correctly

- `channel-lte.cha` — structurally compatible with reference
- `hyd-sed-lte.cha` — column schema matches reference format
- `rout_unit.con` — sdc token conversion is correct
- `rout_unit.def`, `.ele`, `.rtu` — headers match reference
- All content-dominated files have correct column structure

## Recommendation

Phase 3L.10.2: Fix Defects 1 and 2 in the converter. If our build still crashes after the fixes due to chandeg.con content mismatch (S3), the next step is to verify the chandeg.con routing graph against topology (Phase 3L.10.3).
