# rout_unit → channel failure — root cause investigation

**Date:** 2026-05-10
**Conclusion:** **builder version incompatibility**, not engine limitation

## Definitive test

Ran the OFFICIAL Tordera reference TxtInOut (built by SWAT+ editor v3.2.0,
engine rev 61.0.2.61) through OUR engine (rev 60.5.7):

```
Result: rc=0, channel_sd_day.txt: 64,605 rows, 32,213 non-zero flo_out values
```

**The engine CAN route water from routing units to channels.** The reference
TxtInOut produces channel flow on our engine. The failure is in our builder,
not the engine.

## Root cause

The reference uses `sdc` (straight-to-drainage-channel) routing type, which
is supported by engine rev 61 but NOT by our engine rev 60.5.7 (crashes with
rc=174 at `hyd_connect.f90`).

Our editor v3.2.2 generates routing files for engine rev 60.5.7 using `cha`
(regular channel) routing type, but the rout_unit→cha connection is not
functional. Multiple fix attempts confirmed:

| Attempt | Result |
|---|---|
| Add rhg entries to rout_unit.con | Engine runs, zero channel flow |
| Change cha → sdc | Engine crashes (rc=174) |
| rout_unit.def: 2 elements (positive + negative) | Zero channel flow |
| Direct HRU→channel in hru.con | Zero channel flow |
| Negative outlet IDs in rout_unit.def | Zero channel flow |

The rout_unit→cha routing path is simply not implemented in the editor v3.2.2
output for engine rev 60.5.7. The editor generates the files but the engine
doesn't connect the routing.

## The real fix

One of:
1. Upgrade to SWAT+ editor v3.2.0 with engine rev 61.0.2.61 (reference setup)
2. Implement rout_unit→channel routing manually in the builder's post-processing
3. Use direct HRU→channel routing via `hru.con` with obj_typ=cha — currently
   not working, requires investigating why the engine ignores it in full mode

## Evidence artifacts

- `multibasin_test/tordera_ref_1yr/` — reference TxtInOut run on our engine (WORKING)
- `multibasin_test/01547700_full/rhg_fix/` — rhg attempt (FAILED)
- `multibasin_test/01547700_full/sdc2_fix/` — sdc attempt (CRASHED)
- `multibasin_test/01547700_full/direct_hru/` — direct HRU attempt (FAILED)
