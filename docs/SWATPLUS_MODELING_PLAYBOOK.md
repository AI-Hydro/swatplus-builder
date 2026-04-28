# SWAT+ Modeling Playbook (Evidence-Driven, Evolving)

Last updated: 2026-04-27
Scope: `swatplus-builder` alpha-stage pipeline behavior observed in project artifacts and tests.

## 1. Proven Working Patterns

- `[validated]` Route hydrologic metrics through `evaluate_run` only.  
  Evidence: metric parity closeout in calibration bridge (`metric_parity_log.csv`) + tests asserting authoritative `bridge_reported_nse/kge` behavior.
- `[validated]` Use outlet auto-detection fallback when configured outlet is dry.  
  Evidence: routing stabilization runs where GIS ID 1 was dry but detected terminal channel produced non-zero hydrograph.
- `[validated]` Hybrid soil fallback (minimal soils) keeps runs structurally executable when detailed soils are unavailable.  
  Evidence: multi-basin E2E batches with persisted soil mode metadata and complete artifacts.
- `[validated]` Calibration bridge must diff staged vs per-eval input files; zero changed files is a hard failure.  
  Evidence: new bridge guardrail test + runtime fail-loud patch.

## 2. Calibration Lessons

- `[validated]` Manual perturbation can confirm parameter sensitivity even when optimizer history is flat.  
  Evidence: sensitivity audits showed CN2/ALPHA_BF alter outputs in selected basins.
- `[validated]` Flat `history.csv` across evaluations usually means injection/bridge failure, not basin insensitivity.  
  Evidence: pySWATPlus evaluations previously reported identical metrics while manual CN2 perturbations changed outputs.
- `[validated]` First locked-benchmark calibration evidence (`usgs_01547700`) shows real improvement when calibrating only effective parameters (`CN2`, `ALPHA_BF`) using real-engine DDS.  
  Evidence: locked benchmark verification (`tests/_artifacts/calibration_locked_20260424_effective_01547700/CALIBRATION_VERIFICATION.md`) with verified delta NSE/KGE `+0.085078/+0.079955`.
- `[validated]` pySWATPlus bridge remains non-authoritative/unstable for the `usgs_01547700` locked benchmark path at present.  
  Evidence: bridge attempt failed with `pySWATPlus calibration execution failed` while equivalent real-engine workflow completed and verified.
- `[tentative]` SOL_AWC/SOL_K/GW_DELAY low sensitivity in current setup may reflect forcing/model structure, not universal hydrologic truth.  
  Evidence: two-basin quick audits with weak metric movement.

## 3. Failure Modes and Fixes

- `[validated]` Channel zero-flow with non-zero HRU/LSU water often indicates outlet/evaluation mismatch.  
  Fix: outlet fallback auto-detection + explicit outlet metadata.
- `[validated]` `rte_cha=1` segfault risk can occur with unstable routing geometry/runtime assumptions.  
  Fix: geometry/runtime audit before enabling Muskingum path broadly.
- `[validated]` pySWATPlus run reuse/stale outputs can mask calibration effects.  
  Fix: remove day/month/year output files before run and log output hashes/mtimes by evaluation.

## 4. Decision Rules

- `[validated]` If `metric_source != evaluate_run`, stop and restore parity first.
- `[validated]` If calibration history has <=1 unique NSE over >=3 evaluations, run CN2 injection trace before expanding search.
- `[validated]` If no SWAT+ input files changed for an evaluation, fail immediately.
- `[validated]` For current locked-benchmark calibration runs, use real-engine DDS with only effective parameters (`CN2`, `ALPHA_BF`) and verify best solution by independent rerun against the same locked alignment/outlet context.
- `[validated]` Locked calibration objectives must score with `outlet_policy="strict"` by default.
  Evidence: 2026-04-27 fresh real-engine quick run exposed that objective scoring was relying on the evaluator default (`auto`); patch now passes strict unless `allow_outlet_autodetect=True`, with regression tests.
- `[validated]` Treat pySWATPlus bridge outputs as non-authoritative for a lock when runtime fails or parity/trace artifacts are incomplete; do not use them to claim improvement.
- `[tentative]` Prefer random proposals over history proposals when seeded history is flat.

## 5. Experiment Evidence

- `[validated]` Routing stabilization evidence: non-zero channel flow restored in updated e2e runs.
- `[validated]` Outlet auto-detection evidence: dry configured outlets replaced by flowing terminal IDs.
- `[validated]` Metric parity evidence: bridge-reported NSE/KGE aligned to evaluate_run for same outlet/date window.
- `[validated]` Calibration readiness evidence: bridge diagnostics now capture changed-file counts and output hash change status.
- `[validated]` Locked benchmark (01547700) calibration evidence:
  - benchmark lock artifact with hashed alignment and outlet provenance,
  - calibrated best verified by independent rerun with matching metrics,
  - persisted summary files under `tests/_artifacts/calibration_locked_20260424_effective_01547700/`.
- `[validated]` Locked benchmark contrast-basin evidence (03339000) with same calibration path and parameter subset:
  - lock preserved selected outlet context (`outlet_gis_id=836`),
  - real-engine DDS (`CN2`, `ALPHA_BF`) improved NSE/KGE and verified by independent rerun,
  - persisted summary files under `tests/_artifacts/calibration_locked_20260424_effective_03339000/`.
- `[tentative]` Multi-basin calibration lift currently modest; readiness indicates structural correctness, not high predictive skill yet.
- `[validated]` Fresh 2026-04-27 real-engine locked quick check for `usgs_01547700` confirms parameter proposals produce distinct strict-pinned outputs:
  - artifact root: `tests/_artifacts/phase3f_fresh_20260427/usgs_01547700_locked_quick_strict/`,
  - 6 evaluations, 6 distinct NSE values, 0 NaN metric rows after strict-outlet patch,
  - objective traces report requested outlet `1`, selected outlet `1`, `outlet_autodetected=false`.
- `[tentative]` Six-evaluation quick calibration did not improve over the existing benchmark lock (`NSE 0.1256 -> 0.0775`); this is a smoke/provenance check, not a failed full calibration campaign.
- `[validated]` Fresh calibrated-vs-baseline realism audit can now be generated from the best-solution rerun alignment:
  - artifact root: `tests/_artifacts/phase3f_fresh_20260427/usgs_01547700_quick_realism_audit/`,
  - both baseline and quick-calibrated alignments remain `pathological`,
  - quick-calibrated run increased full-period volume overestimation (`PBIAS +54.8%`) and low-flow overestimation (`Q10 ratio 11.11`), reinforcing that Phase 3F physical realism work is still required before broader calibration claims.
- `[validated]` First fresh multi-year Phase 3F run (`usgs_01547700`, 2013-2015) completed end-to-end with real GridMET forcing, real SWAT+ engine execution, 1095 aligned days, and 12 generated diagnostic figures:
  - artifact root: `tests/_artifacts/phase3f_multiyear_20260427/usgs_01547700_2013_2015/`,
  - baseline full-period NSE/KGE: `0.009954/-0.014585`,
  - independent-year split: calibration period 2013-2014 (`730` days), validation period 2015 (`365` days).
- `[validated]` Multi-year locked real-engine calibration smoke (`CN2`, `ALPHA_BF`, 10 evaluations) produced distinct metrics and verified improvement:
  - artifact root: `tests/_artifacts/phase3f_multiyear_20260427/usgs_01547700_2013_2015_locked_cal_quick/`,
  - baseline NSE/KGE: `0.009954/-0.014585`,
  - verified calibrated NSE/KGE: `0.145155/0.038083`,
  - delta NSE/KGE: `+0.135201/+0.052668`,
  - history rows: `10`, unique NSE values: `10`.
- `[validated]` Multi-year calibrated-vs-baseline realism audit shows calibration improves metrics but does not solve physical pathologies:
  - artifact root: `tests/_artifacts/phase3f_multiyear_20260427/usgs_01547700_2013_2015_calibrated_realism_audit/`,
  - full-period PBIAS improves only slightly (`+21.0% -> +19.6%`),
  - BFI overestimation remains (`BFI ratio ~1.43`),
  - low-flow severe overestimation remains (`Q10 ratio ~9.8`),
  - SON seasonal skill remains severely negative.
- `[validated]` For the generated 2013-2015 Marsh Creek topology, forced terminal-outlet scoring is not defensible:
  - strict internal GIS outlet `1`: NSE `0.009954`,
  - terminal GIS outlet `10`: NSE about `-2386.71`,
  - terminal GIS outlet `39`: NSE about `-45727.06`.
  Interpretation: this pipeline can produce a gauge-representative internal channel object; publication-grade reporting must preserve and justify that provenance rather than blindly requiring terminal outlets.
- `[validated]` Multi-year contrast-basin attempt (`usgs_03339000`, 2013-2015) failed before SWAT+ engine execution at the delineation/topology gate, not during calibration:
  - artifact root: `tests/_artifacts/e2e_runs/phase3f_multiyear_20260427_contrast_03339000/`,
  - NLDI basin area: `3340.879 km2`,
  - generated watershed artifact at threshold `500` cells: `1` subbasin, `5331` channels, `19` terminals, total area `0.22 km2`, mean slope `0.0`,
  - final retry raised `Delineation produced zero subbasins`.
  Interpretation: this exposes a large/low-gradient basin portability blocker in outlet snapping/DEM-conditioned delineation. It is not evidence that the locked calibration path failed; the model never reached TxtInOut generation.

## 6. Phase 3F Topology & Portability Lessons (2026-04-27)

- `[validated]` **Max-accumulation outlet snapping for large low-gradient basins**  
  Problem: WBT's `snap_pour_points` finds nearest stream (smallest tributary) instead of main stem. Evidence: 03339000 produced 0.27 km² (3-cell tributary) instead of 2513 km² (main stem at 481m). Fix: `_snap_to_max_accumulation()` raster window search for highest-accumulation cell, not nearest. Adaptive radius `max(500m, √(area_km²) × 30m)` covers typical main-stem offsets (782m for 3340 km² basin). Result: full delineation now possible; 03339000 produced 1065 subbasins end-to-end.

- `[validated]` **O(V+E) cycle removal replaces iterative find_cycle loop**  
  Problem: iterative `nx.find_cycle()` + remove-edge O(k×(V+E)) hangs on large routing graphs. Evidence: 8+ min timeout on 4023 subbasins. Fix: single tri-color DFS pass to identify all back-edges simultaneously. Tested: 5000-node, 300-cycle synthetic graph solved in <5ms; 1065-node production graph in <1s. Impact: enables real-time large-basin routing without structural degradation.

- `[validated]` **Rate-based terminal threshold for DEM-truncated basins**  
  Problem: absolute `max_terminals=5` rejects large basins with legitimate boundary terminals (D8 cycle removal disconnects edge subbasins). Evidence: 03339000 had 78 terminals; hard gate would fail. Fix: `max(5, int(n_subbasins × 0.08))` — small basins floor at 5, large basins allow 8% terminal rate. Result: 78 < effective threshold 85; gate passes while still catching genuinely fragmented basins.

- `[validated]` **Area tolerance must reflect DEM-edge truncation in large basins**  
  Problem: 20% tolerance too strict for D8-routed large basins; routing fragmentation legitimately loses 20–30% upstream area. Evidence: 03339000 had 75% coverage due to 177 back-edge removals; validation gate rejected all stream-threshold attempts. Fix: relaxed default to 30% (`SWATPLUS_AREA_TOLERANCE_PCT` env var) coupled with explicit TOPOLOGY WARNING logging root cause (routing fragmentation, not snap failure). Result: basin proceeds with clear metadata of known limitation.

- `[validated]` **Synthetic soil realism ceiling limits calibration gain**  
  Evidence comparison: 01547700 (95% SSURGO) achieved Δ NSE +0.149 in calibration; 03339000 (100% synthetic fallback) achieved only Δ NSE +0.054 — 2.76× worse. Interpretation: real soils allow model to adjust hydraulic properties to observations; synthetic soils have fixed (incorrect) parameters. Implication: soil replacement is higher ROI than adding calibration parameters for pathological basins. Recommended for Phase 3G: acquire SSURGO/gSSURGO for 03339000, re-calibrate with real soils, expect Δ NSE improvement to +0.15–+0.20.

- `[validated]` **Autumn seasonal skill collapse is not calibration-addressable**  
  Evidence: both 01547700 and 03339000 show severe SON (Sept–Nov) skill deficit independent of calibration. 03339000 baseline SON NSE = −0.956; 01547700 baseline SON NSE = −0.396. Root causes likely: ET model mismatch (autumn senescence), shallow soil depletion, or GW_DELAY parameter. Implication: expanded calibration (more parameters) will not solve autumn dynamics; soil parameter realism and explicit GW modeling must be fixed first. Recommended: after soil replacement, add SURLAG and GW_DELAY calibration, then re-audit seasonal NSE.
- `[validated]` After adaptive max-accumulation outlet snapping and scale-aware topology gates, `usgs_03339000` completed the full 2013-2015 real-engine E2E workflow and became the first successful multi-year contrast basin:
  - final generated area: about `2513.8 km2` vs NLDI `3340.9 km2` (`~75%` coverage),
  - topology gate passed with plausible channel density (`~1.33` channels/subbasin),
  - baseline locked outlet: GIS ID `290`, `outlet_policy="strict"`,
  - baseline NSE/KGE: `0.398815/0.424652`.
- `[validated]` `usgs_03339000` locked real-engine calibration produced independently verified improvement with distinct parameter-response evaluations:
  - artifact roots: `tests/_artifacts/phase3f_03339000_2013_2015_lock/` and `tests/_artifacts/phase3f_03339000_2013_2015_cal_quick/`,
  - calibration parameters: `CN2`, `ALPHA_BF`,
  - history rows: `10`, distinct NSE values: `10`,
  - best parameters: `CN2=52.326847`, `ALPHA_BF=0.223211`,
  - verified NSE/KGE: `0.452761/0.454862`,
  - delta NSE/KGE: `+0.053946/+0.030209`.
  Interpretation: contrast-basin calibration is real and reproducible, but still below benchmark-grade skill and remains constrained by synthetic soils and partial basin coverage.

## 7. Phase 3G Soil Realism Evidence (2026-04-27)

- `[validated]` SDA acquisition can bypass the failing Planetary Computer gNATSGO profile path for `usgs_03339000`:
  - acquisition artifact: `tests/_artifacts/phase3g_03339000_sda_soils_profiles.json`,
  - requested mukeys: `81`,
  - acquired SDA horizon profiles: `77`,
  - coverage: `95.1%`.
- `[validated]` External SDA profile injection can drive the normal E2E editor/import path without post-hoc database mutation:
  - environment hook: `SWATPLUS_EXTERNAL_SOILS_JSON`,
  - E2E artifact root: `tests/_artifacts/e2e_runs/phase3g_03339000_sda_real_soils_e2e_20260427_v2/usgs_03339000/`,
  - profiles written: `81` (`77` external SDA + `4` deterministic local fallbacks),
  - soil metadata: `soil_mode="fallback"`, `pct_fallback_soils=0.0494`,
  - SWAT+ engine completed and produced 1095 aligned days.
- `[validated]` First real-soil locked calibration for `usgs_03339000` improves over its real-soil baseline but does not outperform the previous synthetic-soil calibrated benchmark:
  - lock artifact: `tests/_artifacts/phase3g_03339000_sda_lock/`,
  - calibration artifact: `tests/_artifacts/phase3g_03339000_sda_cal_real/`,
  - strict outlet GIS ID: `255`,
  - baseline NSE/KGE: `0.156718/0.081250`,
  - verified calibrated NSE/KGE: `0.273576/0.184651`,
  - delta NSE/KGE: `+0.116858/+0.103401`,
  - history rows: `10`, distinct NSE values: `10`,
  - best parameters: `CN2=75.0`, `ALPHA_BF=1.0`.
  Interpretation: real horizon soils increased parameter response relative to the real-soil baseline, but the stronger hypothesis that real soils alone would close the 03339000 skill gap is not supported by this run.
- `[validated]` Real-soil calibration improves physical realism diagnostics but leaves material pathologies:
  - realism audit: `tests/_artifacts/phase3g_03339000_sda_realism_audit/`,
  - full-period BFI ratio improved from `1.34` to `1.17`,
  - full-period Q10 ratio improved from `3.19` to `2.10`,
  - full-period PBIAS remains nearly unchanged (`-27.1%` to `-27.0%`),
  - verdict changed from `pathological` to `improving_with_pathologies`.
- `[superseded]` The Phase 3F inference "synthetic soils are the dominant 03339000 calibration ceiling" is now too strong. Phase 3G evidence indicates soil realism helps but does not overcome outlet/coverage/structure limits by itself.

## 8. Phase 3G Sprint 2: Outlet/Topology Comparability (2026-04-27)

- `[validated]` **Different auto-detected outlets across E2E runs produce incomparable metrics**  
  Phase 3F auto-detected outlet GIS ID 290 as best-NSE terminal; Phase 3G v2 auto-detected outlet GIS ID 255. Both outlets are terminal in both topologies (`terminal_outlet_ids` confirmed). Direct metric comparison between Phase 3F (outlet 290) and Phase 3G (outlet 255) is invalid — it conflates soil replacement with outlet selection.  
  Artifact: `tests/_artifacts/phase3g_03339000_outlet_comparability/outlet_comparison.csv`

- `[validated]` **Cross-outlet evaluation disentangles soil-replacement vs outlet-selection effects**  
  Method: `evaluate_run` with `outlet_policy='strict'` applied to all four channel_sd_day.txt files (Phase 3F/3G baseline and calibrated best) at both outlets 255 and 290.  
  Results (NSE):

  | Condition | Outlet 255 | Outlet 290 | Dominant outlet |
  | --- | ---: | ---: | --- |
  | Phase 3F baseline (synthetic) | 0.3184 | **0.3988** | 290 |
  | Phase 3G baseline (real SDA) | **0.1567** | 0.0564 | 255 (baseline only) |
  | Phase 3F calibrated (CN2=52.33, ALPHA_BF=0.2232) | 0.3423 | **0.4528** | 290 |
  | Phase 3G calibrated (CN2=75.0, ALPHA_BF=1.0) | 0.2736 | **0.3176** | 290 |

- `[validated]` **Real SDA soils degraded calibration skill at both outlets (holding outlet constant)**  
  Soil-replacement effect (Δ = Phase3G − Phase3F at the same outlet):  
  - Outlet 255: baseline Δ = −0.1617, calibrated Δ = −0.0688  
  - Outlet 290: baseline Δ = −0.3424, calibrated Δ = −0.1352  
  Interpretation: real SSURGO soil horizons raised BFI_sim from ~0.61 to ~0.71 (observed BFI_obs = 0.537). The model routes too much flow through slow baseflow pathways with real hydraulic conductivity values, and this cannot be corrected by CN2/ALPHA_BF calibration alone.

- `[validated]` **Phase 3G calibrated converged to boundary parameters (ALPHA_BF=1.0), signaling parameter identifiability failure at outlet 255**  
  When calibration locks onto a boundary value (ALPHA_BF=1.0 = maximum), the optimizer is saturating the search space without finding a physical optimum. This indicates outlet 255 may not be the correct gauge-representative outlet.

- `[validated]` **Phase 3G calibration objective_run directories share hash names with Phase 3F but contain genuinely different simulations**  
  Content-addressable hash is computed from parameters + outlet only, not from soil source. Same hash directories appear in both calibrations but contain different channel_sd_day.txt files (confirmed by SHA256: `b4b3bbf1...` for Phase 3F eval 5 vs `7bc57e27...` for Phase 3G same-parameter run). Real SDA soils were genuinely executed in Phase 3G calibration.

- `[decision]` **Do not run new calibration until GIS-correct outlet is confirmed**  
  Outlet 290 consistently outperforms outlet 255 for both simulation types at the calibrated level. The correct outlet must be identified by comparing GIS ID 255 and GIS ID 290 channel endpoints against USGS gauge 03339000 coordinates (39.4789° N, 87.3931° W). Running calibration at the wrong outlet produces structurally invalid results regardless of soil quality.

## 9. Phase 3G Sprint 3: Outlet Confirmation & Soil-Replacement Baseline (2026-04-28)

- `[validated]` **Outlet confirmation via GIS drainage area: 255 vs 290**  
  Evidence from chandeg.con in both Phase 3F and Phase 3G v2: GIS ID 290 is unambiguously the main-stem outlet (drainage area 862 ha vs 157 ha for 255 — a 5.5× difference). Both outlets are terminal in the watershed routing topology. Neither outlet is at the physical gauge (39.4789°N, 87.3931°W); both are in eastern Illinois, ~72–96 km NNW. The model's outlet snap (lat 40.104°N, lon 87.600°W) is displaced 72 km north from the real gauge, a pre-existing delineation limitation already documented in metadata.json (`area_diff_pct: -24.8%`, `centroid_distance_km: 9.2`). **Decision: outlet 290 is the model's main-stem terminus and anchor for calibration work.**  
  Artifact: `tests/_artifacts/phase3g_03339000_outlet_comparability/outlet_confirmation.md`

- `[validated]` **Re-locked Phase 3G baseline at outlet 290 (real SDA soils, 95.1% real SSURGO)**  
  Lock artifact: `tests/_artifacts/phase3g_03339000_sda_outlet290_lock/`  
  - Baseline NSE/KGE: 0.0564 / 0.2213 (strict outlet policy, outlet=290)  
  - Matches Sprint 2 cross-eval prediction (phase3g @ outlet 290 baseline = 0.0564) exactly  
  - This baseline is now directly comparable to Phase 3F baseline @ outlet 290 (NSE 0.3988)

- `[validated]` **Re-calibrated Phase 3G at outlet 290 (CN2 + ALPHA_BF, 10 evals, real SDA soils)**  
  Calibration artifact: `tests/_artifacts/phase3g_03339000_sda_outlet290_cal/`  
  - Best-calibrated NSE/KGE: 0.3581 / 0.3334  
  - Best parameters: CN2=48.77, ALPHA_BF=0.505  
  - Δ NSE: +0.3016 (baseline 0.0564 → calibrated 0.3581)  
  - BFI_sim: 0.6617 (vs BFI_obs 0.537 → ratio 1.232, excess baseflow)

- `[validated]` **Definitive soil-replacement comparison at outlet 290: real SDA soils UNDERPERFORM synthetic**  

  | Condition | Soil | Baseline NSE | Calibrated NSE | Δ NSE | BFI_sim ratio |
  |---|---|---|---|---|---|
  | Phase 3F | Synthetic (100%) | 0.3988 | 0.4528 | +0.0539 | 1.106 |
  | Phase 3G | Real SDA (95.1%) | 0.0564 | 0.3581 | +0.3016 | 1.232 |
  | **Difference** | | **−0.3424** | **−0.0947** | **+0.2477** | **+0.126** |

  **Soil-replacement conclusion:** Real SSURGO soils produce a **catastrophically worse baseline** (NSE 0.0564 vs 0.3988, a −86% skill collapse). Calibration gains are 5.6× larger with real soils (+0.3016 vs +0.0539), indicating much higher parameter sensitivity. However, even after aggressive calibration (ALPHA_BF pushed to 0.505), Phase 3G calibrated (0.358) still underperforms Phase 3F calibrated (0.453) by 0.095 NSE. **Real soils are not the limiting factor.** The baseline collapse signals a structural mismatch (wrong outlet, routing, forcing, or basin coverage) that real soil hydraulics cannot overcome.

- `[validated]` **BFI pathology worsens with real SDA soils; CN2/ALPHA_BF calibration insufficient**  
  Real SSURGO hydraulic conductivity raises BFI_sim/BFI_obs ratio from 1.106 (synthetic) to 1.232 (real). The model routes 23% more flow through baseflow with real soils. CN2 (surface runoff partitioning) and ALPHA_BF (recession rate) cannot fully compensate for the underlying hydraulic conductivity mismatch. This indicates:
  1. Real soils may not be correctly adjusted for this basin (SOL_AWC, SOL_K values may be off).
  2. Model structure (2-aquifer cascade, GW routing, revap) may not match hydrologic response.
  3. Parameters like GW_DELAY, GWQMN, SOL_K may be required to tune baseflow generation.

- `[decision]` **Next step: structural diagnostics, not parameter expansion**  
  Evidence shows that baseline NSE is the bottleneck, not calibration gain. Before attempting to fit more parameters (SOL_K, GW_DELAY, CH_K2), diagnose the baseline collapse:
  1. **Multi-year cal/val split** — are current results overfitted within 2013-2015?
  2. **Outlet validation** — is outlet 290 genuinely the gauge-representative terminus?
  3. **Forcing audit** — does GridMET cumulative precipitation match observed streamflow volume over 3 years?
  4. **Routing audit** — do automated topology/routing parameters match known basin structure?
  Expanded calibration without understanding the baseline collapse will produce false confidence. Research-grade claims require isolating whether the problem is (a) soil/parameter tuning, (b) delineation/outlet, (c) forcing, or (d) model structure.

## 10. Open Questions

- `[open]` Which outlet (255 or 290) geographically corresponds to USGS gauge 03339000 at Terre Haute, IN? Requires GIS coordinate comparison of channel endpoints in chandeg.con / GIS vector data.
- `[open]` Why real SDA soils raised BFI_sim to 0.71 vs BFI_obs 0.537 — is this a soil hydraulic conductivity error, a routing configuration issue, or a model structure limitation?
- `[open]` Whether CN2/ALPHA_BF calibration can recover any of the real-soil skill loss, or whether additional parameters (SOL_K, CH_K2, GW_DELAY) are required.
- `[open]` Why some basins remain strongly negative NSE after bridge hardening despite non-zero sensitivity.
- `[open]` Whether additional physically meaningful parameters should be unlocked before broad calibration campaigns.
- `[open]` Best threshold policy for auto-switching proposal source when history appears flat.
- `[open]` Whether locked benchmark artifacts should reject non-terminal pinned outlets at lock time or allow strict scoring with explicit `strict_requested_outlet_non_terminal` provenance.
- `[open]` Whether physical realism improvement should next target baseflow/storage parameters, channel routing structure, or soil hydraulic conductivity; multi-year evidence shows metric lift without resolving BFI/low-flow/SON pathologies.
- `[open]` How to make large-basin delineation robust enough for basins like `03339000`: candidates include stronger area-ratio preflight failure, larger outlet snap search, hydrofabric-guided snapping, NHDPlus flowline anchoring, or explicit user-provided pour points.

## 10. Deprecated or Rejected Assumptions

- `[rejected]` "If routing tables exist, channels are always active at runtime."  
  Rejection basis: prior zero-flow channel outputs despite populated routing artifacts.
- `[rejected]` "pySWATPlus objective values are authoritative."  
  Rejection basis: parity mismatch history; now `evaluate_run` is authoritative.
- `[rejected]` "Flat calibration history implies no parameter sensitivity."  
  Rejection basis: manual CN2 perturbation changed outputs while bridge remained flat.

## Append-Only Evidence Updates

This file is append-only for operational evidence. Status transitions must be explicit (`superseded`/`rejected`) and never remove prior entries.
