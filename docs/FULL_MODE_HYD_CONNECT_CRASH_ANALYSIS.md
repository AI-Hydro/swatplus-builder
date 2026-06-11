# hyd_connect.f90:377 Crash Analysis — Phase 3L.10.3

**Date:** 2026-05-11
**Verdict:** `d3_localized_from_source` — chandeg.con at wrong connect block position

## Source evidence

The SWAT+ engine source is at `github.com/swat-model/swatplus`. Fetched `hyd_connect.f90` (546 lines), `hyd_read_connect.f90` (344 lines), `input_file_module.f90`, and `hydrograph_module.f90`.

### The crash site

At `hyd_connect.f90:275`:
```fortran
case ("sdc")   !swat-deg channel
    ob(i)%obj_out(ii) = sp_ob1%chandeg+ob(i)%obtypno_out(ii) - 1
```

When `rout_unit.con` references `sdc`, the engine uses `sp_ob1%chandeg` as the object offset. `sp_ob1%chandeg` is computed from `sp_ob%chandeg` (the count of swat-deg channel objects).

### The object initialization

At `hyd_connect.f90:182-183`:
```fortran
if (sp_ob%chandeg > 0) then
    call hyd_read_connect(in_con%chandeg_con, "chandeg ", sp_ob1%chandeg, sp_ob%chandeg, hd_tot%chandeg, bsn_prm%day_lag_mx)
```

The engine reads chandeg objects ONLY when `sp_ob%chandeg > 0`, using `in_con%chandeg_con` as the file handle.

### The file handle mapping

From `input_file_module.f90:47-53`:
```fortran
character(len=25) :: chan_con = "channel.con"       ! position 7 in connect block
character(len=25) :: chandeg_con = "chandeg.con"    ! position 13 in connect block
```

The connect block in `file.cio` assigns files by POSITION. The reference has:
- Position 7: `null` → `in_con%chan_con = "null"` (no regular channels)
- Position 13: `chandeg.con` → `in_con%chandeg_con = "chandeg.con"`

## The D3 defect

Our converter replaces `channel.con` with `chandeg.con` at position 7 (the `chan_con` slot). This means:
- `in_con%chan_con = "chandeg.con"` (channel file set to chandeg.con — wrong type)
- `in_con%chandeg_con = "null"` (default — not set, because we left position 13 null)

When `sp_ob%chandeg = 15` (from lcha=15 in object.cnt, which IS correct), the engine calls:
```fortran
call hyd_read_connect("null", "chandeg", ...)  // file is "null" → skipped
```

The chandeg objects are NEVER initialized. When rout_unit→sdc routing tries to access `sp_ob1%chandeg + obj_id - 1`, the offset points to uninitialized memory → SIGSEGV at line 377.

## The fix

In `_convert_file_cio()`:
1. Set `channel.con` to `null` at position 7 (the regular channel slot)
2. **Add `chandeg.con` at position 13** (the last slot of the connect block, not replacing any existing file)
3. Match the reference's exact connect block layout

The current converter correctly generates `chandeg.con` and `object.cnt` (lcha=15). The only missing piece is putting `chandeg.con` at the right connect block position so the engine actually reads it.
