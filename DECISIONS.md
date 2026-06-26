# Decisions

This file is append-only. Supersede old decisions with a new dated entry.

## 2026-06-26 — Authoritative NLDI Basin Can Constrain DEM Routing After DEM Gates Fail

Decision:

- For USGS-gauge workflows where NLDI returns an authoritative basin polygon,
  the package may use that polygon as a valid-domain mask for the DEM when both
  ordinary DEM routing and stream-burned routing fail area/IoU validation.
- The DEM remains the elevation source; the NLDI polygon constrains the
  drainage domain and must be recorded as
  `nldi_authoritative_basin_masked_dem`.

Why:

- The `01031500` diagnostic showed NLDI itself was correct, while the unmasked
  local D8 route crossed the authoritative divide near the outlet and produced
  invalid watershed areas.
- Treating NLDI only as a reference polygon was too weak. When the reference is
  authoritative and DEM-derived alternatives fail spatial gates, the robust
  recovery path is to promote the NLDI basin to domain authority instead of
  selecting a small tributary or a wrong larger basin.

Consequences:

- Architecture/topology claims can pass only when the masked-DEM result still
  passes area/IoU validation against the reference basin.
- This fallback does not promote hydrologic performance claims. `01031500`
  still has poor uncalibrated skill (`NSE=-0.3768`, `KGE=-0.5884`,
  `PBIAS=-99.12%`) and remains a calibration/process problem.
- Large SWAT output tables should be staged by hardlink/symlink where possible
  to avoid duplicating multi-GB evidence files.
- Generic workflow figures and metadata must use official USGS site metadata
  when available, or a neutral `USGS <id>` fallback, never a hardcoded basin
  name from another example.

## 2026-05-12 — Canonical Workflow Owns Scientific Claims

Decision:

- `swat workflow run` is the only path allowed to emit final claim-tier,
  blocker, calibration, and evidence-bundle decisions.

Why:

- Ad hoc scripts can help execute benchmark sweeps, but if they define claim
  tiers or final calibration status, the package stops being the scientific
  authority and agents can overclaim from partial artifacts.

Consequences:

- Scripts may aggregate `evidence_summary.json`.
- Scripts must not create independent research-grade verdicts.
- Missing canonical evidence is a pipeline failure, even if a basin metric looks
  good.

## 2026-05-12 — Research-Grade Requires Runtime Contract And Standard Window

Decision:

- `research_grade` and `publication_grade` workflow claims require an accepted
  or executed contract accepted by `user` or `policy`, a multi-year modeling
  window, and sufficient warmup.

Why:

- Short one-year simulations can be useful diagnostics, but they are not enough
  for defensible SWAT+ research claims.

Consequences:

- Missing or draft contracts downgrade high-tier requests.
- Short windows downgrade high-tier requests.
- The workflow must record the downgrade as a blocked claim, not silently
  continue.

## 2026-05-14 — Final Skill Selector Prioritizes KGE After Positive NSE

Decision:

- For `maintain_volume_gate_then_rank_nse_kge`, the locked calibration selector
  prioritizes KGE once NSE is nonnegative. Negative-skill candidates still use
  the previous NSE-first ranking.

Why:

- KGE is the explicit research-grade skill gate. Once a candidate has crossed
  out of negative NSE, choosing a small NSE gain over a material KGE
  improvement can move the accepted locked solution away from the governed
  claim criterion.

Consequences:

- The selector still cannot promote a claim by metric ranking alone; physical,
  routing-flow, sensitivity, calibration-verification, soil-fidelity, and
  hydrograph evidence must pass.
- `01654000` now selects the higher-KGE LAT_TTIME candidate
  (`NSE=0.044`, `KGE=-0.026`, `PBIAS=-24.41`) instead of the prior higher-NSE
  but lower-KGE candidate (`NSE=0.053`, `KGE=-0.082`, `PBIAS=-29.55`).

## 2026-05-14 — Routing Closure Keeps Conservative Reference But Records Scope Ambiguity

Decision:

- Do not switch the research-grade routing-flow gate from selected-terminal
  outflow versus `basin_wb` `wateryld` to routed-to-channel terms by default.
  Instead, record selected-terminal, all-terminal, `wateryld`, and
  routed-to-channel ratios together.

Why:

- SWAT+ documentation and source distinguish generated landscape water yield
  from channel-receiving components (`surq_cha`, `latq_cha`, `satex_chan`) and
  channel `flo_in`/`flo_out`. Current basin evidence shows both directions of
  ambiguity: some failed rows match routed-to-channel terms, while some passing
  multi-terminal rows have selected-terminal closure that differs from
  all-terminal routed flow.

Consequences:

- Routed-to-channel agreement is diagnostic evidence, not a claim promotion
  path.
- Multi-terminal rows now retain selected/all-terminal scope diagnostics so a
  future gate can require terminal inventory or aggregation evidence without
  re-parsing SWAT+ text outputs.

## 2026-05-14 — Negative NSE Exception Requires Skill-Diagnostic Timing Evidence

Decision:

- A locked calibrated run with negative NSE may pass the physical skill gate
  only when KGE is at least `0.40`, PBIAS is within `±30%`, and
  `skill_diagnostics.json` documents a timing or peak-lag limitation.

Why:

- The claim policy already allowed `NSE < 0` only under a documented timing
  limitation. The runtime metric gate enforced that rule, but the locked
  physical gate still emitted unconditional `NEGATIVE_SKILL`, making the
  documented exception impossible to reach.

Consequences:

- Timing documentation is evidence, not an agent assertion. It must come from
  package-written skill diagnostics.
- Metric values alone still cannot promote `research_grade`; routing,
  sensitivity, calibration verification, soil fidelity, fresh-output, outlet,
  and contract gates remain required.

## 2026-06-18 — Treat LTE Channel Length as Transfer-Length Compatibility Field

Decision:

- In converted full-mode builds that use the LTE `sdc`/`chandeg.con` channel
  path, write `hyd-sed-lte.cha:len` / `hyd_sed_lte_cha.len` as `0.0005 km`.
- Preserve physical channel geometry in the source GIS/channel tables
  (`gis_channels.len2` and source full-mode channel data).

Why:

- USGS `01547700` timing diagnostics showed that carrying physical channel
  lengths into the LTE compatibility table delayed the September 2004 runoff
  pulse from the basin water-yield date to the outlet by about six days.
- Lowering Manning roughness and seepage did not move the peak. Near-zero LTE
  transfer length did.
- Canonical setup uses the editor GIS importer before text conversion, so both
  the topology converter and `import_gis`/`import_gis_legacy` must enforce the
  same compatibility value.

Consequences:

- This is not a channel-length calibration parameter and must not be presented
  as a physical shortening of the stream network.
- Peak-flow claims remain blocked unless process/forcing evidence supports
  peak magnitude and timing.
- Tests now verify both paths: generated `hyd-sed-lte.cha` rows and editor
  `hyd_sed_lte_cha` rows use `0.0005`, while `gis_channels.len2` remains
  physical.

## 2026-06-18 — Cache Observed Flow and Preserve Applied Prior State

Decision:

- `fetch_usgs_daily_q` first reuses a matching run-local `obs_q.csv`, then a
  package-owned NWIS cache, then live NWIS with bounded retries.
- The subsurface-prior report uses `already_applied` when the prior profile is
  already present and water-yield evidence is within tolerance.

Why:

- The `01547700` full-overlay validation produced valid SWAT+ output but was
  blocked before benchmark lock when `waterservices.usgs.gov` reset a daily-flow
  request. Historical observed discharge should not be refetched every time if
  the exact window has already been cached.
- After a prior is applied and the engine is rerun, later clean reruns may
  legitimately be within the water-yield guardrail. Reporting that as
  `not_applied` hides the fact that the parameter files already carry the
  package-owned prior profile.

Consequences:

- Network outages still fail honestly when neither cache nor live NWIS can
  provide observations; the cache is not synthetic data.
- Repeated runs keep claim evidence interpretable: `not_applied` means the
  package withheld the prior, while `already_applied` means the prior profile is
  active and no additional rerun is required.
- The recovered `01547700` full-overlay baseline is volume-valid but still not
  a peak-flow claim; peak magnitude remains a separate blocked process question.

## 2026-06-18 — Peak-Response Screens Are Diagnostic Until Independently Locked

Decision:

- Treat the `01547700` `LATQ_CO`/`SURLAG` peak-response screens as hypothesis
  evidence only.
- Do not change package defaults, claim tiers, or research-grade status from
  temporary parameter screens.
- A candidate such as `LATQ_CO=0.20, SURLAG=1.0` must be rerun through a fresh
  locked benchmark/evidence path and pass package gates before becoming
  calibration evidence.

Why:

- Corrected daily `basin_wb_day.txt` diagnostics show major storms are present
  in forcing, while fast event response remains muted. This points to process
  parameterization rather than outlet plumbing.
- The best current screen improves `01547700` metrics
  (`NSE=0.343`, `KGE=0.452`, `PBIAS=-1.2%`) but it was produced from temporary
  scratch runs, not a package-governed final calibration artifact.
- More aggressive peak-focused settings improve KGE/extreme-tail ratios while
  degrading NSE or overproducing volume, so the calibration objective must stay
  multi-metric and gate-owned.

Consequences:

- The next robust step is a governed candidate rerun/locked verification for
  the `LATQ_CO`/`SURLAG` family, followed by physical, routing, sensitivity,
  hydrograph, and claim-governance checks.
- Temporary screen outputs may guide parameter bounds and phases, but final
  evidence must come from package-written benchmark/calibration artifacts.

## 2026-06-18 — Verified LATQ/SURLAG Candidate Improves Skill But Does Not Unlock Peak Claims

Decision:

- Treat `LATQ_CO=0.20, SURLAG=1.0` for `01547700` as a verified locked-candidate
  improvement, not as a complete peak-flow solution.
- Keep peak-magnitude claims limited until additional evidence improves the
  extreme-flow tail and event peaks without breaking the physical/process gate.

Why:

- Independent verification against the locked benchmark improved both NSE and
  KGE with fresh outputs: `NSE=0.342880294416419`,
  `KGE=0.45218154428386403`, `PBIAS=-1.2497238817010707`.
- Applying the package candidate water-balance gate to the fresh verification
  `TxtInOut` passed with no condition codes.
- Extreme peaks remain undercaptured: the top-0.1% flow ratio is only `0.257`,
  with `2004-09-18` and `2008-03-05` event peak ratios of `0.202` and `0.121`.

Consequences:

- The next experiment should target peak magnitude/shape, likely through
  bounded surface-response and event-timing controls, while preserving the
  verified LATQ/SURLAG volume gate behavior.
- The paper/presentation can honestly report a verified process-calibration
  improvement, but should not imply flood-peak fidelity has been solved.

## 2026-06-18 — Adopt Verified CN2 Candidate, Treat Snow Thresholds as Secondary

Decision:

- For `01547700`, retain `LATQ_CO=0.20, SURLAG=1.0, CN2=78` as the strongest
  verified candidate found so far.
- Treat snow-threshold tuning (`SFTMP`, `SMTMP`) as a secondary diagnostic for
  this basin, not the primary peak-response repair.
- Keep flood-peak fidelity claims blocked/limited until forcing/event
  representativeness and structural peak attenuation are resolved.

Why:

- Independent verification of the CN2 candidate improved the recovered
  benchmark to `NSE=0.35566856403724056`,
  `KGE=0.49038217013548413`, `PBIAS=1.3632391338746341`, with fresh outputs
  and passing candidate physical/process gates.
- The verified top-0.1% peak-tail ratio improved to `0.299`, but the major
  `2004-09-18` and `2008-03-05` event peak ratios remain only `0.231` and
  `0.180`.
- The largest two observed events have high runoff-demand evidence relative to
  generated precipitation. The USGS drainage-area check is close to the
  delineated area, so this is not mainly an area mismatch.
- A narrow snow-threshold screen produced only small peak-tail gains and lower
  NSE; the best snow variant improved q999 from `0.299` to `0.308` while
  reducing NSE from `0.356` to `0.340`.

Consequences:

- The next robust experiment should audit forcing representativeness and event
  precipitation/antecedent conditions before widening calibration parameters.
- Package defaults should not be changed to snow-threshold settings from this
  screen.
- Any future candidate that improves extreme peaks must still pass the same
  fresh locked verification and package gate workflow before being cited as
  evidence.

## 2026-06-18 — Global Precipitation Scaling Is Diagnostic, Not a Fix

Decision:

- Do not use a global precipitation multiplier as a calibration or repair path
  for `01547700`.
- Treat precipitation scaling only as a diagnostic that shows the model is
  sensitive to storm forcing magnitude.

Why:

- A controlled screen around the verified
  `LATQ_CO=0.20, SURLAG=1.0, CN2=78` candidate shows that increasing all
  generated PCP files improves peak-tail ratios but quickly damages volume and
  NSE.
- `+5%` precipitation improves q999 from `0.299` to `0.321` but raises PBIAS
  to `10.1%` and lowers NSE to `0.341`.
- `+10%` precipitation improves q999 to `0.343` but raises PBIAS to `18.8%`
  and lowers NSE to `0.317`.
- `+20%` precipitation improves q999 to `0.388` but fails the package
  water-balance gate with `PBIAS=36.4%` and `VOLUME_BIAS`.

Consequences:

- The next forcing work must be source-backed: event precipitation
  representativeness, station/grid-cell selection, storm timing, snow/antecedent
  storage, and possibly alternate meteorological products.
- Peak claims remain limited because extra storm water helps but does not
  produce a gate-valid flood-peak solution.

## 2026-06-19 — Resolve D8 Topology Ambiguity Before Terminal Pruning

Decision:

- When a stream link has multiple candidate downstream successors, retain the
  successor with the greatest maximum flow accumulation before cycle removal.
- Do not obtain a single-terminal network by deleting subbasins classified as
  secondary terminals when the ambiguity can be resolved from the flow raster.

Why:

- The first fresh `03349000` full-overlay run produced 39 raster subbasins but
  retained only 35 vector subbasins. Secondary-terminal pruning removed IDs
  `12`, `18`, `19`, and `20`, totaling `315.21 km2`, and reduced delineated
  area to `1772.75 km2`.
- Reconstructing the raw 39-node graph and resolving split successors by flow
  accumulation produced 38 edges, one terminal (`GIS 39`), one weakly
  connected component, and no cycles without deleting basin area.
- The corrected fresh run retained all 39 subbasins and `2087.919 km2`, passed
  delineation validation (`-5.67%` against the NLDI reference polygon), and
  passed the package routing-flow gate.

Consequences:

- Flow accumulation is now the authoritative tie-breaker for ambiguous D8
  stream-link successors.
- Terminal pruning remains a safeguard, not a substitute for resolving
  topology construction errors.
- Cross-basin tests must compare raster and vector subbasin inventories so
  future routing repairs cannot silently discard watershed area.

## 2026-06-19 — One-at-a-Time Sensitivity Must Preserve the Generated Baseline

Decision:

- A basin-specific one-at-a-time sensitivity screen starts from the unchanged
  locked model (`objective({})`).
- Each perturbation applies only the parameter being tested; unrelated scalar
  registry defaults are not written into the model.

Why:

- Generated full-mode models can contain spatially heterogeneous values, such
  as soil- and slope-dependent `PERCO` rows.
- The previous screen applied every registry default before each supposedly
  one-at-a-time perturbation. That silently changed unrelated model fields and
  made both the baseline and parameter attribution invalid.

Consequences:

- Sensitivity deltas now measure one controlled parameter change relative to
  the actual generated basin model.
- Spatially distributed parameters still need a separate design for relative
  or grouped perturbations; replacing their fields with one scalar remains a
  limitation to address before broad calibration.

## 2026-06-19 — Diagnose `03349000` ET Partition Before Broad Calibration

Decision:

- Do not transfer the historical dominant-HRU calibration or begin a broad
  parameter search on the corrected `03349000` full-overlay model.
- Complete one bounded `PET_CO=0.8` diagnostic first. The fresh candidate
  improved `NSE` and `KGE` but still failed `VOLUME_BIAS` and
  `NEGATIVE_SKILL`, so prioritize crop and management fidelity before
  additional hydrologic tuning.

Why:

- The corrected baseline passes delineation, outlet, soil-provenance, and
  routing-flow checks but fails `ET_DOMINATED`, `VOLUME_BIAS`, and
  `NEGATIVE_SKILL`: `NSE=-0.317`, `KGE=0.052`, `PBIAS=-58.0%`.
- Basin water balance is dominated by soil evaporation: `ET/P=0.740`,
  `Esoil/ET=0.806`, `Eplant/ET=0.178`, and `WaterYld/P=0.229`.
- About 70.8% of the basin is NLCD cultivated crops, while the generated model
  represents those HRUs with generic agriculture and generic management rather
  than crop-specific annual rotations.
- Transferring the old candidate corrected volume but damaged shape and skill
  (`NSE=-2.929`, `KGE=-0.214`, `PBIAS=-3.10%`), so it was rejected.

Consequences:

- A better metric alone cannot promote this basin; each candidate must pass a
  fresh physical gate and locked verification.
- Bounded PET adjustment was insufficient. The next structural experiment is
  source-backed crop/management representation, followed by a new baseline and
  controlled sensitivity screen.

## 2026-06-20 — Crop Profiles Require Basin Evidence and Remain Opt-In

Decision:

- Keep crop-specific management profiles opt-in and require crop-composition
  evidence with source URL, digest, year, basin, and quantitative coverage.
- Do not promote the new corn-soy profile to a package default from the
  `03349000` experiment.

Why:

- USDA CDL evidence strongly supports corn and soybeans as the dominant crops
  in this basin, so the controlled two-year rotation was a defensible test.
- The fresh crop-specific run did not improve the hydrology: NSE was unchanged
  within `0.001`, KGE and PBIAS worsened, and all physical blockers remained.
- CDL crop identity does not prove field-level planting dates, tillage,
  fertilization, or annual sequence for every HRU.

Consequences:

- The profile is useful infrastructure for source-backed experiments, not an
  automatic national mapping from NLCD class 82.
- Any future adoption requires fresh multi-basin evidence and normal package
  gates; source provenance does not substitute for model validation.

## 2026-06-20 — Use Land-Use-Scoped CN Deltas for Process Diagnostics

Decision:

- Use `apply_cn2_delta_to_landuse()` when testing runoff response for one land
  use. Preserve hydrologic-group differences and leave all other classes
  unchanged.
- Do not interpret an absolute global CN2 target as an isolated process test in
  a multi-land-use basin.

Why:

- Setting global `CN2=82` would raise the row-crop B value from 78 to 82 while
  lowering urban CN from 98 to 82 and changing forest/pasture rows in other
  directions. A resulting metric cannot be attributed to agricultural runoff.
- The scoped AGRL `+4` test improved volume but worsened NSE and correlation,
  demonstrating a real volume-versus-timing tradeoff without the urban
  confound.

Consequences:

- Broad CN2 calibration remains diagnostic-only until the global parameter is
  redesigned as a relative or grouped perturbation that preserves land-use
  structure.
- Candidate reports must identify the exact `landuse.lum` and `cntable.lum`
  rows changed.

## 2026-06-20 — Annual GridMET Magnitude Is Not the Primary `03349000` Repair

Decision:

- Do not apply a basin-wide precipitation multiplier to `03349000`.
- Move next to subsurface/baseflow generation and event timing, using a complete
  alternate forcing rerun only if event-level evidence later supports it.

Why:

- Five matching Daymet points are only `2.1%` wetter than GridMET over
  2000-2019, far below the current discharge-volume deficit.
- Daymet event-window differences around the largest observed peaks are mixed,
  not a consistent positive correction.
- The model's simulated BFI near `0.21` remains much lower than observed BFI
  `0.562`, while runoff acceleration through AGRL CN worsens NSE.

Consequences:

- The next controlled branch should preserve soil heterogeneity while testing
  percolation, aquifer release, and subsurface timing.
- Forcing corrections still require an area-weighted alternate bundle, a fresh
  full-period run, and unchanged physical/verification gates.

## 2026-06-20 — Restore Explicit Groundwater Recharge Routing

Decision:

- Route every full-mode routing unit's `rhg` hydrograph to its matching
  shallow aquifer and every shallow aquifer's deep-recharge fraction to the
  matching deep aquifer.
- Treat missing recharge routes as a build error. Do not calibrate aquifer
  parameters while aquifer recharge is zero.

Why:

- The canonical `03349000` model produced `35.443 mm/yr` HRU percolation but
  every aquifer reported zero recharge and zero groundwater flow.
- A SWAT+ reference project explicitly routes `ru -> aqu` and shallow
  `aqu -> deep aqu` with hydrologic type `rhg`; the generated builder graph
  omitted both connections.
- A fresh 1997-2019 controlled rerun restored `37.109 mm/yr` basin aquifer
  recharge and `10.838 mm/yr` groundwater flow to channels. Simulated BFI
  increased from `0.210` to `0.242`; NSE, KGE, log-KGE, and PBIAS all improved
  modestly without changing HRU parameters or forcing.

Consequences:

- The routing repair is adopted as an engineering correction, not a
  research-grade model claim. `03349000` still has negative NSE and a
  `-56.24%` discharge-volume bias.
- The next experiment may screen aquifer release/revap controls because those
  parameters now act on nonzero recharge. Physical and locked-verification
  gates remain unchanged.

## 2026-06-20 — Govern `GW_REVAP`; Do Not Use Its Endpoint as a Default

Decision:

- Add `GW_REVAP` as an engine-active extended full-mode control targeting only
  shallow-aquifer `aquifer.aqu:revap` rows.
- Keep the generated default `0.02`. A value of zero is retained as an endpoint
  diagnostic, not adopted as a basin or package default.

Why:

- SWAT+ defines revap as ET-demand-driven upward transfer from shallow aquifer
  storage and documents a coefficient range of `0-1`.
- With repaired recharge, the `GW_REVAP=0` endpoint moved aquifer flow to
  channels from `10.838` to `33.543 mm/yr` and improved every reported metric.
- It still failed the key gates: `NSE=-0.282`, `KGE=0.090`, and
  `PBIAS=-52.33%`. Even eliminating all simulated revap cannot repair the
  basin's large water-yield deficit.

Consequences:

- `GW_REVAP` is eligible for basin-specific sensitivity/calibration only after
  nonzero recharge is verified.
- The next volume hypothesis must address the larger ET/soil-water partition;
  aquifer release alone is quantitatively insufficient.

## 2026-06-20 — Redistribute Filtered HRU Area Within Each LSU

Decision:

- When full-overlay HRUs are removed by `min_hru_fraction`, redistribute their
  area proportionally among retained HRUs in the same LSU.
- Refuse post-Editor models when retained HRU fractions do not sum to one per
  routing unit. Do not permit threshold filtering to change modeled basin area.

Why:

- The canonical `03349000` model retained `191,588.842 ha` of HRUs from
  `208,791.925 ha` of LSUs. The missing `17,203.083 ha` was passed directly to
  SWAT+ as routing fractions below one.
- A fresh overlay audit attributes `17,173.314 ha` to threshold filtering and
  only `29.770 ha` to invalid source pixels.
- QSWAT+ documents proportional redistribution of ignored HRU area among
  retained HRUs within each LSU.
- A full controlled rerun improved KGE, log-KGE, PBIAS, BFI, and KGE volume and
  variability components. NSE remained negative and worsened, confirming that
  mass repair is necessary but not equivalent to event-shape calibration.

Consequences:

- Existing models built before this correction must be rebuilt or explicitly
  migrated and freshly rerun before their outputs are used as evidence.
- The remaining `03349000` deficit cannot be attributed to missing HRU area
  alone. The separate `5.67%` difference between the DEM-derived watershed and
  the authoritative reference polygon remains a delineation-scope question,
  not an authorized area multiplier.
- No performance gate or claim tier is weakened by this correction.

## 2026-06-25 — Calibration Audit: Six Structural Vulnerabilities Fixed

Decision:

- Fix six structural vulnerabilities in the calibration pipeline identified
  during a comprehensive audit against SWAT+ calibration best practices
  (Tolson & Shoemaker 2007, Klemeš 1986, Abbaspour 2015, Pushpalatha et al.
  2012).

Why:

1. **LTE mode silently bypassed physical gates.** `include_physical_gate` was
   conditioned on `parameter_mode == "full"`, letting LTE calibrations select
   physically implausible candidates on skill alone.
   **Fix:** `include_physical_gate=True` unconditionally — every candidate,
   regardless of mode, must pass the water-balance gate before finetune
   promotion.

2. **Multi-seed DDS ensemble only refined the final phase.** Secondary seeds
   perturbed only the finetune parameter set from the primary best point,
   producing a false-narrow uncertainty estimate and missing earlier-phase
   equifinality basins.
   **Fix:** Each seed now traces the complete staged protocol (volume →
   baseflow → peaks → finetune) from a fresh baseline, with budget divided
   across seeds.

3. **Baseflow phase ignored BFI.** The `baseflow_subsurface` phase used
   `maintain_volume_gate_then_improve_bfi_and_kge` as its objective but
   `_score_candidate` had no BFI term, letting groundwater parameters
   overfit to total-flow KGE regardless of baseflow index fidelity.
   **Fix:** Added basin-specific BFI scoring that rewards simulated BFI
   matching observed `bfi_obs` (from `evaluate_run`), with a graded reward
   band and fallback to 0.55 prior when unobserved.

4. **Real-engine cache was not invalidated on binary upgrade.**
   `_objective_cache_signature` hashed only the builder source files but not
   the SWAT+ binary, so upgrading the engine reused stale workdirs with
   potentially different solver behaviour.
   **Fix:** Cache signature now includes `swat_binary_sha256` and
   `builder_version`.

5. **pySWATPlus bridge truncated multi-objective requests to single indicator.**
   A dead loop with `break` after first iteration silently discarded all but
   the first objective when multiple were passed.
   **Fix:** Loop removed; single-objective limitation documented with a clear
   note that pySWATPlus binds one indicator per monitored file.

6. **No warm-up period stripping during objective scoring.** The first 1–3
   years of simulation are contaminated by uninitialised state variables
   (empty aquifers, dry channels), yet the entire observed window was scored.
   **Fix:** Added `nyskip_years=2` default to `make_real_objective`, trimming
   early years from the observed series before metric computation. Split-
   sample validation correctly passes `nyskip_years=0` since the held-out
   period is already warm-up-excluded.

Consequences:

- All 226 calibration + full-mode + integration tests pass.
- LTE calibration no longer escapes physical-process governance.
- Uncertainty quantification (multi-seed ensemble) reflects independent
  search trajectories, not local fine-tuning.
- BFI now constrains groundwater-phase optimisation.
- Cached workdirs are properly invalidated when the SWAT+ binary changes.
- Warm-up stripping follows Klemeš (1986) / Abbaspour (2015) convention.
- The water-balance gate (`full_mode/water_balance_gate.py`) is mode-agnostic —
  it reads `basin_wb_aa.txt`, a standard SWAT+ output present in both LTE
  and full-mode runs, so unconditional physical gating works for both modes.

## 2026-06-20 — Acquire DEMs Beyond the Reference Watershed Boundary

Decision:

- Fetch 3DEP over a rectangular extent expanded 5 km beyond the authoritative
  basin bounds. Keep the original NLDI polygon as the independent validation
  reference.
- Refuse full-mode delineations whose watershed touches invalid DEM data or
  the raster edge.

Why:

- Clipping the DEM to the basin polygon made that polygon an artificial
  drainage boundary. Although the DEM valid-cell area matched the reference,
  only `2089.599 km²` of `2213.476 km²` could contribute to the largest outlet
  path and `4,808` watershed cells contacted invalid data.
- Polygon-shaped buffers remained boundary-sensitive and changed area with
  buffer size.
- A 5 km buffered bounding box produced zero domain contacts and improved the
  independent validation from `-5.67%` area difference / `94.31%` IoU to
  `-1.30%` / `95.13%`, with a clean single-terminal topology.

Consequences:

- DEM request geometry is context, not the modeled watershed. The DEM-derived
  catchment must still pass area, overlap, topology, and outlet checks against
  authoritative evidence.
- Cached DEMs whose buffer cannot be verified are provenance-labeled and will
  fail the hard margin gate if their domain truncates the watershed.
- This correction is verified geometrically on `03349000`; multi-basin fresh
  builds remain required before general performance claims.

## 2026-06-25 — Locked Calibration Uses One Immutable Scoring Window

Decision:

- Handle model spin-up in the prepared SWAT+ simulation and output
  configuration before creating the benchmark lock.
- After `benchmark/alignment.csv` is sealed, sensitivity screening,
  calibration search, and independent verification must use its exact dates
  and observed values with `nyskip_years=0`.

Why:

- A production `01547700` run exposed inconsistent contexts: the benchmark
  scored 2010–2018, while sensitivity and candidate search silently removed
  2010–2011. The empty-parameter sensitivity baseline therefore differed from
  the locked benchmark (`NSE 0.230` versus `0.260`).
- The generated project had already run 2008–2009 as spin-up and excluded those
  years from the scored channel output. Applying another trim removed valid
  evaluation data rather than warm-up.

Consequences:

- The empty-parameter objective must reproduce the benchmark metrics exactly
  before parameter screening can be trusted.
- Historical calibration artifacts produced with a second post-lock trim are
  diagnostic only and must be regenerated before release evidence is cited.
- Standalone users remain responsible for preparing a benchmark alignment that
  excludes any intended spin-up period before locking.

## 2026-06-26 — Score Converted Terminal Outlets With Topology-Owned Inflow When State Tables Are Non-Accumulating

Decision:

- When a requested outlet is a terminal channel but its daily channel state
  table is dwarfed by immediate upstream channel inflows, evaluate the outlet
  using a topology-derived `terminal_inflow_sum` hydrograph.
- Keep the selected outlet GIS ID unchanged. Record the contributing parent
  GIS IDs, parent/state flow ratio, source file hash, and `outlet_scope`.
- Prefer `channel_sdmorph_day.txt` over `channel_sd_day.txt` when daily basin
  output is unavailable, because it exposes the same SWAT-deg flow fields with
  less table overhead for outlet evaluation.

Why:

- A fresh `01031500` NLDI-masked run produced a nearly flat selected-terminal
  hydrograph at GIS `259` (`PBIAS=-99.1%`), even though basin water balance
  generated large water yield and upstream main-stem channels carried
  basin-scale flow.
- `chandeg.con` showed terminal unit `254` / GIS `259` was fed by immediate
  upstream channel GIS IDs `231` and `247`. Their terminal-inflow sum changed
  the diagnostic hydrograph from almost zero to realistic volume
  (`PBIAS=-1.4%`) without changing the selected outlet authority.
- Choosing the best NSE/KGE channel would be scientifically unsafe. The repair
  must be topology-owned, not metric-picked.

Consequences:

- The original `01031500` near-zero hydrograph is an evaluator/output-table
  authority bug, not evidence that the model generated no water.
- The corrected `01031500` hydrograph still has poor skill
  (`NSE=-1.08`, `KGE=0.21`) because the response is too flashy and
  baseflow persistence is weak. Calibration and process diagnosis remain
  separate next steps.
- Terminal-inflow evaluation is claimable only with recorded provenance; it
  does not license arbitrary upstream channel selection.

## 2026-06-26 — Use Windowed Real-Engine Screens Only as Calibration Triage

Decision:

- Real-engine calibration may use explicit `simulation_start` /
  `simulation_end` and `score_start` / `score_end` windows for screening.
- These windows are written into `time.sim`, `print.prt`, and the objective
  cache signature.
- Windowed results are triage evidence only. A parameter vector is not
  claimable until it passes a full-window locked verification.

Why:

- Full-period `01031500` corrected-objective calibration candidates were too
  slow for iterative debugging because each run wrote large daily channel
  tables.
- The package still needed a scientifically governed way to reject bad
  calibration hypotheses without promoting short-window results as final
  performance claims.

Consequences:

- The `01031500` 2007-2012 screen rejected two simple calibration directions
  before full verification: `LATQ_CO=0.003` / `SURLAG=12` and `CN2=65` /
  `CN3_SWF=0.5` / `SURLAG=12` both worsened NSE/KGE relative to baseline.
- No full-window verification was promoted from that screen.
- Future calibration work should target more specific hypotheses, such as
  aquifer/baseflow controls, snow/precipitation timing, or routing
  concentration, rather than widening those failed directions.

## 2026-06-26 — Make Diagnostic-Guided DDS The Automated Calibration Contract

Decision:

- The automated calibration path is a package-owned diagnostic-guided DDS
  workflow: volume first, then baseflow/subsurface, then peak timing, then
  KGE/NSE finetuning.
- Long locked records may use a recent real-engine screening window for
  candidate search, but the chosen parameter vector must still pass full
  locked verification before it can support a calibration claim.
- SWAT-DG is treated as methodological inspiration for staged diagnosis, not
  as an imported dependency or direct SWAT+ authority.

Why:

- Blind metric optimization can improve one score while hiding volume,
  outlet-scope, routing, or process failures.
- Full-window real-engine DDS is expensive enough that a governed screening
  window is needed for iteration.
- A short-window result is scientifically weaker than a full locked rerun, so
  the package must record the window and refuse to treat the candidate score as
  final evidence.

Consequences:

- `diagnostic_calibration.json` now records the strategy, phase logic, and
  screening window.
- `best_solution.json` records the screening window used for search.
- Final performance claims still point to `verification_summary.json`, not to
  optimizer history.

## 2026-06-26 — Dashboard Is A First-Class End-To-End Artifact

Decision:

- End-to-end workflow runs must record the generated dashboard in
  `evidence_summary.json`, `EVIDENCE_SUMMARY.md`, and `run_manifest.json`.

Why:

- The HTML dashboard was being generated after evidence/manifest writes, so
  users could miss it even when the file existed.
- A modeller-facing dashboard is part of the evidence bundle, not an optional
  debug sidecar.

Consequences:

- `dashboard.html` is now promoted into the machine-readable and human-readable
  artifact pointers after generation.
- Dashboard build failure still does not abort the hydrologic run, but success
  is now traceable from the official run artifacts.

## 2026-06-26 — Calibration Progress Is Evidence, Not Console Noise

Decision:

- Real-engine calibration must write `calibration_progress.json` while it is
  screening, searching, verifying, blocked, failed, or complete.
- Progress writes are atomic and live under the run's calibration evidence
  tree so dashboards and agents can inspect the current state without parsing
  stdout.

Why:

- Multi-candidate SWAT+ calibration can spend minutes in setup, sensitivity
  screening, or a single objective evaluation with no terminal output.
- A silent calibration run is not auditable enough for an agent-governed
  scientific workflow; users need to know whether the package is screening
  parameters, evaluating a candidate, verifying a locked solution, or refusing
  promotion.

Consequences:

- The dashboard can show calibration status even for incomplete or failed
  calibration attempts.
- A failed calibration phase, such as `03349000` failing the volume promotion
  gate after 8 evaluations, becomes a retained evidence artifact instead of a
  vague failure.

## 2026-06-26 — Spatial Overview Panels Must Share Basin Authority

Decision:

- Basin overview visuals must use a common basin reference geometry for
  clipping, extent, and context overlays.
- Use vector panels for subbasins, HRUs, and stream networks when vector
  artifacts exist; use masked rasters only where raster evidence is the
  scientific object being shown.

Why:

- The previous dashboard spatial overview mixed raster extents, CRS behavior,
  and unclipped panels. That made some basins appear cropped, resized, or
  visually inconsistent even when the underlying artifacts were valid.
- These figures are diagnostic evidence for modellers, not decorative
  thumbnails; inconsistent map context weakens trust in the run.

Consequences:

- Spatial panels now show the same basin footprint, visible stream network,
  outlet marker, and masked nodata handling.
- The overview remains diagnostic context only; it is not treated as model
  performance evidence.

## 2026-06-26 — Calibration Must Try Sensitivity-Guided Anchor Combinations

Decision:

- Before DDS spends its random-search budget, locked diagnostic calibration
  evaluates deterministic anchor combinations derived from the basin-specific
  sensitivity screen.
- These anchors are candidates only; they are still scored by the same locked
  objective, volume gate, calibration-process gate, and final verification
  authority as any DDS candidate.

Why:

- `03349000` showed a false block: one-at-a-time sensitivity moves were not
  enough to pass the volume gate, but combined moves such as `ESCO=0.01` with
  `PET_CO=0.8` or `CN3_SWF=0.0` did pass volume.
- A calibration method that only waits for DDS to stumble into such a
  combination can incorrectly report "no candidate passed the volume gate."

Consequences:

- The volume phase can now advance when sensitivity evidence already identifies
  complementary parameter directions.
- Candidate metrics remain provisional until independent locked verification.
- Standalone `run_diagnostic_calibration()` writes root
  `calibration_provenance.json` so debug reruns do not leave stale failed
  provenance beside successful report artifacts.
