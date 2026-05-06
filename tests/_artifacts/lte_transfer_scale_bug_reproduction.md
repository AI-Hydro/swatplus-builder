# SWAT+ LTE hru_lte → channel transfer scale bug reproduction

**SWAT+ version:** v2023.60.5.7 (Rev 2023.60.5.7, modular build)
**SWAT+ Editor version:** v3.2.2+ed60db0
**Date:** 2026-05-06

## Summary

Evidence strongly indicates an LTE `hru_lte`-to-channel transfer scaling defect
in SWAT+ v2023.60.5.7. The engine computes channel inflow from HRU water yield
as:

```
channel_inflow_m3 = water_yield_mm × 1000 × HRU_area_ha   (observed)
```

The correct computation should be:

```
channel_inflow_m3 = water_yield_mm × 10 × HRU_area_ha     (expected)
                   = water_yield_mm ÷ 1000 × HRU_area_ha × 10000
                   = water_yield_m  × HRU_area_m2
```

The factor of 100× (1000 ÷ 10) is consistent across all 40 channels in a
real basin. The bug was detected in a USGS 01654000 (Accotink Creek, VA)
model with 40 HRU-LTE objects, 40 channels, and 1 outlet.

## Reproduction

### Environment

- Basin: USGS 01654000 (Accotink Creek near Annandale, VA)
- 40 HRU-LTE objects → 40 channels → 1 outlet (CH24)
- Area: 61.436 km²
- Simulation: 2015-01-01 to 2015-12-31
- Weather: GridMET, 25 stations
- Soils: gNATSGO (SDA)

### Observed behavior (uncorrected)

Channel hru_lte inflow (from `hydin_yr.txt`) is exactly 100× the HRU water
yield volume computed from `hru-lte_wb_yr.txt` × `hru-lte.hru` area:

| HRU | Area (ha) | Water Yield (mm) | Expected Vol (m³) | Channel Inflow (m³) | Ratio |
|-----|-----------|-------------------|--------------------|---------------------|-------|
| 1   | 361.021   | 1146.210          | 4,138,062          | 413,806,050         | 100.0 |
| 2   | 201.032   | 1146.210          | 2,304,240          | 230,424,690         | 100.0 |
| 3   | 156.923   | 1150.023          | 1,804,641          | 180,465,490         | 100.0 |
| 4   | 484.288   | 1150.023          | 5,569,316          | 556,942,780         | 100.0 |
| ... | ...       | ...               | ...                | ...                 | 100.0 |
| 40  | 61.320    | 1512.850          | 927,673            | 92,767,880          | 100.0 |

**All 40 ratios: min=99.99995, max=100.00005, mean=100.00000**

Basin totals:
- HRU water yield: 72,092,329 m³
- Channel hru_lte inflow sum: 7,209,232,207 m³
- Ratio: 100.0

Consequence:
- Simulated mean discharge at outlet: 213.95 m³/s
- Observed mean discharge: 0.89 m³/s
- NSE: -81,729

### After correction (frac=0.01 in hru-lte.con)

Setting `hru-lte.con` connection fraction to 0.01 cancels the engine's ×100:

| HRU | Expected Vol (m³) | Corrected Channel Inflow (m³) | Ratio |
|-----|--------------------|-------------------------------|-------|
| 1   | 4,138,062          | 4,138,061                     | 1.000 |
| 2   | 2,304,240          | 2,304,244                     | 1.000 |
| 3   | 1,804,641          | 1,804,641                     | 1.000 |
| 4   | 5,569,316          | 5,569,315                     | 1.000 |
| ... | ...                | ...                           | 1.000 |
| 40  | 927,673            | 927,673                       | 1.000 |

**All 40 ratios: min=0.999999, max=1.000000, mean=1.000000**

After correction:
- Basin water yield: 72,092,329 m³
- Outlet outflow: 72,092,334 m³
- Mass closure ratio: 1.000
- Simulated mean: 2.14 m³/s (vs obs 0.89 m³/s — uncalibrated)

## Root cause hypothesis

The engine's `hru_lte` → channel volume computation appears to use:

```fortran
! Buggy code (hypothetical)
channel_inflow = water_yield_mm * 1000.0 * area_ha
```

instead of:

```fortran
! Correct code
channel_inflow = water_yield_mm * 10.0 * area_ha
```

The `×1000` factor suggests a unit conversion path of:
- water_yield_mm ÷ 1000 → m (correct)
- area_ha × 10000 → m² (correct)  
- But the net multiplier ends up as ×1000 instead of ×10

This may be caused by an extra multiplication by 100 (e.g., basin area
fraction reversal, or percent→ratio confusion) in the LTE routing module.

## Workaround

Set `SWATPLUS_LTE_HRU_CHANNEL_SCALE_CORRECTION=0.01` environment variable
before engine execution. This patches `hru-lte.con` to use `frac=0.01`,
cancelling the engine's ×100 while keeping HRU water balance calculations
correct.

Or manually: set all `frac` values in `hru-lte.con` from `1.00000` to `0.01000`.

## Verification checklist for upstream

- [ ] Check LTE channel routing Fortran code for area/volume unit conversion
- [ ] Verify against a minimal 1-HRU, 1-channel model
- [ ] Confirm the bug is LTE-specific (does NOT affect standard/exco routing)
- [ ] Test with the 01654000 basin as provided
