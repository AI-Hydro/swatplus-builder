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

## 6. Open Questions

- `[open]` Why some basins remain strongly negative NSE after bridge hardening despite non-zero sensitivity.
- `[open]` Whether additional physically meaningful parameters should be unlocked before broad calibration campaigns.
- `[open]` Best threshold policy for auto-switching proposal source when history appears flat.
- `[open]` Whether locked benchmark artifacts should reject non-terminal pinned outlets at lock time or allow strict scoring with explicit `strict_requested_outlet_non_terminal` provenance.
- `[open]` Whether physical realism improvement should next target baseflow/storage parameters, channel routing structure, or soil hydraulic conductivity; multi-year evidence shows metric lift without resolving BFI/low-flow/SON pathologies.
- `[open]` How to make large-basin delineation robust enough for basins like `03339000`: candidates include stronger area-ratio preflight failure, larger outlet snap search, hydrofabric-guided snapping, NHDPlus flowline anchoring, or explicit user-provided pour points.

## 7. Deprecated or Rejected Assumptions

- `[rejected]` "If routing tables exist, channels are always active at runtime."  
  Rejection basis: prior zero-flow channel outputs despite populated routing artifacts.
- `[rejected]` "pySWATPlus objective values are authoritative."  
  Rejection basis: parity mismatch history; now `evaluate_run` is authoritative.
- `[rejected]` "Flat calibration history implies no parameter sensitivity."  
  Rejection basis: manual CN2 perturbation changed outputs while bridge remained flat.

## Append-Only Evidence Updates

This file is append-only for operational evidence. Status transitions must be explicit (`superseded`/`rejected`) and never remove prior entries.
