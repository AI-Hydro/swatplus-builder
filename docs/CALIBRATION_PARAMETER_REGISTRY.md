# Calibration Parameter Registry

Status: current checkout alignment note
Date: 2026-05-16

## Full-Mode Core Parameters

| Name | Target file | Target column | Range | Default | Scope | Activity class | Evidence source | Model family | Claim-tier allowance |
|---|---|---|---:|---:|---|---|---|---|---|
| CN2 | `cntable.lum`; `urban.urb` | `cn_a/cn_b/cn_c/cn_d` for referenced `landuse.lum:cn2` rows; `urb_cn` for referenced urban rows | 35-98 | 75 | HRU/CN table and urban runoff CN | active | `tests/test_parameter_bridge.py`, full-mode bridge, urban volume-bias evidence | full | diagnostic until engine-screened per basin |
| PERCO | `hydrology.hyd` | `perco` | 0.01-1.0 | 0.5 | HRU | active | bridge implementation, registry alignment | full | diagnostic until engine-screened per basin |
| LATQ_CO | `hydrology.hyd` | `latq_co` | 0.001-1.0 | 0.01 | HRU | active | bridge implementation, registry alignment | full | diagnostic until engine-screened per basin |
| PET_CO | `hydrology.hyd` | `pet_co` | 0.8-1.2 | 1.0 | HRU | not_tested | SWAT+ hydrology.hyd documented range, bridge implementation, registry alignment | full | exploratory unless screened |
| ESCO | `hydrology.hyd` | `esco` | 0.01-1.0 | 0.95 | HRU | weak | SWAT+ hydrology.hyd documented range, bridge tests | full | diagnostic if included after screen |
| EPCO | `hydrology.hyd` | `epco` | 0.01-1.0 | 1.0 | HRU | not_tested | SWAT+ hydrology.hyd documented range, bridge tests | full | exploratory unless screened |
| SURLAG | `parameters.bsn` | `surq_lag` | 1.0-24.0 | 4.0 | global | not_tested | SWAT+ parameters.bsn documented range, bridge implementation | full | exploratory unless screened |
| ALPHA_BF | `aquifer.aqu` | `alpha_bf` | 0.001-1.0 | 0.048 | subbasin | not_tested | bridge tests, bridge/registry alignment | full | exploratory unless screened |
| RCHG_DP | `aquifer.aqu` | `rchg_dp` | 0.0-0.8 | 0.05 | subbasin | not_tested | bridge tests, registry alignment | full | exploratory unless screened |
| GW_DELAY | none in full-mode `aquifer.aqu` | unsupported | n/a | n/a | n/a | dead | bridge fail-loud writer | full | blocked |

## Full-Mode Extended Process Controls

These controls are not part of the required ten-parameter core set, but are
governed because diagnostics may identify process blockers that cannot be
resolved by the core set alone.

| Name | Target file | Target column | Range | Default | Scope | Activity class | Evidence source | Model family | Claim-tier allowance |
|---|---|---|---:|---:|---|---|---|---|---|
| SFTMP | `snow.sno` | `fall_tmp` | -5.0-5.0 | 1.0 | global snow record | weak | SWAT+ `snow.sno` documentation and bridge tests | full | diagnostic only when retained after basin-specific snow screen |
| SMTMP | `snow.sno` | `melt_tmp` | -5.0-5.0 | 0.5 | global snow record | weak | SWAT+ `snow.sno` documentation and bridge tests | full | diagnostic only when retained after basin-specific snow screen |
| LAT_TTIME | `hydrology.hyd` | `lat_ttime` | 0.0-120.0 | 0.0 | HRU | not_tested | SWAT+ lateral-flow lag documentation and full-mode source-code calibration path | full | diagnostic only when retained after basin-specific recession screen |
| CN3_SWF | `hydrology.hyd` | `cn3_swf` | 0.0-1.0 | 0.95 | HRU | not_tested | SWAT+ soft-calibration and `hydrology.hyd` documentation; `03353000` locked-objective probes | full | diagnostic only when retained after basin-specific volume screen |
| CH_N2 | `hyd-sed-lte.cha` | `mann` | 0.014-0.15 | 0.05 | channel | not_tested | SWAT+ `hyd-sed-lte.cha` and channel-flow Manning equation documentation; bridge tests | full | diagnostic only when retained after basin-specific channel-routing screen |
| CH_K2 | `hyd-sed-lte.cha` | `k` | 0.0-500.0 | 50.0 | channel | not_tested | SWAT+ `hyd-sed-lte.cha` channel alluvium conductivity documentation; bridge tests | full | diagnostic only when retained after basin-specific channel-routing screen |

## Rules

1. Bridge-supported parameters must exist in `src/swatplus_builder/params/registry.py`.
2. Registry-only parameters cannot support `research_grade`.
3. Dead or unsupported parameters must fail loudly.
4. Not-tested parameters require `exploratory` tier unless a basin-specific sensitivity screen promotes them.
5. CN2 edits the `cntable.lum` rows referenced by `landuse.lum:cn2` and, when urban land uses are present, referenced `urban.urb:urb_cn` rows for provenance consistency. Runtime HRU CN in generated full-mode TxtInOut is governed by the `landuse.lum:cn2` -> `cntable.lum` link, so urban-dominated basins require the referenced `cntable.lum` `urban` row to be covered.
6. `LAT_TTIME=0.0` delegates lateral-flow travel time to SWAT+ calculation; positive values are explicit recession-lag probes and must be basin-screened before calibration use.
7. `CN3_SWF` is SWAT+'s documented soft-calibration surface-runoff control. It belongs in the volume stage but remains diagnostic unless a fresh basin-specific locked sensitivity screen retains it and the promoted locked rerun passes all claim gates.
8. `CH_N2` and `CH_K2` are channel-routing attenuation controls for `hyd-sed-lte.cha`. They are not part of the required core parameter set; they enter only when active skill diagnostics show muted peaks or channel attenuation after volume gates pass, and remain diagnostic unless screened and locked.

## External References

- SWAT+ calibration documentation: `cn3_swf` is the surface-runoff variable in the water-balance soft-calibration procedure, with total limits `0.0-1.0`: https://swatplus.gitbook.io/io-docs/introduction/calibration
- SWAT+ `hydrology.hyd` documentation: `cn3_swf` is the soil-water adjustment factor for CN3 in `hydrology.hyd`: https://swatplus.gitbook.io/io-docs/introduction-1/hydrology/hydrology.hyd/cn3_swf
- SWAT+ `hyd-sed-lte.cha` documentation: channel hydrology records contain `mann` (Manning roughness) and `k` (effective channel alluvium conductivity): https://swatplus.gitbook.io/io-docs/introduction-1/channels/hyd-sed-lte.cha
- SWAT+ channel flow-rate documentation: Manning roughness appears directly in the channel flow and velocity equations: https://swatplus.gitbook.io/io-docs/theoretical-documentation/section-7-main-channel-processes/water-routing/flow-rate-and-velocity
