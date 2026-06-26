# swatplus-builder

## What It Is

`swatplus-builder` is an agent-governed Python pipeline for building,
running, diagnosing, and calibrating SWAT+ models from USGS watershed requests.
Its central design rule is that the package is the scientific authority and the
agent is only the operator. Production readiness means every claim is backed by
runtime gates, provenance, diagnostics, and machine-readable evidence.

## Status

Active hardening toward research-grade production pipeline. Last updated:
2026-06-26.

## Where To Read Next

- Continue work: `ROADMAP.md` and latest `PROGRESS.md` entry.
- Understand current blockers: `docs/PIPELINE_RESEARCH_GRADE_AUDIT.md`.
- Understand agent-governed principles:
  `docs/AGENT_GOVERNED_RESEARCH_SOFTWARE_GUIDE.md`.
- Understand workflow contracts: `docs/SCIENTIFIC_AGENT_WORKFLOW_CONTRACT.md`.
- Understand claim tiers and gates: `docs/SCIENTIFIC_CLAIM_GOVERNANCE.md`.
- Modify calibration or hydrology behavior:
  `docs/SWATPLUS_MODELING_PLAYBOOK.md` and
  `docs/CALIBRATION_PARAMETER_REGISTRY.md`.
- Operate as an executor agent: `docs/AGENT_WORKFLOW.md`.
- Track lessons that generalized across basins: `docs/PIPELINE_LEARNING_LOG.md`.

## Current State

- Current hardening evidence lives under
  `/Users/mgalib/swatplus_runs/e2e_hardening_20260626/`. The latest verified
  set has three current runs: `01547700_2010_2018_diag` completed with
  diagnostic-guided locked calibration (`NSE=0.3440`, `KGE=0.4551`,
  `PBIAS=7.34%`, diagnostic tier); `03349000_2010_2018_diag` now completes
  diagnostic calibration after sensitivity-guided anchor combinations fixed a
  false volume-gate block (`verified NSE=-0.149`, `KGE=0.475`,
  `PBIAS=15.51%`, diagnostic tier with weak absolute skill retained);
  and `01031500_2010_2018_nocal` has now had diagnostic calibration attempted
  after the original no-calibration run. The `01031500` calibration is
  classified as `attempted_failed_or_blocked` in `kge_nse_finetune` because no
  prior volume-valid candidate also passed calibration process gates; mass
  imbalance remains the dominant retained blocker. The stale interrupted
  `01031500_2010_2018_diag` calibration scratch folder was removed before this
  superseding evidence.

- Dashboard and spatial overview hardening is now active: dashboards expose
  calibration method, history, best solution, calibrated alignment, and
  calibration progress; basin overview figures use a common basin reference,
  vector subbasin/HRU/stream panels where possible, masked rasters, visible
  outlets, and deterministic layout spacing.

- Automated calibration now uses a package-owned diagnostic-guided DDS
  contract: basin-specific sensitivity screen, phased volume/baseflow/peak
  timing/KGE-NSE search, optional recent real-engine screening window for long
  records, and full locked verification as the only final metric authority.
  End-to-end runs also promote `dashboard.html` into
  `evidence_summary.json`, `EVIDENCE_SUMMARY.md`, and `run_manifest.json`.
  Screening-window metrics remain triage evidence only.

- Current active diagnostic is the `01031500` outlet/evaluation repair. The
  NLDI-masked run at
  `/Users/mgalib/swatplus_runs/recovery_01031500_nldi_mask_20260625/` passed
  geometric checks but initially produced a near-zero selected-terminal
  hydrograph at GIS `259` (`PBIAS=-99.12%`). The model was not dry: upstream
  main-stem channels carried basin-scale flow. The evaluator now uses a
  topology-owned `terminal_inflow_sum` for converted terminal outlets when the
  terminal state table is non-accumulating; for `01031500` this uses parent GIS
  IDs `[231, 247]` plus terminal GIS `259`, improving volume to
  `PBIAS=-1.41%`. Skill remains poor (`NSE=-1.0798`, `KGE=0.2083`) because the
  response is too flashy and baseflow persistence remains weak. A first
  corrected-objective real-engine calibration probe confirmed fresh output.
  A governed 2007-2012 screening window now exists and rejects two simple
  calibration directions: `LATQ_CO=0.003`/`SURLAG=12` and
  `CN2=65`/`CN3_SWF=0.5`/`SURLAG=12` both worsen NSE/KGE relative to the
  corrected baseline. No candidate from that screen is promoted to full-window
  verification; next hypotheses should target aquifer/baseflow controls,
  snow/precipitation timing, or routing concentration separately.

- Cross-basin full-overlay validation is active on USGS `03349000`. The fresh
  corrected run at
  `swatplus_runs/cross_basin_03349000_topology_fixed_20260619/` retains all 39
  delineated subbasins, passes outlet and routing-flow checks, and exposes a
  genuine ET-dominated hydrologic deficit rather than an outlet-selection
  failure. Its current baseline is exploratory (`NSE=-0.3168`, `KGE=0.0524`,
  `PBIAS=-58.00%`). This run also drove fixes for full-overlay HRU vectorization
  scalability, flow-accumulation-based D8 successor resolution, and
  one-at-a-time sensitivity baseline leakage. A fresh bounded `PET_CO=0.8`
  diagnostic improved the metrics but still failed `VOLUME_BIAS` and
  `NEGATIVE_SKILL`. Subsequent source-backed corn-soy management, `ESCO=1.0`,
  and land-use-scoped AGRL CN `+4` experiments were also rejected by fresh
  metrics and unchanged gates. A five-point Daymet comparison is only `2.1%`
  wetter than GridMET and does not support a global forcing multiplier. The
  current leading target is the low simulated baseflow/subsurface response
  (`BFI_sim` about `0.21` versus `BFI_obs=0.562`), with broad calibration
  deferred until spatial parameter semantics are preserved.

- Active phase: 2026-06-15 scientific-correctness remediation plan. Phase A
  slope nodata masking, Phase F.1/F4 spatial/water-balance visuals, Phase D1
  land-use fidelity disclosure/gating, Phase F6 HRU/land-use composition
  visualization, Phase F5 forcing-context visualization,
  Phase D2 vintage-aware NLCD selection/provenance plumbing, Phase D3
  terrain/climate-default disclosure, and Phase C full-overlay HRU decision
  evidence,
  and the first Phase B
  water-balance/subsurface prior correction are implemented and verified on
  real `01547700` artifacts. Phase B still needs broader basin validation
  before it should be treated as generally proven.
- Latest live remediation run:
  `swatplus_runs/phaseE_01547700_clean_20260616_2000_2019/` completed a clean
  20-year `01547700` workflow on 2026-06-16/17 with build, SWAT+ engine
  execution, benchmark lock, gated calibration, locked verification, and plot
  generation. The run was requested as `research_grade` with accepted contract
  metadata, and the package allowed contract, fresh-output, benchmark-lock,
  outlet-provenance, routing-flow, calibration-improvement, sensitivity, soil
  fidelity, and locked-verification claims. It still kept
  `effective_claim_tier=exploratory`: final verified metrics improved from
  baseline (`NSE=0.0138`, `KGE=0.1127`, `PBIAS=7.18%`) to locked verification
  (`NSE=0.1742`, `KGE=0.1538`, `PBIAS=-16.65%`), but research skill remains
  below threshold; land-use fidelity remains degraded because dominant-only
  HRUs retain 3 of 15 source land-use classes (`retention_fraction=0.20`);
  and terrain/lapse-derived claims remain diagnostic-only because
  `dist_cha` is constant and lapse corrections are disabled over about
  `496 m` relief. The subsurface prior was applied honestly:
  pre-prior `WYLD/P=0.134` against observed `Q/P=0.453`, post-prior
  `WYLD/P=0.509`; routing-flow gates passed with selected terminal GIS `29`.
  The plot suite emitted spatial overview, forcing context, water balance, and
  HRU/land-use composition figures. Earlier prepared-artifact validations on
  `03351500` and `01493500` remain useful negative controls showing the
  subsurface prior is withheld when the package evidence points to ET-dominated
  deficits rather than excessive percolation.
- Authoritative objective-suite status as of 2026-06-17:
  the summarize-only report has been regenerated from existing evidence with
  the clean `01547700` run and fresher `01493500`/`03351500`/`02129000`
  overrides. It still reports `research_grade_count=0/11`; blocker domains are
  `science=6`, `provenance=3`, `diagnostics=2`; the target hypothesis remains
  `not_supported_by_current_evidence`; and the production compliance audit is
  `complete` (`17/17`). This is the current suite-level status; older embedded
  `69/97`, `96/97`, or one-research-grade statements are historical context.
- Phase C decision evidence now exists for the same real `01547700` F6
  artifact at
  `swatplus_runs/realtest_01547700_phaseF6_landuse_composition/reports/phaseC_full_overlay_threshold_probe_nodata_fixed.json`.
  A full-overlay HRU nodata bug was fixed first: raster-declared land-use
  nodata, including NLCD-style `127`, is now excluded from HRU combinations
  and recorded in `hru_catalog.json`. The regenerated threshold sweep has no
  `lu_127` retained class. For this basin, `min_hru_fraction=0.001` retains all
  15 source land-use classes with `1871` HRUs in about `19.8 s`; no-filter
  full overlay retains all 15 classes with `3320` HRUs in about `32.4 s`;
  `0.005` is smaller (`858` HRUs) but retains only `11/15` classes. The
  canonical workflow and MCP launcher now expose this as an explicit
  `--hru-mode full_overlay --min-hru-fraction <fraction>` option for
  research-grade land-use fidelity probes; the default HRU mode has not been
  changed.
- A real canonical full-overlay workflow has now been run through that surface:
  `swatplus_runs/phaseC_01547700_full_overlay_20260617_2000_2019_nocal/`.
  The run completed with `--hru-mode full_overlay --min-hru-fraction 0.001`
  and `--no-calibrate`, producing `1876` HRUs across `31` subbasins and
  retaining `14/15` source land-use classes (`retention_fraction=0.9333`;
  missing `UCOM`). The first generated run exposed a package construction bug:
  `rout_unit.def` referenced only one positive HRU element per routing unit,
  so most full-overlay HRU elements in `rout_unit.ele` were disconnected from
  the routing network. That bug produced the near-zero outlet hydrograph
  (`PBIAS=-98.3%`) while still using the correct terminal outlet GIS `29`.
  The routing fix now expands each routing unit to all owned HRU elements and
  validates that every `rout_unit.ele` HRU appears exactly once in
  `rout_unit.def`. A fixed-copy SWAT+ probe on the same full-overlay
  `01547700` TxtInOut raised strict outlet GIS `29` simulated volume from
  `217.8` to `10795.9` m3/s-days over the benchmark alignment and improved
  baseline metrics to `NSE=0.0997`, `KGE=0.0772`, `PBIAS=-17.4%`. This
  supersedes the earlier interpretation that the blocker was outlet/channel
  mass-transfer alone. This was later rerun through the canonical evidence path
  after the LTE transfer-length and hydrology-prior fixes below.
- A follow-up Marsh Creek peak-diagnosis ladder isolated an additional
  converted-topology routing regression: carrying real `hyd-sed-lte.cha:len`
  values into the full-mode `sdc`/`chandeg.con` compatibility path delayed the
  September 2004 basin-generated runoff pulse from the observed outlet peak date
  (`2004-09-18`) to `2004-09-24`. Lowering Manning roughness and seepage did not
  move the peak; near-zero LTE transfer lengths did. The converter now writes
  `hyd-sed-lte.cha:len=0.00050 km` as an explicit engine/topology compatibility
  transfer length while preserving physical channel geometry in the source
  GIS/channel data. The native editor GIS import path now writes the same
  compatibility value into `hyd_sed_lte_cha.len`; canonical validation showed
  all `31` rows at `0.0005` while source `gis_channels.len2` retained physical
  lengths (`164.13-5663.62 m`). A 20-year fixed full-overlay probe with this
  restored stabilization improved baseline metrics to `NSE=0.2804`,
  `KGE=0.2662`, `PBIAS=-13.7%`, but still undercaptured the largest flood peak
  (`sim_max=22.17 m3/s` vs `obs_max=126.86 m3/s`), so peak-flow claims remain
  blocked pending separate process/forcing evidence. The canonical 2026-06-18
  no-calibration full-overlay validation at
  `swatplus_runs/patch_validate_01547700_lte_len_importer_20260618/` now locks
  the same recovered volume behavior after cached/retried NWIS observed-flow
  acquisition and package-owned subsurface-prior state detection:
  `selected_outlet_gis_id=29`, `NSE=0.2804109215855428`,
  `KGE=0.2665468454841228`, `PBIAS=-13.617382816533395`,
  `locked_calibration_ready=true`. Diagnostic parameter isolation in
  `reports/hydrology_parameter_isolation_20260618.json` shows the prior repair
  is dominated by `LATQ_CO=0.08`, with `PERCO=0.75` providing the remaining
  volume recovery; `CN3_SWF` is not material for this regression.
- The current `01547700` peak-flow blocker is no longer outlet selection or
  missing rainfall. Corrected daily basin water-balance diagnostics at
  `swatplus_runs/patch_validate_01547700_lte_len_importer_20260618/reports/peak_response_forcing_diagnostics_20260618.json`
  show the major storms are present in SWAT+ forcing, but high-flow days remain
  muted: the upper 0.1% observed-flow days carry only about `16%` as much
  simulated flow in the recovered baseline. Event windows route much of storm
  water into lateral flow/percolation/storage instead of fast surface response
  (`surq_gen/P` about `0.047-0.131` across the checked peak windows). Two
  temporary parameter screens, stored only as compact reports, identify
  lateral-flow delivery and surface-runoff timing as the active next
  hypothesis. The best balanced candidate, `LATQ_CO=0.20, SURLAG=1.0`, has now
  been independently rerun against the locked benchmark under
  `reports/locked_candidate_latq_surlag_20260618/`. It improved the recovered
  benchmark from `NSE=0.2804109215855428`, `KGE=0.2665468454841228`,
  `PBIAS=-13.617382816533395` to verified `NSE=0.342880294416419`,
  `KGE=0.45218154428386403`, `PBIAS=-1.2497238817010707`, with the package
  candidate water-balance/process gate passing and no condition codes. This is
  a verified improvement, but not a peak-magnitude solution: top-0.1% flow
  ratio improved only to `0.257`, and `2004-09-18`/`2008-03-05` peak ratios
  remain `0.202` and `0.121`. Peak-flow claims remain limited while the next
  experiment targets peak magnitude/shape without sacrificing the volume gate.
- Continuing that branch, `LATQ_CO=0.20, SURLAG=1.0, CN2=78` is now the
  strongest verified `01547700` candidate. Fresh locked verification under
  `swatplus_runs/patch_validate_01547700_lte_len_importer_20260618/reports/locked_candidate_latq_surlag_cn2_78_20260618/`
  improved the recovered benchmark to `NSE=0.35566856403724056`,
  `KGE=0.49038217013548413`, `PBIAS=1.3632391338746341`, with candidate
  physical/process gates passing. Peak-tail response improved to q999
  simulated/observed ratio `0.299`, but flood-peak claims remain blocked:
  `2004-09-18` and `2008-03-05` peak ratios are only `0.231` and `0.180`.
  `reports/event_runoff_depth_vs_forcing_20260618.json` shows the largest
  two events have high observed runoff demand relative to generated
  precipitation, while the USGS drainage-area check is within about `0.5%` of
  the delineated area. A narrow snow-threshold screen
  (`reports/snow_threshold_screen_after_verified_cn2_20260618.json`) did not
  justify snow controls as the primary fix: the best snow variant raised q999
  only to `0.308` while lowering NSE to `0.340`. Next hypothesis is forcing
  representativeness/event precipitation and structural peak attenuation, not
  outlet selection or simple snow-threshold tuning.
  A global precipitation multiplier screen
  (`reports/forcing_scale_screen_after_verified_cn2_20260618.json`) confirms
  the model is storm-forcing-sensitive but also rules out a simple multiplier
  as a valid fix: `+5%` precipitation raises q999 to `0.321` but PBIAS to
  `10.1%`; `+20%` raises q999 to `0.388` but fails the water-balance gate with
  `PBIAS=36.4%` and `VOLUME_BIAS`. Any forcing correction must be
  meteorologically source-backed rather than calibrated as a blanket scale.
- Full-overlay `01547700` calibration has been attempted against the locked
  full-overlay benchmark. Direct `locked-calibrate` probes failed honestly in
  the `volume` phase: baseline outlet metrics were about `NSE=-0.2556`,
  `KGE=-0.4902`, `PBIAS=-98.33%`; no tested candidate passed the promotion
  gate `abs(pbias) <= 30`. This means the package is calibrating, but claim
  governance correctly refuses to promote a calibration while the outlet volume
  evidence is invalid. The `locked-calibrate --json` failure path now returns
  structured JSON errors, and locked sensitivity screening now writes live
  `sensitivity_screen_progress.json` progress artifacts during long screens.
- New clean builds now select the supported NLCD epoch nearest the simulation
  midpoint and write `raw/nlcd_selection.json`; land-use fidelity, spatial
  overview, and volume diagnostics read that selection instead of assuming
  `nlcd_2021.tif`. Existing remediation runs that already used NLCD 2021 remain
  historically valid evidence of their own run state.
- D3 terrain/climate assumptions are now disclosed as evidence rather than
  implied away. The real `01547700` F6 artifact has 62 topography rows,
  `slp_len/lat_len` values of `10, 60, 121`, constant `dist_cha=121`, lapse
  disabled (`lapse=0`, `plaps=0`, `tlaps=0`) over about `496 m` DEM relief, and
  25 distributed weather stations. This blocks terrain/lapse-derived claims but
  does not change hydrology.
- Current canonical command:

```bash
swat workflow run \
  --usgs-id <id> \
  --model-family full \
  --start YYYY-MM-DD \
  --end YYYY-MM-DD \
  --warmup-years N \
  --calibrate \
  --claim-tier diagnostic|research_grade \
  --json
```

- Working capability: canonical workflow command exists; contract policy can
  downgrade claim allowance; `effective_claim_tier` records the tier supported
  by the completed evidence; full-mode parameter governance is centralized for
  the ten required parameters plus governed extended snow controls
  (`SFTMP`, `SMTMP`), the source-backed lateral-flow recession control
  (`LAT_TTIME`), the soft surface-runoff control (`CN3_SWF`), and governed
  channel-routing attenuation controls (`CH_N2`, `CH_K2`); low-baseflow skill
  diagnostics now avoid legacy `GW_DELAY`/`GWQMN` tuning advice and route
  subsurface/recession probes through governed full-mode controls; high
  observed runoff-fraction volume diagnostics also avoid `GW_DELAY` and use
  governed snow/subsurface controls; empty run directories enter a package-owned
  full-build handoff; prepared run directories are clean-rerun, evaluated, and
  locked before calibration; full-mode prepared and candidate TxtInOut copies
  are normalized before fresh solver execution so legacy `tot` routing-unit
  rows cannot be scored or locked; physical gates, routed-flow gates,
  sensitivity evidence, locked calibration verification, and research metric
  thresholds now feed allowed/blocked claims. Objective reports now retain
  verified channel-routing refinement evidence as locked-rerun evidence instead
  of treating the temporary search metrics as final. Failed or blocked
  calibration rows also retain the best failed parameter vector from
  `calibration_reports_locked/history.csv` plus registry-backed bound-hit
  context and a diagnostic-only skill/volume tradeoff frontier
  (`best_abs_pbias`, `best_kge`, `best_nse`), so non-promotable candidates remain
  auditable without becoming final evidence. Terminal-scope volume diagnostics
  now retain all-terminal aggregation-validity context from
  `terminal_trace.json`; terminal inventories compute upstream footprints from
  the emitted `chandeg.con` SWAT+ routing table keyed by GIS ID, so unused raw
  delineation-graph branch candidates are not promoted into terminal-overlap
  claim blockers. Real emitted split routing still records pairwise overlap
  evidence and future routing-flow gate payloads promote the same overlap
  summary into `routing_flow_gates.json`, so runtime claim governance can
  classify `terminal_topology_overlap` before volume diagnostics run when it is
  present in the actual SWAT+ routing table. Explicit virtual all-terminal
  runs that pass `virtual_outlet_scope_gate` now keep selected-terminal
  hydrograph diagnostics as contrast evidence without letting those diagnostics
  re-block the claim-authoritative virtual outlet scope. Terminal-scope blockers now retain
  diagnostic hydrograph scope even when the physical gate is not a
  `VOLUME_BIAS` row: the workflow uses locked calibrated alignment/channel
  outputs for the sidecar, and the objective report preserves that evidence for
  rows such as `02129000` where terminal scope, not hydrologic volume skill, is
  the current claim blocker. Objective report rows also carry
  `physical_gates_path`, making each physical/mass/ET/volume/skill blocker
  traceable to the package-owned gate artifact rather than only to summarized
  condition codes; the objective audit now verifies that every row's physical
  status and condition codes match the referenced `physical_gates.json`.
  Multi-terminal rows now also carry a package-owned terminal area-scope
  classification showing whether selected-terminal area is partial while
  all-terminal area matches the NLDI/reference basin, so terminal-scope
  blockers are machine-readable rather than inferred from ratios. Active
  low-skill rows now also carry package-owned skill-limitation classes, so
  timing/correlation, snow/peak-response, variability, bias, baseflow, and
  mixed skill blockers are claim-governed evidence rather than prose-only
  interpretation. Future locked diagnostic calibration runs now include
  screened `SFTMP` and `SMTMP` snow-threshold controls in the `peaks_timing`
  phase alongside surface-runoff lag and channel-routing controls, so snow
  timing blockers are tested before final KGE/NSE finetuning rather than only
  in the all-parameter final phase. Future locked calibration now also blocks
  `kge_nse_finetune` phase entry when prior candidate physical/process-gate
  evidence exists but no earlier volume-valid candidate has passed the
  calibration process gate; `history.csv` records
  `blocked_preceding_process_gate` before raising. Future calibration
  histories also retain
  diagnostic-only selected-vs-all terminal candidate metrics for multi-terminal
  runs, so failed searches can separate selected-outlet scope from persistent
  all-terminal volume or hydrologic skill failures without promoting
  all-terminal metrics to final evidence.
  Current terminal-scope hydrograph diagnostics also retain package-owned
  scope classes, separating selected-terminal metric passes with partial basin
  support, all-terminal volume correction with remaining skill limits,
  persistent post-aggregation volume deficits, nearest-terminal outlet clues,
  and invalid all-terminal aggregation from topology overlap. Terminal
  inventories now also retain official USGS Site Service drainage-area
  authority checks (`terminal_authority_area_check`) alongside NLDI/reference
  area, so selected/all-terminal scope can be compared against gauge metadata
  before any outlet claim advances. Rows where the official area supports the
  all-terminal footprint now also emit diagnostic-only virtual all-terminal
  outlet candidates with no claim authority, no temporary-metric promotion, and
  an explicit fresh locked-rerun requirement before any virtual outlet claim
  can advance. Objective-suite summaries now also retain virtual outlet scope,
  policy, terminal GIS IDs, authority, and `virtual_outlet_scope_gate` evidence
  for future virtual all-terminal workflow rows; the production audit enforces
  the contract before any such rows can become claim evidence. Residual
  all-terminal volume deficits now also retain
  `post_aggregation_process_context`, separating degraded soil provenance,
  high runoff demand, low SWAT water yield, ET, subsurface partition, and
  runoff-generation clues before another parameter search is interpreted; the
  canonical workflow promotes this context into `evidence_summary.json` values
  and calibration provenance rather than leaving scripts to infer it.
  Future canonical
  workflow evidence summaries and calibration provenance now promote those
  terminal hydrograph scope classes, flags, recommended focus, and claim impact
  directly into the main evidence bundle.
  Active `MASS_IMBALANCE` rows now also retain
  `reports/mass_balance_diagnostics.json`, with closure residual, wetland
  outflow, ET coupling, source-backed alternatives, and probe order before
  any mass-closure claim can be promoted.
  `03353000` also retains a
  diagnostic-only bound-interaction screen showing that `CN2=98`, `PET_CO=0.8`,
  and `ESCO=0.01` still misses the volume gate (`PBIAS=-35.16%`). Future workflow evidence summaries promote
  calibration failure phase, failure message, final-metric authority, and the
  temporary-candidate guard directly into `values`. Future calibrated evidence
  also separates `calibration_locked_verification_succeeded`,
  `calibration_locked_rerun_improved`,
  `calibration_final_claim_gates_passed`, and
  `calibration_claim_status` from `calibration_success`, so a verified locked
  diagnostic rerun can be reported without promoting a research-grade skill
  claim. JSON workflow runs now suppress internal stdout/stderr while
  preserving a parseable final stdout payload, and the discard streams remain
  writable for retained third-party shutdown hooks.
- Current blocker: the 2026-05-24 objective-suite evidence harness covers 11
  evidence summaries and the compliance audit remains `96/97`. Terminal-scope
  rows now carry package-owned `terminal_scope_resolution_plan` evidence before
  claim promotion, official-area matching multi-terminal rows carry
  diagnostic-only virtual all-terminal outlet candidates, residual
  post-aggregation volume-deficit rows carry process-context evidence, every
  calibration-history row carries machine-readable phase parameter
  coverage/counts from `calibration_reports_locked/history.csv`, every
  non-research row carries machine-readable `blocker_domain` and
  `blocker_action_items`, and the root report carries
  `target_hypothesis_evaluation=not_supported_by_current_evidence` plus a
  machine-readable `pipeline_improvement_plan` for the active diagnostics and
  provenance gaps. That plan now includes per-basin executable entries with
  current artifact pointers and diagnostic-only authority flags for the six
  non-science blocker rows, plus typed `decision_request` payloads that require
  user-or-policy outlet-scope decisions for provenance rows and keep
  diagnostics rows explicitly diagnostic-only. The typed decision builder is
  package-owned in `swatplus_builder.output.volume_diagnostics`, and future
  workflow evidence promotes `terminal_scope_decision_request` into
  `evidence_summary.json` values and calibration provenance instead of leaving
  objective scripts to define terminal-scope policy. Provenance decisions now
  also carry outlet-scope evidence for `01013500` and `02129000`, including the
  official authority-area class, selected-vs-all-terminal authority-area
  fractions, virtual all-terminal candidate status, terminal GIS IDs, and
  required-before-claim steps. The compliance audit now gates that diagnostic
  pipeline-plan decisions are evidence-specific and process-context backed
  (`pipeline_improvement_diagnostic_context_rows=4/4`) and that provenance
  pipeline-plan decisions are outlet-scope-evidence backed
  (`pipeline_improvement_provenance_context_rows=2/2`), so generic prompts
  cannot pass as pipeline improvement evidence. Residual all-terminal
  volume-deficit diagnostics now also carry candidate explanations for every
  retained post-aggregation process domain
  (`post_aggregation_candidate_explanation_rows=4/4`), including evidence,
  next action, fresh locked rerun requirement, and claim impact. Those
  explanations are now also preserved directly in the root
  `pipeline_improvement_plan` diagnostic `decision_request` payloads
  (`pipeline_improvement_diagnostic_explanation_rows=4/4`), so agents can
  select the next diagnostic experiment from the executable plan without
  losing the evidence basis. The root report also carries
  `science_blocker_summary` (`science_blocker_summary_ok=True`) for the four
  science blockers, separating genuine current skill/mass limitations from
  repairable pipeline-improvement domains.
  Diagnostics decisions now use retained post-aggregation process context to
  choose a first experiment:
  soil-provenance repair for `03349000`, PET/ET partition screening for
  `03353000` and `09504500`, and high observed-runoff forcing/area audit for
  `12031000`. The active `12031000` high-runoff context now also carries
  structured candidate explanations for precipitation/area/external inflow
  basis, snow storage, aquifer release, selected terminal scope, and model
  water-yield deficit, while the defensible
  research-grade target is still incomplete. The stale `12031000`
  research-grade row has been superseded by a fresh accepted canonical rerun
  (`demo_runs/workflow/fresh_12031000_20260517_core_sensitivity`) that carries
  current core sensitivity evidence but downgrades the basin to `exploratory`:
  physical gates fail (`PBIAS=-80.51%`), routing-flow closure is a warning,
  terminal scope remains `multi_terminal_volume_deficit`, and 38 fresh locked
  candidates did not pass the volume promotion gate. One basin is currently
  reported as `research_grade` in the objective report (`03351500` only).
  `02129000` is now downgraded by current terminal-scope policy despite strong
  locked metrics because its selected terminal carries only `0.757` of all
  terminal flow; `terminal_scope_claim` is blocked as
  `outlet_scope_volume_mismatch`. `03351500`
  (`NSE=0.313`, `KGE=0.521`, `PBIAS=-5.59%`) passes physical gates and
  routed-flow closure after full-mode routing stopped writing duplicate `tot`
  plus `sur`/`lat` routing-unit flows.
  `01491000` has also been freshly rerun through the canonical full-mode
  calibrated path in
  `demo_runs/workflow/fresh_01491000_20260518_process_gate`. It passes
  routed-flow closure with no `tot` rows, retains high-fidelity
  `gnatsgo_raster` soils, and carries a basin-specific locked sensitivity
  screen, but remains `exploratory`. Its mixed `MASS_IMBALANCE` plus
  volume/ET/skill blockers are allowed to enter diagnostic calibration;
  `MASS_IMBALANCE`-only still blocks. The diagnostic calibration evaluated 157
  fresh candidates; 126 passed the volume gate, 0 passed the candidate
  calibration process gate, and no final locked calibrated `TxtInOut` was
  promoted. Baseline metrics remain authoritative (`NSE=-0.096`,
  `KGE=0.105`, `PBIAS=-29.94%`) and temporary candidate metrics are not
  promoted (`final_metrics_authority=none`,
  `temporary_candidate_metrics_allowed_as_final=false`). Its refreshed
  ET/volume diagnostic sidecars now retain explicit soil context
  (`high_fidelity`, `gnatsgo_raster`, `pct_fallback_soils=0.0`) and recommend
  subsurface-control screening with retained soil provenance rather than
  deferring those controls as degraded-soil artifacts.
  Prepared-directory `01013500` evidence that looked diagnostic before
  objective-cache routing normalization is superseded as tainted. The fresh
  canonical rerun
  `demo_runs/wetland_massfix_01013500_2010_2019_lockroutingfix` has no `tot`
  routing-unit rows in the live TxtInOut, did not create a locked calibrated
  TxtInOut because no candidate passed the volume promotion gate, and remains
  `exploratory` (`NSE=-0.057`, `KGE=-0.025`, `PBIAS=-57.21%`) with
  `calibration_final_metrics_authority=none` and
  `temporary_candidate_metrics_allowed_as_final=false`. `09504500` has also
  been rerun through the canonical calibrated path after the gNATSGO
  duplicate-depth soil repair. It now retains high-fidelity
  `gnatsgo_raster` soils, basin-specific sensitivity, and 128 fresh
  calibration candidate evaluations, but remains `exploratory`: no candidate
  passed the final `kge_nse_finetune` promotion gate, all candidates retained
  failing physical gates, routing closure remains a `fail_mass_closure`
  warning, final metrics remain the baseline (`NSE=0.053`, `KGE=-0.140`,
  `PBIAS=-67.7%`), and candidate metrics are not promoted
  (`final_metrics_authority=none`,
  `temporary_candidate_metrics_allowed_as_final=false`). Its refreshed
  volume-bias diagnostics now also expose terminal-scope evidence:
  `selected_terminal_partial_of_all_terminal_flow` and
  `all_terminal_routed_to_channel_reference_matches`; this is diagnostic-only
  until selected-outlet scope is explained. The same diagnostics now compare
  selected-terminal and all-terminal hydrographs against observations and
  promote those comparisons into row-level `terminal_hydrograph_scope`
  evidence in `docs/objective_basin_validation_report.json`. The same rows
  carry package-emitted `terminal_scope_blocker` classifications, separating
  `outlet_scope_volume_mismatch` from `multi_terminal_volume_deficit` without
  promoting all-terminal metrics. Future canonical workflow evidence summaries
  write both fields into `values` and calibration provenance when relevant,
  and runtime claim governance blocks `terminal_scope_claim` until selected
  outlet scope is explained. Objective rows now also retain structured
  `allowed_claim_names` and `blocked_claim_names` for all 11 basins, so claim
  policy evidence is not only embedded in prose notes.
  `01013500`
  all-terminal volume closes diagnostically (`PBIAS=+0.1%`) while
  timing/shape still fails (`NSE=-0.316`); `03353000` and `09504500` improve
  under all-terminal aggregation but still miss the hard volume gate
  (`PBIAS=-51.7%` and `-36.2%`). Selected-terminal and all-terminal
  diagnostic hydrographs now also retain `kge_2009_components`; the objective
  audit gates `terminal_hydrograph_kge_component_rows=7/7` and
  `terminal_hydrograph_scope_class_rows=7/7`, keeping
  all-terminal aggregation diagnostic-only while showing whether the remaining
  limitation is correlation, variability, or bias. Selected-not-nearest terminal
  rows now also retain `terminal_outlet_conflict_class`; the current four such
  rows classify as `selected_largest_terminal_not_nearest_minor_branch_conflict`,
  which directs remediation to hydrofabric/gauge outlet-authority reconciliation
  instead of unexamined nearest-terminal promotion. Terminal inventory now also falls back to
  `delin/validation_result.json` for NLDI/reference area and persists
  selected/all-terminal area fractions, so the objective audit gates
  `terminal_area_context_rows=8/8`. `01013500` is the clearest source-backed example:
  selected terminal area is `0.480` of NLDI while all terminals are `0.983`.
  These comparisons refine blocker triage but do not promote claims without
  selected-outlet provenance, routing closure, and locked verification.
  Active `multi_terminal_volume_deficit` rows now also rank terminal inventory
  reconciliation and selected-vs-all hydrograph review before CN, ET, or
  subsurface parameter screens in the machine-readable volume diagnostic probe
  order. When valid all-terminal aggregation improves volume but still fails
  the hard volume gate, volume diagnostics now retain
  `all_terminal_hydrograph_volume_deficit_persists` and queue
  `diagnose_post_aggregation_water_balance_deficit`, keeping terminal evidence
  diagnostic-only while directing the next fresh-output work toward forcing,
  ET, runoff-generation, and subsurface process evidence. Volume diagnostics
  also write `reports/weather_forcing_summary.json` from retained SWAT+
  precipitation files and observed-flow context, and the objective report now
  promotes that forcing summary for active residual volume-deficit rows. The
  forcing summary includes precipitation over the observed-flow comparison
  window and `observed_runoff_to_overlap_precip_ratio`, avoiding warmup-period
  precipitation totals as the basis for residual volume diagnosis.
  Objective summaries now expose volume-bias diagnostic flags only for active
  final `VOLUME_BIAS` rows, so historical baseline diagnostics from calibration
  runs do not appear as blockers on research-grade rows whose final physical
  gates passed. Skill diagnostic flags follow the same final-gate rule: they
  remain visible for active `BELOW_RESEARCH_SKILL` or `NEGATIVE_SKILL`
  blockers, but historical skill sidecars are suppressed from rows whose final
  skill gates pass or whose active blocker is elsewhere. Routing diagnostic
  flags and terminal-inventory blockers likewise remain visible only for
  active failed/warning routing rows. Failed calibration rows now also expose
  compact history summaries in `docs/objective_basin_validation_report.json`:
  volume-gate pass count, physical-gate pass count, best failed phase,
  best failed candidate metrics by absolute PBIAS, and the best failed
  parameter vector with governed bound hits. This separates basins where
  volume search never found a gate-passing candidate (`01013500`, `03353000`)
  from basins where volume can be matched but final physical/skill promotion
  still fails (`01547700`, `01491000`, `01493500`, `09504500`). `01493500`
  has now been freshly rerun through the accepted canonical path after fixing
  a WhiteboxTools wrapper mode that returned success without writing the breach
  output raster. The fresh run passes routing-flow closure and verifies a
  locked calibrated rerun, improving from `NSE=-0.022`, `KGE=-0.332`,
  `PBIAS=-80.61%` to `NSE=0.006`, `KGE=0.154`, `PBIAS=-13.17%`; it remains
  exploratory because final skill is below research-grade thresholds. Its
  remaining baseflow/subsurface suggested controls `ALPHA_BF` and `RCHG_DP`
  are now explicitly classified as screened-dead by the basin-specific
  sensitivity evidence, while `CH_N2=weak` and `CH_K2=active` remain retained
  channel-routing evidence rather than unscreened gaps. Future locked
  calibration histories also write per-candidate physical-gate condition codes
  and dominant blockers, and the objective report backfills those counts from
  existing compact objective traces where available.
  Soil-realism build blockers are no longer reported as verified
  `high_fidelity` soil evidence: objective summaries normalize these rows to
  `soil_mode=not_verified` with
  `soil_provenance_mode=soil_realism_gate_failed`, and future workflow evidence
  records the same package-owned blocker context before claim gates are
  evaluated. These build-blocked rows now explicitly fail the `soil_fidelity`
  gate while retaining the more precise primary blocker
  `soil_realism_gate_failed`.
  All eight failed or blocked calibration searches now carry row-level failure
  phase, failure message, final-metric authority, temporary-candidate guard,
  calibration provenance evidence, candidate physical blocker counts, and
  process-vs-claim blocker counts. All eleven attempted, completed, or
  precheck-blocked calibrations now also expose row-level calibration precheck
  sequences and baseline physical/routing gate statuses, so diagnostic
  calibration before final gate repair is auditable.
  The fresh channel-aware `01654000` canonical rerun now closes the earlier
  channel-routing probe gap in real evidence: the locked basin-specific screen
  includes `CH_N2=weak` and `CH_K2=active`,
  `skill_probe_gap_parameters=[]`, and
  `skill_unscreened_suggested_parameters=[]`. The promoted locked rerun
  improved only marginally over baseline (`NSE=0.031 -> 0.032`,
  `KGE=0.069 -> 0.073`, `PBIAS=-12.40% -> -9.11%`) with final metrics
  authoritative from `verification_summary.json` and temporary candidate
  metrics disallowed. It remains exploratory because skill is below
  research-grade thresholds and routed-flow closure is still a warning: the
  selected terminal carries only `0.527` of all terminal flow, while
  all-terminal routed-to-channel closure is `1.006`
  (`generated_topology_mismatch`). Terminal-scope classification now comes
  from the package routing evidence layer, so the same row also exposes
  `terminal_scope_blocker=outlet_scope_volume_mismatch` even though its
  primary blocker remains `BELOW_RESEARCH_SKILL`; passed routing closure now
  still blocks terminal-scope claims when selected-terminal flow is materially
  partial relative to all generated terminal flow.
  The same process-gate split now has fresh volume-skill-aware `01547700`
  evidence:
  high-fidelity `gnatsgo_raster` soils, selected-terminal routing closure
  passed, the current governed parameter screen included `CH_N2` and `CH_K2`,
  and the promoted locked rerun improved strongly over baseline
  (`NSE=-0.012 -> 0.156`, `KGE=-0.173 -> 0.317`,
  `PBIAS=-63.95% -> -18.13%`). The volume-stage scorer now preserves KGE/NSE
  inside the preferred `|PBIAS| <= 15%` tier instead of chasing exact zero
  PBIAS. It remains exploratory because final skill is still below
  research-grade thresholds (`BELOW_RESEARCH_SKILL`), with final metrics
  authoritative from `verification_summary.json` and temporary candidate
  metrics disallowed.
  The skill diagnostic for this row now separates annual/event timing from
  peak-magnitude attenuation: `01547700` no longer reports a false
  `peak_lag_days=-688` single-maximum lag and instead reports attenuated
  high-flow peaks (`top_decile_sim_obs_flow_ratio=0.456`). `01654000` retains
  a local timing lag (`peak_lag_days=3`) and also reports attenuated peaks
  (`top_decile_sim_obs_flow_ratio=0.253`). Skill diagnostics now also carry
  locked-parameter bound context: `01547700` now has `SURLAG=24.0` at the
  governed upper bound and `LATQ_CO=0.001` at the governed lower bound, while
  `01654000` has `SURLAG=24.0` at its upper bound. These fields are now first-class row values in
  `docs/objective_basin_validation_report.json`, not only sidecar diagnostic
  details. The same report now also exposes active
  `skill_evidence_metrics`: `01547700` carries the high-flow attenuation ratio
  (`top_decile_sim_obs_flow_ratio=0.456`), and `01654000` carries both local
  annual peak-lag metrics (`median_lag_days=3`) and high-flow attenuation
  (`top_decile_sim_obs_flow_ratio=0.253`). Locked skill diagnostics now also
  retain KGE component decomposition: the fresh `01547700` row is now
  primarily correlation/timing-limited (`r=0.450`) after volume repair, while
  `01493500` and `01654000` are also primarily correlation/timing-limited
  (`r=0.288` and `r=0.261`).
  Channel-routing attenuation is now
  a governed parameter-support path: `CH_N2` writes
  `hyd-sed-lte.cha:mann`, `CH_K2` writes `hyd-sed-lte.cha:k`, and both active
  skill-blocked rows now expose channel-routing evidence in the calibration
  sensitivity context. The fresh `01547700` and `01654000` reruns both close
  their channel probe gaps (`skill_probe_gap_parameters=[]`) and retain
  basin-specific channel screen evidence; `01547700` has `CH_N2=weak`,
  `CH_K2=active`, and `01654000` has `CH_N2=weak`, `CH_K2=active`.
  Both rows remain exploratory; these diagnostics redirect the next work toward
  precipitation forcing, outlet/output-scope review, and structural routing
  evidence instead of repeating exhausted parameter probes.
  The objective report now enforces that distinction directly:
  `skill_bound_aware_probe_rows=3/3`, with `01547700` and `01654000` ranking
  `screen_channel_routing_attenuation_controls` ahead of fully bound-exhausted
  SURLAG/CN2 probes while keeping the exhausted controls visible in
  `bound_exhausted_parameters`.
  The package-owned runtime sensitivity gate now also requires basin-specific
  coverage of every current non-dead governed core parameter and blocked/dead
  accounting for unsupported core controls. Objective audit evidence is
  `research_grade_core_sensitivity_rows=2/2` after the fresh `12031000`
  rerun superseded the stale narrow-screen research-grade row.
  Future reruns will encode this exact distinction as
  `calibration_status=verified_diagnostic_claim_blocked` rather than treating
  the locked verification as a failed or promoted research claim.
  Objective reports also now carry a future-proof near-miss classification for
  failed calibration histories where temporary candidates meet skill thresholds
  but miss the hard volume gate; current canonical evidence has no qualifying
  row, while controlled high-fidelity `03353000` probes reached
  `NSE=0.477`, `KGE=0.424`, `PBIAS=-34.50%` without crossing the required
  `|PBIAS| <= 30%` gate. The same probe closed a parameter-support gap:
  `CN3_SWF` is now a governed extended full-mode volume control targeting
  `hydrology.hyd:cn3_swf`, based on the SWAT+ soft-calibration documentation.
  It is eligible for basin-specific locked screening but remains diagnostic
  until the promoted locked rerun passes all claim gates. A fresh canonical
  `03353000` rerun now exercises that support: `CN3_SWF` screened `active`,
  38 fresh locked candidates ran, no candidate passed the `abs(PBIAS) <= 30`
  volume gate, and the best candidate remained `CN2=98` with `NSE=0.442`,
  `KGE=0.346`, `PBIAS=-35.69%`. The basin remains exploratory with a
  persistent water-yield/routing/ET blocker, not a missing-parameter-support
  blocker. JSON workflow mode also now redirects process-owned stdout/stderr
  file descriptors to run-local shutdown logs after emitting the final payload,
  closing the long-run post-payload shutdown-noise defect observed in that run.
  The soil-fidelity claim gate now requires explicit authoritative provenance:
  `soil_mode=high_fidelity`, `soil_provenance_mode=gnatsgo_raster`, and numeric
  `pct_fallback_soils=0.0`. Missing soil provenance no longer passes by
  default. The workflow and objective summarizer normalize package-owned
  `metadata.json` fields and metadata notes into first-class evidence before
  gate evaluation, so older high-fidelity rows such as `12031000` and
  `01493500` expose `gnatsgo_raster` provenance directly while genuinely
  degraded or missing provenance still fails `soil_fidelity`.
  Calibration documentation has been reconciled with current implementation:
  standalone `swat locked-calibrate` still defaults to the historical
  `CN2,ALPHA_BF` scope, while the governed end-to-end workflow screens
  calibration-eligible full-mode parameters and passes retained controls into
  staged diagnostic phases before independent verification. Historical
  two-parameter evidence remains a baseline only, not the current full-mode
  claim.
  The objective compliance audit has also been refreshed against the moved
  workspace: it now accepts current objective-row `build_diagnostic_artifacts`
  when the older single overlay-repair side artifact is absent, while still
  requiring real artifact paths. The regenerated audit reports `complete`
  (`17/17` checks).
  A summarize-only Phase E refresh of the objective report was run from
  existing evidence with explicit fresher overrides for `01547700`, `01493500`,
  `03351500`, and `02129000`. It did not launch new basin workflows. Current
  objective status remains honest: `research_grade_count=0/11`; blocker domains
  are now `science=6`, `provenance=3`, `diagnostics=2`, showing that the
  repaired-volume evidence shifted the failure explanation rather than
  manufacturing a pass.
- The `03349000` subsurface audit found and repaired a missing groundwater
  recharge connection: routing units now send `rhg` to shallow aquifers and
  shallow aquifers route deep recharge onward. A fresh full-period run changed
  aquifer recharge/flow from zero to `37.109/10.838 mm/yr` and improved
  simulated BFI from `0.210` to `0.242`, but retained negative NSE and
  `PBIAS=-56.24%`. This is an adopted plumbing correction, not model promotion.
- The same basin exposed a full-overlay area-conservation defect: thresholded
  HRUs represented `191,588.842 ha` while their LSUs represented
  `208,791.925 ha`. Filtered HRU area is now redistributed proportionally
  within each LSU, cataloged explicitly, and enforced by a post-Editor
  fraction-sum validator. A fresh full-period run improved volume/KGE evidence
  but retained negative NSE; this is an adopted mass correction, not model
  promotion.
- The remaining `5.67%` delineation gap was caused by requesting 3DEP only
  inside the reference polygon, creating artificial D8 exits. DEM acquisition
  now uses a 5 km buffered bounding box while retaining the NLDI polygon for
  independent validation, and full workflows refuse domain-edge contact. A
  controlled `03349000` geometry rerun improved area difference to `-1.30%`
  and IoU to `95.13%` with zero edge contacts; multi-basin rebuilds remain
  pending.
- Next step: rebuild `03349000` end to end through both corrected geometry and
  HRU-area paths, then run a contrasting gauge before using
  the refreshed objective report to target the remaining
  engineering/science blockers: aquifer release/revap sensitivity after the
  recharge repair, remaining physical volume/ET failures,
  low final skill after successful locked promotion, routed-flow warnings, and
  degraded-soil recovery for fallback basins. Do not report additional
  research-grade claims until build, provenance, fresh-output, physical-gate,
  sensitivity, locked-calibration, soil-fidelity, routed-flow, hydrograph, and
  contract evidence all pass.

## Non-Goals

- Do not chase basin pass count by weakening gates.
- Do not report research-grade claims from metrics alone.
- Do not let ad hoc scripts define claim tiers, blockers, or final calibration
  evidence.
- Do not use stale SWAT+ outputs as evidence.
- Do not document planned behavior as implemented behavior.

## How To Run And Test

```bash
PYTHONPATH=src python -m swatplus_builder.cli workflow run --help
PYTHONPATH=src pytest -q tests/test_cli_workflow.py tests/test_workflow_usgs_e2e.py
PYTHONPATH=src pytest -q tests/test_parameter_bridge.py tests/test_parameter_registry.py tests/test_sensitivity_screen.py
```
