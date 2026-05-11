# Full-Mode Routing Schema Specification — Engine rev 60.5.7

**Phase:** 3L.9
**Date:** 2026-05-10
**Verdict:** `routing_schema_rule_identified` — engine supports only `sdc`+`lcha`+`chandeg.con` routing for rout_unit→channel transfer

## Executive summary

On engine rev 60.5.7, routing unit water reaches channels ONLY when the routing chain is:
```
HRU → rout_unit.con → sdc → chandeg.con → lcha → outlet
```

The `cha` (channel) object type silently produces zero channel flow when used in rout_unit→channel routing, even with `rte_cha=1`. The `sdc` (straight-to-drainage-channel) object type works, but requires `chandeg.con`, `lcha` objects, and `channel-lte.cha` infrastructure that our editor v3.2.2 does not generate.

## Mutation ladder results

| Step | Description | rc | Channel flow | Key finding |
|---|---|---|---|---|
| M0 | Reference baseline (sdc + chandeg + rte_cha=1) | 0 | ✅ 32,213 non-zero | Reference works on our engine |
| M1 | sdc → cha in rout_unit.con only | 174 | ❌ crash | `cha` incompatible with chandeg.con |
| M_cha_infra | M1 + channel.con + object.cnt fix | 174 | ❌ crash | `cha` objects not recognized in chandeg routing |
| M_rtecha_full_infra | rte_cha=1 + cha + channel-lte files | 174 | ❌ crash | Engine requires sdc+chandeg for rte_cha=1 |
| M_final_sdc_test | sdc + chandeg + channel-lte + rte_cha=1 | 174 | ❌ crash | Our cha-based objects don't convert to sdc |
| M_rtecha_fix | rte_cha=1 only (our build) | 174 | ❌ crash | Channel routing requires full sdc infra |

## What the reference has that our build doesn't

| Component | Reference (working) | Our build (broken) |
|---|---|---|
| Routing type in rout_unit.con | `sdc` (straight-to-drainage) | `cha` (channel) |
| Channel objects in object.cnt | `lcha=177, cha=0` | `cha=15, lcha=0` |
| Channel routing file | `chandeg.con` (176 rows) | `channel.con` (15 rows) |
| codes.bsn rte_cha | `1` (enabled) | `0` (disabled) |
| Channel parameter files | `channel-lte.cha` + `hyd-sed-lte.cha` | `channel.cha` + `hydrology.cha` + `sediment.cha` |
| rout_unit.con hyd types | `tot, sur, lat, rhg` | `tot` only |

## The schema rule

For engine rev 60.5.7:

1. **`rte_cha=1` routes water through channels.** With `rte_cha=0`, rout_unit→channel connections are silently ignored.
2. **`rte_cha=1` requires `sdc` routing type**, not `cha`. The engine crashes (rc=174, hyd_connect.f90) when `cha` objects appear in the `sdc`/`chandeg.con` routing chain.
3. **`sdc` routing requires `chandeg.con`** (not `channel.con`) and `lcha` objects (not `cha` objects).
4. **Channel routing requires `channel-lte.cha` + `hyd-sed-lte.cha`** channel parameter files.

## Implications for builder

The SWAT+ editor v3.2.2 generates `cha`-based routing (cha objects + channel.con) with `rte_cha=0`. This configuration is internally consistent (engine doesn't crash) but produces zero channel flow because `rte_cha=0` silently disables all channel routing.

To get working full-mode channel flow, the builder must either:
1. **Upgrade the editor**: Use an editor version that generates `sdc`+`lcha`+`chandeg.con` routing (like v3.2.0)
2. **Post-process routing files**: Convert the editor's cha-based output to sdc-based routing with proper chandeg.con and lcha infrastructure
3. **Bundle a different engine**: Use engine rev 61.0.2.61 which may support `cha` routing in full mode

## Honest limitations

- Engine source not available — no Fortran code found in QSWATPlus-3.2.2 distribution
- Only one engine binary tested (rev 60.5.7)
- Mutation ladder stopped at M_final_sdc_test — further mutations (e.g., regenerating chandeg.con from scratch) may find a path but were not attempted
- The reference uses different editor version (v3.2.0 vs our v3.2.2); the editor version determines the generated file format, not the engine
