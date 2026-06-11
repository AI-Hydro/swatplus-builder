# Pipeline Research-Grade Audit

Date: 2026-05-12
Scope: Phase 0 audit of the current checkout against the agent-governed SWAT+
production-pipeline requirements.

## Executive Verdict

Status: not research-grade yet.

2026-05-13 recheck: the canonical objective-suite report now summarizes 11
per-basin evidence summaries, including fresher per-basin rerun evidence where
available. After the 2026-05-18 terminal-scope governance tightening, one
basin is currently reported as research-grade in the objective report
(`03351500`). `02129000` is downgraded to `exploratory` under current policy
because its selected terminal carries only `0.757` of all generated terminal
flow, so `terminal_scope_claim` is blocked as
`outlet_scope_volume_mismatch`. The older `12031000`
research-grade evidence is superseded by a fresh accepted canonical rerun with
current core sensitivity coverage; that rerun downgrades `12031000` to
`exploratory` because terminal-scope volume, routing-flow, physical-gate, and
calibration-promotion gates fail. The other basins remain
`exploratory` because physical gates, routed-flow mass closure, soil-fidelity
gates, or low skill block calibration and claim promotion. This is the correct
scientific posture: the pipeline records runtime evidence for routed-flow
closure, degraded soils, physical gates, and calibration verification instead
of allowing ad hoc scripts or stale outputs to decide claims.

2026-05-18 objective evidence distribution after the emitted-routing terminal
inventory refresh:
the refreshed compliance audit reports `research_grade_count=1`,
`calibration_rows=5`, `hydrograph_rows=5`,
`volume_diagnostic_rows=5/5`, `skill_diagnostic_rows=3/3`,
`skill_evidence_metrics_rows=3/3`,
`skill_kge_component_rows=3/3`,
`skill_limitation_class_rows=3/3`,
`terminal_hydrograph_scope_rows=7/7`,
`terminal_hydrograph_kge_component_rows=7/7`,
`terminal_hydrograph_aggregation_context_rows=7/7`,
`terminal_hydrograph_scope_class_rows=7/7`,
`terminal_scope_resolution_plan_rows=7/7`,
`terminal_outlet_conflict_class_rows=4/4`,
`blocker_domain_action_rows=10/10`,
`target_hypothesis_evaluation_ok=true`,
`pipeline_improvement_plan_ok=true` with active domains
`diagnostics` and `provenance` and
`pipeline_improvement_plan_basin_rows=6/6`,
`pipeline_improvement_decision_request_rows=6/6`,
`pipeline_improvement_diagnostic_context_rows=4/4`,
`pipeline_improvement_diagnostic_explanation_rows=4/4`,
`pipeline_improvement_provenance_context_rows=2/2`,
`science_blocker_summary_ok=true`,
`calibration_phase_coverage_rows=10/10`,
`soil_realism_diagnostic_rows=0/0`,
`soil_realism_remediation_rows=0/0`, `routing_diagnostic_rows=6/6`,
`routing_source_coverage_rows=6/6`, `soil_fidelity_provenance_rows=2/2`,
`claim_policy_name_rows=11/11`,
`routing_unit_semantics_rows=6/6`, `terminal_inventory_rows=8/8`,
`terminal_area_context_rows=8/8`,
`terminal_topology_overlap_rows=0/0`, `et_context_rows=4/4`, `et_diagnostic_rows=4/4`,
`mass_balance_diagnostic_rows=1/1`,
`terminal_scope_blocker_rows=7/7`,
`routing_terminal_scope_blocker_rows=5/5`,
`terminal_scope_claim_blocked_rows=8/8`,
`skill_channel_screen_rows=3/3`,
`skill_channel_refinement_rows=0/0`,
`calibration_bound_interaction_rows=1/1`,
`skill_parameter_governance_rows=0/0`,
`superseded_skill_parameter_rows=0/0`,
`skill_probe_gap_rows=3/3`,
`skill_sensitivity_triage_rows=1/1`,
`skill_bound_aware_probe_rows=3/3`,
`research_grade_core_sensitivity_rows=1/1`,
`promotion_gate_failure_rows=5/5`,
`failed_calibration_evidence_rows=8/8`,
`failed_calibration_context_rows=8/8`,
`failed_calibration_tradeoff_frontier_rows=8/8`,
`failed_calibration_terminal_scope_history_rows=0/0`,
`failed_calibration_physical_trace_rows=8/8`,
`failed_calibration_process_trace_rows=8/8`,
`calibration_precheck_rows=11/11`,
`terminal_scope_probe_priority_rows=7/7`,
`routed_to_channel_semantics_rows=0/0`,
`routing_status_mismatch_rows=0/0`,
`terminal_gauge_context_rows=8/8`,
`not_nearest_terminal_probe_rows=4/4`,
`nearest_terminal_hydrograph_rows=3/3`,
`post_aggregation_volume_deficit_rows=4/4`,
`post_aggregation_process_context_rows=4/4`,
`post_aggregation_candidate_explanation_rows=4/4`,
`volume_forcing_context_rows=5/5`,
`volume_forcing_plausibility_rows=5/5`,
`high_runoff_demand_context_rows=1/1`,
`high_runoff_interpretation_rows=1/1`,
`terminal_area_scope_class_rows=8/8`,
`terminal_authority_area_context_rows=8/8`,
`terminal_virtual_outlet_candidate_rows=8/8`,
`virtual_outlet_scope_gate_rows=0/0`,
`physical_gate_artifact_rows=11/11`, and routing statuses
`{passed: 5, failed: 0, warning: 6, not_run: 0, unknown: 0}`.
Primary blockers are `{multi_terminal_volume_deficit: 4,
outlet_scope_volume_mismatch: 2, MASS_IMBALANCE: 1,
BELOW_RESEARCH_SKILL: 3, none: 1}`. The
objective compliance audit is now
`96/97` implemented. The only missing check is the defensible research-grade
target. `12031000` now has current-core sensitivity evidence, but the fresh
canonical rerun remains `exploratory`: selected-terminal PBIAS is `-80.51%`,
all-terminal PBIAS is `-64.30%`, routing closure is `fail_mass_closure`, and
38 fresh locked candidates failed the volume promotion gate. The best failed
candidate reached `NSE=0.335`, `KGE=0.249`, and `PBIAS=-48.51%`, so this is
not a near-threshold research-grade miss. The next work
should follow the suite-level `pipeline_improvement_plan`: diagnostics for
the four `multi_terminal_volume_deficit` rows and provenance for the two
`outlet_scope_volume_mismatch` rows. The plan now includes per-basin next
experiments and artifact pointers, so agents can inspect the current evidence
before deciding whether to run a provenance repair, virtual-outlet experiment,
or process/forcing diagnostic. Provenance rows now emit typed `needs_input`
outlet-scope decisions with official authority-area, virtual all-terminal
candidate, conflict, terminal-ID, and required-before-claim evidence; those
decisions may recommend virtual all-terminal authorization only as a
user-or-policy decision, not as claim authority. Diagnostics rows remain typed
`diagnostic_only` plans until source-backed evidence identifies a repairable
package gap.
The production audit now also requires diagnostic-domain plan decisions to
retain process context (`likely_process_domains` and `recommended_focus`) and
choose a non-generic, evidence-specific first option, preventing generic
diagnostic prompts from satisfying the pipeline-improvement evidence check.
That terminal-scope decision shape is now owned by
`swatplus_builder.output.volume_diagnostics`; workflow evidence promotes
`terminal_scope_decision_request` from future diagnostic sidecars into
`evidence_summary.json` values and calibration provenance, while the objective
script only aggregates package-owned guidance into the suite plan. The current
diagnostics rows are now evidence-specific rather than generic:
`03349000` is pointed first at soil-provenance repair before parameter
attribution, `03353000` and `09504500` at PET/ET partition screening, and
`12031000` at high observed-runoff forcing/area audit. These are next
experiments, not claim authority.
Science blockers remain honest
non-pipeline blockers unless new evidence exposes a repairable diagnostics,
calibration, provenance, engineering, or parameter-support gap.

2026-05-25 virtual-outlet follow-up: the canonical
`swat workflow run --virtual-all-terminal-outlet` path was exercised for
`02129000` with explicit policy authority. The sandboxed first attempt failed
closed with `external_data_provider_unreachable`; the network-authorized rerun
exposed and then, after patching, cleared an observed-series relock bug. The
fresh `_v2` run completed with `outlet_scope=virtual_all_terminal`,
`virtual_outlet_scope_gate=passed`, fresh engine output, high-fidelity gNATSGO
soils, basin-specific sensitivity, locked calibration verification, and final
all-terminal metrics `NSE=0.443`, `KGE=0.637`, `PBIAS=+6.31%`. The same run
also exposed a governance conflict where selected-terminal volume diagnostics
could reapply `outlet_scope_volume_mismatch` after the virtual scope gate
passed. Runtime claim governance now treats the passed virtual scope gate as
claim-authoritative, while retaining selected-terminal hydrographs as
diagnostic contrast evidence only. Recomputing claim governance from the fresh
artifacts with the patched package returns `research_grade`; the objective
suite has not yet been regenerated to count this follow-up basin.

The terminal hydrograph diagnostic rows now retain package-owned scope
classes. Current classes are:
`02129000=selected_metric_passes_but_area_scope_partial`,
`01013500` and `01493500=all_terminal_volume_corrected_but_skill_limited`,
and `03349000`, `03353000`, `09504500`, and
`12031000=all_terminal_volume_deficit_persists_after_valid_aggregation`.
These classes are diagnostic-only; they distinguish outlet-scope evidence,
remaining timing/shape skill limits, and persistent post-aggregation
water-balance deficits without allowing all-terminal metrics to become final
claim evidence. Future canonical workflow evidence summaries and calibration
provenance now promote the same class, flags, recommended focus, and claim
impact into the main evidence bundle when volume diagnostics produce them.

All-terminal hydrograph diagnostics now retain aggregation-validity context
from `terminal_trace.json`. Terminal inventories now compute upstream terminal
footprints from the emitted `chandeg.con` SWAT+ routing table keyed by GIS ID,
not from raw delineation-graph branch candidates that were never written to
`gis_routing`. After refreshing retained terminal traces and volume
diagnostics, the prior overlap rows have `shared_upstream_area_km2=0.0` and
valid all-terminal aggregation context. `03349000`, `03353000`, `09504500`,
and `12031000` are therefore classified as `multi_terminal_volume_deficit`,
while `01013500` is classified as `outlet_scope_volume_mismatch` because
all-terminal aggregation nearly closes the volume gate. Real emitted split
routing still records pairwise overlap diagnostics, and future routing-flow
gate payloads promote that compact overlap summary into `routing_flow_gates.json`
so runtime claim governance can classify `terminal_topology_overlap` before
using outlet-scope or multi-terminal volume-deficit fallbacks when the actual
SWAT+ routing table contains overlap.

The skill diagnostics now separate suggested controls into usable,
screened-dead, and unscreened groups. `01493500` is the current clearest
example: `ALPHA_BF` and `RCHG_DP` are not merely missing from a screen; both
were basin-screened as `dead`, so repeat groundwater-control searches are not
scientifically justified without new process evidence. Its channel controls
remain retained evidence (`CH_N2=weak`, `CH_K2=active`), and the same
channel-screen distinction prevents `01547700` and `01654000` from being
misreported as having unscreened channel controls.

The baseflow/low-flow diagnostic rules now follow the same full-mode
governance. The flashy low-baseflow rule no longer recommends legacy
`GW_DELAY` or `GWQMN` edits; it recommends governed subsurface and recession
controls (`PERCO`, `LATQ_CO`, `LAT_TTIME`, `ALPHA_BF`, `RCHG_DP`) that must be
basin-screened and locked before any claim use. This keeps diagnostic advice
aligned with the bridge, registry, sensitivity screen, and parameter docs
instead of reintroducing unsupported groundwater edits through a side report.
The retained `01493500` low-skill sidecar was refreshed from its locked
calibrated alignment, so the objective report no longer presents `GW_DELAY` or
`GWQMN` as suggested baseflow calibration controls; `GW_DELAY` remains visible
only as a dead governed core parameter where the sensitivity context lists the
full core set.

The high observed runoff-fraction volume diagnostic now follows the same rule.
`audit_high_observed_runoff_fraction_context` no longer lists `GW_DELAY` as a
parameter to probe. It keeps governed snow and subsurface/recession controls
(`SFTMP`, `SMTMP`, `PERCO`, `LATQ_CO`, `LAT_TTIME`, `ALPHA_BF`, `RCHG_DP`) so
the retained `12031000` evidence can separate snow/storage, water-yield,
aquifer-release, and terminal-scope causes without reviving unsupported legacy
groundwater-delay edits. The refreshed `12031000` sidecar now also retains
candidate explanations showing that gauge area matches all-terminal area while
runoff fraction remains high, SWAT snow terms and aquifer release do not
explain the demand, selected-terminal scope is partial, and SWAT water yield is
far below observed runoff fraction. These explanations are diagnostic-only
until a source-backed repair is selected and rerun through locked gates.

Future locked diagnostic calibration runs now also include screened `SFTMP`
and `SMTMP` controls in the `peaks_timing` phase with `SURLAG`, `CH_N2`, and
`CH_K2`. This keeps the automated protocol aligned with the retained
`snow_timing_and_peak_response` class: snow/rain partition and snowmelt
thresholds are tested as timing controls before final KGE/NSE finetuning, but
they remain diagnostic-only unless fresh locked candidates pass physical,
routing, calibration, sensitivity, and claim-governance gates.

Future calibration histories also retain diagnostic-only terminal-scope
candidate metrics. For multi-terminal runs, `history.csv` now records
selected-terminal and all-terminal NSE/KGE/PBIAS, selected-terminal fraction of
all terminal flow, and whether the all-terminal volume gate passes
diagnostically. The objective report surfaces those values inside the
diagnostic skill/volume tradeoff frontier when future histories contain them,
and the audit gates that report behavior (`0/0` for current retained histories,
which predate these columns). These columns do not affect scoring or final
evidence authority; they make failed searches auditable when a basin's active
blocker is selected-outlet scope or persistent all-terminal volume deficit.

Locked skill diagnostics now also decompose KGE into correlation, variability,
and bias components for active low-skill rows. This turns the three active
skill blockers into measured calibration targets: after the 2026-05-18
volume-skill scoring refresh, `01547700` is primarily correlation/timing
limited (`r=0.450`) rather than volume or variability limited, while
`01493500` and `01654000` are also primarily correlation/timing-limited
(`r=0.288` and `r=0.261`). The objective audit now requires this
`kge_2009_components` evidence for active skill blockers.

Active low-skill rows now also carry a package-owned skill-limitation class.
`01547700` and `01654000` are classified as
`correlation_timing_peak_attenuation`, while `01493500` is classified as
`snow_timing_and_peak_response`. The classes retain the dominant KGE component,
diagnostic flags, recommended focus, and claim impact in the machine-readable
objective report, so claim governance no longer depends on prose
interpretation of low-skill blockers.

Failed or blocked calibration histories now retain diagnostic-only
skill/volume tradeoff frontiers. For each failed-search row, the objective
report records separate `best_abs_pbias`, `best_kge`, and `best_nse`
candidates with metrics, phase, gate flags, condition codes, and parameters.
This exposes cases such as `01547700`, where the best KGE candidate still
fails NSE while the best volume candidate has much weaker skill, without ever
using a temporary candidate as final evidence.

Legacy calibration histories that predate explicit
`calibration_process_gate_passed` columns now infer process-vs-claim gate
counts from retained candidate physical condition codes by excluding
skill-only failures (`NEGATIVE_SKILL`, `BELOW_RESEARCH_SKILL`). This makes all
eight failed or blocked calibration searches auditable at the process-gate
level. The fresh `01491000` canonical rerun had 126
volume-gate-passing candidates but zero candidate-process-gate-passing
candidates; its blockers are `ET_DOMINATED`, `MASS_IMBALANCE`, and
`VOLUME_BIAS`, so it is not a near-threshold PBIAS tuning problem.

The ET-partition and volume-bias diagnostic sidecars now carry explicit
`soil_context` (`soil_mode`, `soil_provenance_mode`, `pct_fallback_soils`,
`soil_degraded`) and use it when ranking subsurface repair actions. Retained
high-fidelity rows such as `01491000`, `03353000`, and `09504500` now
recommend screening supported subsurface controls with retained soil
provenance instead of using degraded-soil deferral language. Fallback or
unverified rows still block subsurface calibration claims until soil
provenance is defensible. This keeps diagnostic actions aligned with the
soil-fidelity gate without weakening any research-grade claim policy.

Locked skill diagnostics now also use bound-hit context when ranking
recommended probes. `01547700` now has `SURLAG=24.0` at the governed upper
bound and `LATQ_CO=0.001` at the governed lower bound, while `01654000` has
`SURLAG=24.0`; both rows rank screened channel-routing attenuation (`CH_N2`,
`CH_K2`) ahead of fully bound-exhausted SURLAG probes. The exhausted controls
remain visible in `bound_exhausted_parameters` with diagnostic claim impact,
so this redirects experiments without hiding parameter saturation or promoting
a claim.

2026-05-17 `03353000` bound-interaction diagnostic: a fresh locked-objective
candidate screen tested whether `CN2=98.0` at the governed upper bound could
be rescued by governed ET/subsurface bounds. The best combination was
`CN2=98.0`, `PET_CO=0.8`, `ESCO=0.01`, with `NSE=0.443653`,
`KGE=0.349641`, and `PBIAS=-35.16%`; it remains outside the hard
`|PBIAS| <= 30%` gate and is retained as diagnostic-only evidence under
`calibration_bound_interaction_*` fields. This classifies the current
`03353000` blocker as persistent water-yield/forcing/outlet-scope or process
structure, not a simple missing CN2/PET/ESCO bound interaction.

2026-05-17 `01493500` fresh canonical rerun: the first
`swat workflow run --model-family full --calibrate --claim-tier research_grade`
attempt was correctly blocked by contract policy with no accepted contract
metadata. The accepted rerun then exposed a recoverable build blocker:
WhiteboxTools returned success for `BreachDepressionsLeastCost` without
writing the output raster when the Python wrapper was run with
`verbose=False`. The package now forces Whitebox execution verbosity and waits
briefly for expected outputs on cloud-backed filesystems before declaring a
missing-raster blocker.

After that fix, `01493500` completed the canonical accepted path end to end:
build, fresh engine run, lock, basin-specific sensitivity, fresh locked
calibration candidates, locked calibrated `TxtInOut` promotion, clean rerun,
gates, and evidence bundle. Final metrics are authoritative from
`verification_summary.json` and improved from baseline
(`NSE=-0.022`, `KGE=-0.332`, `PBIAS=-80.61%`) to
`NSE=0.006`, `KGE=0.154`, `PBIAS=-13.17%`. Routing-flow closure now passes,
volume bias is repaired, and temporary candidate metrics remain disallowed.
The basin remains `exploratory` because final physical gates block only on
`BELOW_RESEARCH_SKILL`; the earlier diagnostic bound-interaction sidecar is
superseded by this canonical locked calibration evidence. Because the
canonical basin-specific sensitivity screen already includes `CH_N2` and
`CH_K2`, the objective report now accepts that artifact as channel-routing
skill-screen evidence instead of requiring a duplicate channel-only sidecar.

2026-05-17 calibration-history auditability: failed or blocked calibration
rows now retain the best failed candidate's parameter vector in
`calibration_failure_best_parameters`, plus registry-backed
`calibration_failure_best_parameter_bound_hits` and
`calibration_failure_best_parameter_bound_context`, sourced directly from
`calibration_reports_locked/history.csv`. This keeps non-promotable candidates
traceable without treating their metrics as final evidence and shows whether a
governed control was exhausted. Current examples include `03353000` with
`CN2=98.0` at the governed upper bound (`NSE=0.442`, `KGE=0.346`,
`PBIAS=-35.69%`), `01013500` with `PET_CO=0.8` at the lower bound, and
`01493500` with `PERCO=0.01` at the lower bound; all remain exploratory because
the locked promotion gates still fail.

2026-05-18 channel-aware canonical rerun: `01654000` now has fresh accepted
workflow evidence with current channel controls inside the canonical locked
sensitivity and diagnostic calibration path. The locked basin-specific screen
classifies `CH_N2=weak` and `CH_K2=active`, with
`skill_probe_gap_parameters=[]` and
`skill_unscreened_suggested_parameters=[]`, so the earlier channel-routing
probe gap is closed. The promoted locked rerun improved only marginally from
baseline (`NSE=0.031`, `KGE=0.069`, `PBIAS=-12.40%`) to final
`NSE=0.032`, `KGE=0.073`, `PBIAS=-9.11%`; final metrics are authoritative
from `verification_summary.json`, and temporary candidate metrics remain
disallowed. The basin stays `exploratory` because skill is below the
research-grade gate and routed-flow closure remains a warning: the selected
terminal carries `0.527` of all terminal flow, all-terminal routed-to-channel
closure is `1.006`, and the terminal inventory class is
`generated_topology_mismatch`. Terminal-scope blocker classification now comes
from the package routing evidence layer rather than only from volume-bias
diagnostics, so this row also carries
`terminal_scope_blocker=outlet_scope_volume_mismatch` while retaining
`BELOW_RESEARCH_SKILL` as the primary blocker. Passed routing rows are not
assigned terminal-scope blockers.

2026-05-17 soil-fidelity hardening: runtime claim governance now requires
explicit authoritative soil evidence instead of treating missing values as
implicitly high-fidelity. A research-grade soil-fidelity pass requires
`soil_mode=high_fidelity`, `soil_provenance_mode=gnatsgo_raster`, and numeric
`pct_fallback_soils=0.0`. Missing provenance, degraded provenance, or positive
fallback fraction fails `soil_fidelity` and downgrades the effective claim
tier. The workflow and objective summarizer also promote package-owned
`metadata.json` fields and metadata notes into first-class evidence before
gate evaluation. Regenerated objective rows now expose `gnatsgo_raster`
provenance for `01493500` and `12031000`. The later fresh `12031000`
canonical rerun supersedes the older research-grade row and downgrades it to
`exploratory`; `01493500` remains exploratory behind physical,
calibration-verification, and routing-flow gates. The latest objective audit
status is `not_complete`, `96/97`, with `research_grade_count=1` after the
later terminal-scope, terminal area-scope, terminal hydrograph scope-class,
terminal outlet conflict-class,
machine-readable blocker domain/action-plan,
target-hypothesis evaluation,
root science-blocker summary,
suite-level pipeline-improvement planning,
process-context-backed diagnostic decision auditing,
diagnostic decision candidate-explanation preservation,
outlet-scope-evidence-backed provenance decision auditing,
calibration phase coverage,
terminal-scope resolution-plan,
KGE/NSE phase-entry process-gate hardening,
official USGS drainage-area authority checks,
diagnostic-only virtual all-terminal outlet candidates,
virtual all-terminal scope-gate report preservation,
post-aggregation process-context evidence,
post-aggregation candidate-explanation evidence,
mass-balance diagnostic, physical-gate artifact consistency,
skill-limitation class, terminal-scope candidate-history, and calibration
phase coverage hardening.

The fresh `01654000` channel-aware canonical rerun converted the current
governed channel controls into objective-suite evidence without promoting the
basin: `CH_N2` and `CH_K2` are screened in the locked basin-specific artifact,
110 candidates passed both volume and process gates, 0 passed the full
claim-oriented physical gate, and locked verification improved only marginally
to `NSE=0.032`, `KGE=0.073`, `PBIAS=-9.11%`. This keeps the basin
`exploratory` and documents the next blocker as structural skill plus
multi-terminal routing closure, not stale calibration auditability or missing
channel-control screening.

The fresh 2026-05-16 canonical process-gate rerun for `01547700` converted the
old stale-routing row into locked calibration evidence. The basin has
high-fidelity `gnatsgo_raster` soils, selected-terminal routing closure passes,
and 72 candidates passed both the volume and calibration process gates while 0
passed the full claim-oriented physical gate. The best process-valid parameters
were promoted to `locked_calibrated_TxtInOut` and independently rerun:
`NSE=0.271`, `KGE=0.252`, `PBIAS=12.65%`, with `delta_nse=+0.284` and
`delta_kge=+0.425` relative to the locked baseline. The run remains
`exploratory` because final physical gates still fail `BELOW_RESEARCH_SKILL`;
metrics are authoritative from `verification_summary.json`, and temporary
candidate metrics remain disallowed as final evidence.

2026-05-17 skill-diagnostic update: the package no longer computes peak lag by
comparing the single largest observed peak date against the single largest
simulated peak date across the full decade. That global-maximum rule produced
`peak_lag_days=-688` for `01547700`, which was not an actionable hydrologic
timing diagnosis. Skill diagnostics now use annual observed peaks with a local
simulated peak window and separately report high-flow attenuation using the
simulated/observed top-decile flow ratio. The fresh `01547700` diagnostic now
reports local peak lag (`median_lag_days=4`) and attenuated peaks
(`top_decile_sim_obs_flow_ratio=0.448`), not the old false multi-year timing
lag; `01654000` reports both a local timing lag (`peak_lag_days=3`) and
attenuated peaks (`top_decile_sim_obs_flow_ratio=0.253`). The same diagnostics
now retain locked-parameter bound context: `01547700` has `SURLAG=24.0` at
the governed upper bound and `LATQ_CO=0.001` at the governed lower bound,
while `01654000` has `SURLAG=24.0` at its upper bound. These values are now promoted into
`docs/objective_basin_validation_report.json` as
`calibrated_skill_parameter_values`, `skill_parameter_bound_hits`,
`skill_parameter_bound_context`, and `skill_parameter_bound_claim_impact`, so
the 10-basin evidence bundle carries the exhausted-control classification
without requiring sidecar inspection. The same objective rows now expose
`skill_evidence_metrics`, preserving `01547700` local annual timing
(`median_lag_days=4`) plus high-flow attenuation
(`top_decile_sim_obs_flow_ratio=0.448`) and `01654000` local annual timing
(`median_lag_days=3`) plus high-flow attenuation
(`top_decile_sim_obs_flow_ratio=0.253`) as structured numeric evidence.
2026-05-17 follow-up: channel-routing attenuation is now governed as an
extended parameter-support path. `CH_N2` writes `hyd-sed-lte.cha:mann` and
`CH_K2` writes `hyd-sed-lte.cha:k`, backed by SWAT+ channel hydrology
documentation and the Manning flow/velocity equations. The latest fresh
`01547700` canonical rerun closes its earlier channel-routing probe gap:
the basin-specific locked screen retains `CH_N2=weak` and `CH_K2=active`,
the locked calibration protocol includes `SURLAG`, `CH_N2`, and `CH_K2` in
the `peaks_timing` phase, and row-level
`skill_probe_gap_parameters=[]`. The rerun still remains `exploratory`
because the independently verified locked metrics (`NSE=0.156`,
`KGE=0.317`, `PBIAS=-18.13%`) fail the final `BELOW_RESEARCH_SKILL` gate.
`01654000` now has the same current channel-control evidence in a fresh
canonical rerun: `CH_N2=weak`, `CH_K2=active`, and
`skill_probe_gap_parameters=[]`. It remains exploratory because the locked
rerun improved only marginally and routed-flow closure remains a
selected-vs-all-terminal warning, not because channel controls are unscreened.
The current objective audit remains `not_complete`, `96/97`, with
`research_grade_count=1` after the later terminal-scope, terminal area-scope,
mass-balance diagnostic, physical-gate artifact consistency, and
skill-limitation class, terminal hydrograph scope-class, terminal outlet
conflict-class, machine-readable blocker domain/action-plan,
target-hypothesis evaluation, suite-level pipeline-improvement planning,
root science-blocker summary,
outlet-scope-evidence-backed provenance decision auditing,
process-context-backed diagnostic decision auditing,
diagnostic decision candidate-explanation preservation,
post-aggregation candidate-explanation evidence,
terminal-scope candidate-history,
calibration phase coverage, terminal-scope resolution-plan, KGE/NSE
phase-entry process-gate hardening, official USGS drainage-area authority
checks, diagnostic-only virtual all-terminal outlet candidates, and virtual
all-terminal scope-gate report preservation.
Residual all-terminal volume-deficit rows also retain
`post_aggregation_process_context`, keeping these metrics diagnostic-only while
separating likely soil, forcing, water-yield, ET, subsurface, and runoff
partition causes before any future locked rerun. Future canonical workflow
runs promote the same object into `evidence_summary.json` values and
calibration provenance whenever the volume-diagnostic sidecar emits it.

The workflow now preserves that distinction explicitly for future evidence.
Calibration provenance promotes `calibration_locked_verification_succeeded`,
`calibration_locked_rerun_improved`,
`calibration_final_claim_gates_passed`, and `calibration_claim_status` into
the top-level evidence values. A run with an improved locked rerun but failed
final claim gates is classified as
`calibration_status=verified_diagnostic_claim_blocked`: it can satisfy the
locked diagnostic verification gate, but it still blocks calibrated model skill
claims and cannot grant `research_grade`.

A clean 2026-05-16 no-calibration probe for `02129000` also shows the current
gNATSGO mosaic path can clear the retained soil-realism blocker for that basin:
`soil_provenance_mode=gnatsgo_raster`, `pct_fallback_soils=0.0`, 1606 unique
gNATSGO mukeys, and 45/45 profiles written. This is not final objective-suite
evidence because sensitivity and calibration were intentionally not run in the
probe. The basin remains `exploratory` with `PBIAS=-64.28%`, `NSE=-0.023`,
`KGE=-0.091`, `routing_flow_gates=warning`, and
`routing_flow_closure_status=fail_mass_closure`; the next canonical step is a
fresh sensitivity/calibration run, not claim promotion.

The follow-up canonical calibrated run for `02129000` completed that sequence
and produced strong locked metrics: `KGE=0.468`, `NSE=0.250`,
`PBIAS=1.20%`, `delta_kge=+0.556`, `delta_nse=+0.269`, and final physical and
routing-flow gates passed on the locked calibrated `TxtInOut`. The final
metric authority is `verification_summary.json`, with
`temporary_candidate_metrics_allowed_as_final=false`. Under the current
terminal-scope policy, however, those metrics do not promote a research-grade
claim because the selected terminal carries only `0.757` of all generated
terminal flow; `terminal_scope_claim` is blocked as
`outlet_scope_volume_mismatch`.
The retained terminal-scope diagnostic now uses the locked calibrated channel
output and locked alignment, so the same row records the selected-terminal
hydrograph (`KGE=0.468`, `PBIAS=1.20%`), the all-terminal diagnostic
hydrograph (`KGE=0.527`, `PBIAS=33.29%`), and the nearest-terminal diagnostic
hydrograph (`PBIAS=-83.24%`) without promoting any non-authoritative terminal
series into final claim evidence.

2026-05-16 `03353000` controlled probes: the canonical high-fidelity locked
history does not contain a research-grade candidate because the volume phase
stops before any candidate reaches `|PBIAS| <= 30%`; its best current history
row is `CN2=98`, `NSE=0.439`, `KGE=0.342`, `PBIAS=-35.72%`. Additional
manual probes against the same locked benchmark tested source-backed
surface-runoff, ET, lag, and soil-storage controls without changing gates.
They reached research-level skill but still missed volume, with the best case
at `NSE=0.477`, `KGE=0.424`, `PBIAS=-34.50%`. This is diagnostic-only
evidence and does not alter the objective report's claim tier. The report
schema now has explicit near-miss fields for future canonical histories that
contain such candidates, so the blocker can be classified without allowing
temporary-candidate metrics as final evidence.

The same probe exposed a parameter-support gap rather than a reason to weaken
the volume gate: SWAT+ documents `cn3_swf` as the soft-calibration variable for
surface runoff and as a `hydrology.hyd` CN3 soil-water adjustment factor, but
the full-mode bridge had not exposed it. `CN3_SWF` is now a governed extended
process control targeting `hydrology.hyd:cn3_swf`, included in the canonical
volume stage after basin-specific locked screening. It remains diagnostic-only
until locked verification and all physical, routing, metric, provenance,
outlet, sensitivity, and contract gates pass. Source references are recorded in
`docs/CALIBRATION_PARAMETER_REGISTRY.md`.

The fresh canonical `03353000` rerun after adding `CN3_SWF` confirms this is no
longer a missing-parameter-support blocker. The basin-specific locked
sensitivity screen retained `CN3_SWF` as `active`, and staged calibration ran
38 fresh candidates with the governed volume-stage parameter set. No candidate
passed `abs(PBIAS) <= 30`; the best candidate was still `CN2=98` with
`NSE=0.442`, `KGE=0.346`, and `PBIAS=-35.69%`. The objective report now points
at this fresh evidence and keeps `03353000` `exploratory` behind
`simulated_volume_deficit`, ET partition flags, and routed-flow mass-closure
warnings.

The fresh 2026-05-16 `09504500` no-calibration rerun resolved the remaining
soil-realism build blocker as an engineering defect, not a defensible
provenance failure. The root cause was a shallow aggregate profile with
duplicate layer bottom depths (`gnatsgo_658396`, `dp=300.0` twice), which
correctly failed the soil writer's strict monotonicity gate and forced
synthetic fallback in diagnostic mode. The soil builders now normalize
zero-thickness duplicate-depth layers before write and generate strictly
increasing aggregate layer breaks. The no-calibration probe is superseded by
the calibrated canonical evidence, but it established that the soil recovery
path can write `soil_mode=high_fidelity`, `soil_provenance_mode=gnatsgo_raster`,
and `pct_fallback_soils=0.0` for the basin.

The follow-up 2026-05-16 calibrated canonical `09504500` run kept the
high-fidelity gNATSGO soil evidence and ran basin-specific sensitivity plus
128 fresh real-engine calibration candidates. It remains correctly
`exploratory`: final baseline metrics are `KGE=-0.140`, `NSE=0.053`, and
`PBIAS=-67.7%`; final physical gates fail; routing-flow closure is a
research-grade-blocking warning (`fail_mass_closure`); and no candidate passed
the final `kge_nse_finetune` promotion gate. The best candidate KGE in
`history.csv` was only about `0.272`, all candidates retained
`physical_gate_passed=false`, and the final evidence keeps
`calibration_final_metrics_authority=none` with
`temporary_candidate_metrics_allowed_as_final=false`. This is a documented
science/routing blocker, not a promoted calibration.

2026-05-14 provenance update: objective-suite rows now retain first-class soil
provenance (`soil_mode`, `soil_provenance_mode`, `pct_fallback_soils`,
`soil_overlay_gap_fraction`) and routing mass-trace source coverage
(`basin_wb` source/row/year coverage and channel source/row/year coverage).
Soil-fidelity blockers now also retain an explicit `reports/soil_report.json`
artifact so degraded successful soil acquisition is auditable outside the
project database metadata. Those reports carry a source-priority manifest:
USDA gNATSGO raster plus SDA horizons is the only research-grade-eligible soil
source in the current chain; explicit `gnatsgo_raster` provenance with
`soil_mode=high_fidelity` and zero fallback soils now passes the soil-fidelity
gate, as confirmed by the prepared-directory `01493500` rerun. SDA
representative mukey, SoilGrids v2.0 coarse
profiles, and synthetic soils are degraded diagnostic fallbacks. Soil-realism
blocker rows now also retain source-backed recovery alternatives and probe
order: retry gNATSGO raster plus SDA horizons first, use SDA representative
mukey only as degraded spatial fallback, use SoilGrids v2 coarse profiles only
as diagnostic/degraded gap fill, and reserve synthetic or constant soils for
engine diagnostics that block soil-fidelity claims.
Prepared-directory reruns now reload package-owned `metadata.json` before
evidence classification, so rerunning an existing `TxtInOut` cannot silently
promote degraded soils to high-fidelity. The refreshed `03353000` prepared
rerun correctly retains `soil_mode=fallback`,
`soil_provenance_mode=diagnostic_partial_gnatsgo_constant`, and
`pct_fallback_soils=1.0`; despite improved final metrics, it remains
`exploratory` behind soil-fidelity, physical, routing-flow, and calibration
verification blockers.
ET-dominated rows also retain `reports/et_partition_diagnostics.json` with
ratio flags, governed next actions, source-backed alternatives, a recommended
fresh-output probe order, the gate context (`baseline` or `final_locked`), and
the physical-gate artifact path used to derive the ratios. The compliance
audit requires the objective-row gate context to match the diagnostic artifact
context. The alternatives prioritize PET
method/forcing review (`PET_CO`), soil evaporation compensation (`ESCO`),
plant uptake/management checks (`EPCO`), and deferred subsurface partition
controls (`LATQ_CO`, `PERCO`) where soil provenance is acceptable. For degraded
soil rows, the same artifact explicitly keeps ET sensitivity diagnostic-only
until the soil-fidelity gate is repaired.
Volume-bias rows now retain `reports/volume_bias_diagnostics.json` with
diagnostic flags, governed next actions, source-backed alternatives, and a
recommended fresh-output probe order. The alternatives prioritize curve-number
and landuse/soil mapping review (`CN2`), developed-land and urban curve-number
assumptions, PET/ET partition controls (`PET_CO`, `ESCO`, `EPCO`),
subsurface partition controls after soil provenance is defensible (`LATQ_CO`,
`PERCO`, `ALPHA_BF`, `RCHG_DP`), and outlet-selection review before any volume
repair is treated as research-grade evidence.
Rows with active `MASS_IMBALANCE` now also retain
`reports/mass_balance_diagnostics.json`, `mass_closure_residual_high`, the
residual basis, and a source-backed
`audit_basin_water_balance_closure_terms` alternative covering
`physical_gates.json`, `basin_wb_aa.txt`, `basin_wb_yr.txt`, ET context,
wetland terms, and subsurface partition before any research-grade
mass-closure claim is accepted.
Volume-bias diagnostics now also ingest routing-flow and mass-trace scope
fields when present. For multi-terminal volume-deficit rows, the report can
distinguish a selected terminal that carries only part of all terminal flow
from all-terminal routed-to-channel agreement. This does not promote claims:
`selected_terminal_partial_of_all_terminal_flow` and
`all_terminal_routed_to_channel_reference_matches` explicitly route agents to
terminal inventory and selected-vs-all terminal hydrograph audits before any
parameter search or research-grade volume claim is accepted. The refreshed
`01013500` diagnostic report now carries those flags.
As of the 2026-05-17 follow-up, those selected-vs-all terminal hydrograph
audits are machine-readable both in `reports/volume_bias_diagnostics.json` and
as first-class `terminal_hydrograph_scope` row values in
`docs/objective_basin_validation_report.json`. The compliance audit now checks
the row-level field directly (`terminal_hydrograph_scope_rows=7/7`) and
requires the package-emitted machine-readable `terminal_scope_blocker`
classification (`terminal_scope_blocker_rows=7/7`). Future workflow evidence
summaries also copy `terminal_scope_blocker` and `terminal_hydrograph_scope`
into `values` and calibration provenance when relevant, and runtime claim
governance blocks `terminal_scope_claim` while the blocker is present. The
evidence is diagnostic-only: for
`01013500`, all-terminal aggregation closes
volume (`PBIAS=+0.1%`) but worsens NSE (`-0.057` selected to `-0.316`
all-terminal), so it identifies outlet scope without authorizing a claim. For
`03353000` and `09504500`, all-terminal aggregation improves volume
(`PBIAS=-51.7%` and `-36.2%`, respectively) but still fails research-grade
volume evidence. These comparisons guide the next outlet/terminal audit; they
do not replace selected-outlet provenance, routing-flow closure, or locked
calibration verification.
As of the 2026-05-18 refresh, selected-terminal and all-terminal diagnostic
hydrographs also retain `kge_2009_components` evidence and a dominant
KGE-deficit label. The objective audit gates this directly
(`terminal_hydrograph_kge_component_rows=7/7`). The result is sharper blocker
triage without claim promotion: `01013500` all-terminal aggregation fixes
volume but remains correlation-limited (`r=0.374`), `03353000` and
`12031000` remain bias-limited even after all-terminal aggregation, and
`09504500` remains correlation-limited.
The current 2026-05-18 refresh also gates
`terminal_hydrograph_scope_class_rows=7/7`, so the report distinguishes
`selected_metric_passes_but_area_scope_partial`,
`all_terminal_volume_corrected_but_skill_limited`, and
`all_terminal_volume_deficit_persists_after_valid_aggregation` before any
terminal-scope blocker is used to guide new runs.
The same refresh now gates `terminal_outlet_conflict_class_rows=4/4` for
selected-not-nearest terminal rows. `02129000`, `01654000`, `01013500`, and
`12031000` classify as
`selected_largest_terminal_not_nearest_minor_branch_conflict`, which preserves
the scientific distinction between a likely hydrofabric/gauge authority
conflict and a simple wrong-outlet repair.
The 2026-05-17 diagnostic refresh also promotes that governance into the
machine-readable probe order: active `multi_terminal_volume_deficit` rows now
rank terminal inventory reconciliation and selected-vs-all hydrograph review
before CN, ET, or subsurface parameter screens. This keeps calibration effort
behind outlet-scope evidence when the selected terminal may not represent the
observed gauge volume. The 2026-05-18 post-aggregation refresh adds
`all_terminal_hydrograph_volume_deficit_persists` for the four valid
all-terminal aggregation rows where aggregation improves volume but still
misses `|PBIAS| <= 30%`; those rows now queue
`diagnose_post_aggregation_water_balance_deficit` as a fresh-output
water-balance, forcing, ET, runoff-generation, and subsurface process probe
after terminal reconciliation. The same rows now retain
`weather_forcing_summary_path` and a package-written
`reports/weather_forcing_summary.json` payload parsed from SWAT+
precipitation files, so the forcing part of that probe has a concrete
artifact before any future calibration rerun. The forcing payload also
separates full weather-period precipitation from precipitation over the
observed-flow comparison window and records
`observed_runoff_to_overlap_precip_ratio`, preventing warmup-period totals
from being used as validation-period volume evidence. The objective audit now
promotes this into a standalone forcing-context requirement for all five active
volume-bias rows, including the outlet-scope mismatch row where all-terminal
aggregation is not the primary diagnosis. The same evidence now carries a
post-aggregation process context for the four residual all-terminal
volume-deficit rows, with explicit no-claim authority and fresh locked-rerun
requirements before any process interpretation can advance to claim evidence.
The forcing evidence also carries a
diagnostic runoff/precipitation plausibility class: four volume rows are
`ordinary_observed_runoff_fraction`, while `12031000` is
`high_observed_runoff_fraction` (`Qobs/P=0.751`), so its residual volume
deficit needs snow/storage, drainage-area, and forcing-area context before
another parameter-only calibration attempt. The `12031000` evidence row now
retains that context directly: `Qobs/P=0.751`, SWAT net water yield/P
`0.271`, selected-terminal flow fraction `0.546`, and observed-area to
all-terminal-area ratio `1.024`, with
`audit_high_observed_runoff_fraction_context` queued as diagnostic-only work.
The same context now carries snow/storage and aquifer evidence from retained
SWAT+ outputs: snowfall/P `0.017`, snowmelt/P `0.017`, snowpack/P
`0.00010`, soil-water change `1.238 mm`, lagged lateral flow `459.993 mm`,
aquifer flow mean `0.0 mm`, and aquifer recharge mean `0.0 mm`. The evidence
now classifies this as a SWAT water-yield gap, snow storage not explaining the
observed runoff fraction, absent aquifer release, and a partial selected
terminal during high runoff demand.
Active failed/warning multi-terminal routing rows now retain
`reports/terminal_trace.json` and a terminal failure class, so topology
mismatches are auditable without re-parsing SWAT+ text outputs. Passed routing
rows retain gate status and closure ratios, but the objective summary
suppresses routing diagnostic flags, terminal-failure labels, and routing
source alternatives from those rows so historical context is not reported as an
active blocker.
The terminal inventory now also carries source-backed NLDI/reference area
context from `delin/validation_result.json` when the snap diagnostic lacks it,
plus selected-terminal, all-terminal, and delineated-area fractions. The
objective audit requires these fields directly on active multi-terminal rows in
`docs/objective_basin_validation_report.json`, not only in the sidecar
`reports/terminal_trace.json`.
The 2026-05-18 authority refresh added official USGS Site Service drainage
area from `drain_area_va` to the same terminal inventory evidence. Objective
rows now retain selected/all-terminal fractions against the official station
area and a `terminal_authority_area_check`; for all eight active
multi-terminal rows the all-terminal footprint is within the authority area
gate while the selected terminal remains partial, so all-terminal hydrographs
remain diagnostic-only and selected-outlet authority still blocks claims.
Those same rows now emit a `terminal_virtual_outlet_candidate` sidecar when
the all-terminal footprints are non-overlapping. The candidate is explicitly
diagnostic-only: it has no claim authority, forbids temporary terminal metrics
as final evidence, and requires explicit virtual outlet provenance plus a fresh
locked rerun before any claim can advance.
The locked-benchmark layer now has a guarded implementation path for that next
experiment: `swat lock-benchmark --virtual-all-terminal-outlet` requires
`--virtual-outlet-authority`, writes `outlet_scope=virtual_all_terminal` and
the terminal GIS ID set into `outlet_provenance.json` and
`benchmark_lock.json`, and scores the fresh output by summing terminal
hydrographs. Sensitivity screens, calibration candidates, and verification
reruns against such a lock now pass `outlet_policy=all_terminal_sum` into the
real-engine objective, so virtual-outlet experiments cannot silently fall back
to single-channel calibration evidence. The canonical `swat workflow run`
command now exposes the same guarded relock through
`--virtual-all-terminal-outlet --virtual-outlet-authority ...`, which means
virtual outlet follow-up experiments remain package-governed rather than
script-defined. Runtime claim governance now also emits and enforces
`virtual_outlet_scope_gate` for `outlet_scope=virtual_all_terminal`: the gate
requires documented authority, terminal GIS IDs, a multi-terminal inventory,
non-overlapping terminal topology, nonzero all-terminal outflow, and
all-terminal routed/mass closure before same-scope calibration or routing claims
can proceed. The locked diagnostic calibration path now passes the same virtual
scope from `benchmark_lock.json` into the final locked-calibrated `TxtInOut`
routing gate, so post-calibration verification cannot silently evaluate a
single selected terminal for an all-terminal virtual benchmark. The objective
summarizer now preserves `outlet_scope`, `outlet_policy`, selected terminal GIS
IDs, virtual outlet authority, and the full `virtual_outlet_scope_gate` payload
for future virtual all-terminal rows; the production audit currently records
`virtual_outlet_scope_gate_rows=0/0` and will fail if any future virtual row
lacks that machine-readable gate evidence.
For `01013500`, selected terminal area is only `0.480` of NLDI while
all-terminal area is `0.983`, which explains why all-terminal volume closure is
diagnostically informative but cannot substitute for selected-outlet authority.
Failed calibration rows now also expose calibration-history summaries directly
in `docs/objective_basin_validation_report.json`: volume-gate pass count,
physical-gate pass count, best failed phase, and best failed candidate metrics
by absolute PBIAS. The current histories distinguish volume-search failures
(`01013500`, `03353000`, `01493500`, all with zero volume-pass candidates)
from physical/skill-promotion failures after volume matching (`01547700`,
`01491000`, `09504500`, all with many volume-pass candidates but zero
physical-pass candidates).
Future locked calibration histories write per-candidate physical-gate condition
codes and dominant blockers, and the objective report backfills the same counts
from existing compact objective traces when older history CSVs lack those
columns. Existing traces show `01491000` dominated by `ET_DOMINATED` and
`MASS_IMBALANCE`, `03353000` dominated by `VOLUME_BIAS`, and `09504500`
dominated by `NEGATIVE_SKILL` plus volume/ET blockers.
Routing-unit scale-suspect rows now retain
`ru_outflow_to_basin_wateryld_ratio` and the
`routing_unit_outflow_unit_semantics_suspect` flag, so repeated
`fail_mass_closure` rows can distinguish likely output-semantics or generation
path issues from generic terminal mass imbalance. These rows now also retain
source-backed routing alternatives and a recommended probe order for terminal
inventory/aggregation, routing-unit output semantics, and channel-rate versus
basin-yield semantics before any research-grade routing claim is allowed.
Routing `warning` status is calibration-permissive but research-grade-blocking;
workflow evidence and objective rows now list `routing_flow` in `gates_failed`
for warning rows while preserving the distinction from hard calibration
blockers.
Mass traces now also retain the basin water-balance routed-to-channel terms
(`surq_cha`, `latq_cha`, `satex_chan`) as a diagnostic comparison. The routing
gate still uses generic `wateryld` as the conservative closure reference
because current objective evidence is inconsistent: several failed rows match
the routed-to-channel reference, while older superseded `12031000` evidence
matched `wateryld`; the fresh canonical rerun now keeps `12031000`
exploratory behind terminal-scope and volume/routing blockers. Rows where the
routed-to-channel comparison matches terminal flow are flagged with
`routed_to_channel_reference_matches_terminal` and require a source-semantics
audit before any routing claim is promoted. The current objective report has
no stale evidence-summary versus gate-artifact routing status mismatches after
the 2026-05-15 refresh. Warning rows remain blocked for research-grade claims
and must not be treated as promoted outcomes.
2026-05-14 routing-scope hardening: future mass traces and routing-flow gates
also retain all-terminal routed-to-channel closure, all-terminal mass closure,
and selected-terminal share of all terminal flow. This follows the official
SWAT+ output semantics that distinguish generated `wateryld` from channel-
receiving `surq_cha`/`latq_cha`/`satex_chan` and channel `flo_in`/`flo_out`.
The new fields are diagnostic-only until a fresh canonical rerun writes them
into each evidence summary; they do not promote claims from existing stale
artifacts.
Skill diagnostic rows now retain source-backed alternatives and a recommended
fresh-output probe order. The alternatives prioritize `SURLAG` for surface-runoff
lag and peak timing, `CN2`/`ESCO`/`EPCO` for runoff and ET partitioning,
`LAT_TTIME` plus subsurface partition controls for recession/baseflow behavior,
governed `SFTMP`/`SMTMP` for snow timing, and explicit replacement of legacy
`GW_DELAY` advice with supported full-mode controls. Web/source research on
2026-05-14 confirmed SWAT+ documents lateral-flow lag through `LAT_TTIME` and
the open-source full-mode calibration path handles `lat_ttime`, so future
recession diagnostics now point at `LAT_TTIME` instead of unsupported
`GW_DELAY`. Refreshed `01654000`
diagnostics now classify `SFTMP`/`SMTMP` as governed controls, so there are no
current superseded unsupported skill-parameter rows. Six rows now also expose
`skill_probe_gap_parameters`, making clear where source-backed skill diagnostics
recommend governed controls that were not retained by the basin-specific
sensitivity screen. These gaps are now written by the package-owned locked
calibration diagnostics into `skill_diagnostics.json` with the retained
sensitivity-screen classes; the objective report aggregates that evidence
rather than being the only source of the gap classification.
The locked physical gate now uses the same negative-NSE exception as the
research metric gate: `NSE < 0` remains blocking unless KGE is at least `0.40`,
PBIAS is within `±30%`, and package-written `skill_diagnostics.json` documents
a timing or peak-lag limitation. This makes the exception evidence-backed
instead of agent-asserted and does not bypass routing, calibration
verification, sensitivity, soil-fidelity, fresh-output, outlet, or contract
gates.
Full-mode locked calibrations write candidate-level physical-gate evidence
during objective scoring. The staged selector keeps the volume gate for
earlier diagnostic phases and requires `calibration_process_gate_passed` before
a candidate can be promoted by the final KGE/NSE finetune phase when that
candidate evidence is available. Candidate process gates exclude skill-only
claim threshold codes (`NEGATIVE_SKILL`, `BELOW_RESEARCH_SKILL`) so the
finetune phase can repair the metric deficit it is designed to optimize, while
still rejecting ET-, volume-, runoff-, and water-balance-failing candidates.
When prior candidate gate evidence exists, the final phase also requires at
least one earlier volume-valid candidate to have passed the calibration process
gate before `kge_nse_finetune` starts. If no such candidate exists,
`history.csv` records `blocked_preceding_process_gate` and calibration raises a
typed blocker before evaluating any final-phase KGE/NSE candidate.
The candidate history retains both `physical_gate_passed` and
`calibration_process_gate_passed`, and `best_solution.json` records the
finetune gate, so high-skill ET- or water-balance-failing candidates cannot
silently win the final selector. As of 2026-05-16, locked verification also
forces a fresh real-engine objective rerun before promotion:
`verify_calibration()` calls `make_real_objective(..., keep_workdirs=True,
force_fresh=True)`, preserving the promotable verification `TxtInOut` while
deleting any old hashed verification workdir. `verification_summary.json`
records `fresh_outputs=true` and
`fresh_output_policy=force_fresh_real_engine_objective`.
The refreshed `03351500` rerun now treats ET-dominated water-balance failures
as diagnostic-calibration eligible, consistent with SWAT+'s documented soft
water-balance calibration sequence for `esco`, `petco`, `latq_co`, and
`perco`. Candidate-level physical-gate evidence then exposed a separate
routing-unit hyd-type problem: generated full-mode `rout_unit.con` rows were
routing `tot` plus explicit `sur` and `lat`, which double-counted water
(`surq_cha + latq_cha` was approximately `2x` basin `wateryld`).
A fresh canonical rerun now emits and normalizes LSU/routing-unit routes as
`sur` plus `lat` only. The locked final `03351500` evidence is
`research_grade` with `NSE=0.313`, `KGE=0.521`, `PBIAS=-5.59%`, passing
physical gates, and passing routing-flow closure. The row still documents two
terminal outlets and selected-terminal share `0.9256`, but
`missing_terminal_gis_ids`, `orphan_terminal_gis_ids`, and
`material_missing_terminal_gis_ids` are empty in the objective report and no
longer block the claim.
The refreshed `01493500` rerun reached basin-specific sensitivity screening
and locked candidate probes, but no candidate passed the phase-1 volume gate.
It is therefore classified as `blocked_by_volume_gate` rather than as a
completed calibrated row requiring hydrograph or delta-metric evidence.
The refreshed `01491000` canonical rerun now passes routed-flow closure and no
longer writes `tot` routing-unit hyd-type rows, but final physical gates still
fail for ET, mass, and skill. Mixed `MASS_IMBALANCE` plus repairable
volume/ET/skill blockers may now enter diagnostic calibration; `MASS_IMBALANCE`
alone remains a hard pre-calibration stop. The 01491000 diagnostic search
attempted volume, sensitivity, baseflow/subsurface, peaks/timing, and final
KGE/NSE phases across 157 fresh candidates. Although 126 candidates passed the
volume gate, 0 passed the candidate calibration process gate because
`ET_DOMINATED` and `MASS_IMBALANCE` persisted. The row is therefore classified
as `blocked_by_promotion_gate`, final metrics remain the baseline
(`NSE=-0.096`, `KGE=0.105`, `PBIAS=-29.94%`), and temporary candidate metrics
are not promoted as final evidence. The objective row exposes the failed phase
(`kge_nse_finetune`), the failure message, final metric authority (`none`),
and `temporary_candidate_metrics_allowed_as_final=false` without requiring
agents to inspect nested calibration provenance.
All eight failed or blocked calibration-search rows now expose the same
row-level failure-phase, failure-message, final-metric authority,
temporary-candidate guard, and calibration-provenance path evidence, so
calibration failures are no longer silent or nested-only blockers in the
objective report.
Future canonical workflow evidence now promotes the same calibration
failure-phase and final-metric-authority fields into `evidence_summary.json`
`values`, so package-owned evidence carries the guard directly instead of
requiring the objective summarizer to parse nested calibration provenance.
Prepared-directory and calibration-candidate full-mode reruns now normalize
routing-unit files before every fresh solver execution. `orchestrate.py`
applies full routing fixes to prepared or built `TxtInOut` directories before
baseline reruns, and the real-engine objective applies the same fix to each
candidate copy while including `routing_fixes.py` in the objective-cache
signature. This supersedes the earlier `01013500` diagnostic-looking evidence
whose locked calibration copy retained legacy `tot` plus `sur`/`lat` rows. The
fresh canonical `01013500` rerun has no `tot` rows in the live full-mode
TxtInOut, does not create a locked calibrated TxtInOut because no candidate
passed the volume promotion gate, and remains `exploratory` with
`NSE=-0.057`, `KGE=-0.025`, `PBIAS=-57.21%`,
`calibration_final_metrics_authority=none`, and
`temporary_candidate_metrics_allowed_as_final=false`.
The refreshed `01654000` prepared rerun now screens all non-dead full-mode
controls instead of only governance-default active/weak controls. It retains
`CN2`, `PERCO`, `LATQ_CO`, `PET_CO`, `ESCO`, `SURLAG`, `SFTMP`, `SMTMP`, and
`LAT_TTIME`, and the locked candidate search keeps compact objective traces in
the artifact directory while running disposable copied SWAT+ workspaces in
local temp. Dense one-at-a-time plus random combination volume probes repaired
PBIAS from `+78.27%` to `-24.41%`, with final routed-flow closure passing.
After adding `LAT_TTIME` to the governed bridge and baseflow/subsurface phase
and fixing the final selector to prioritize KGE once NSE is nonnegative, the
selected locked candidate improves NSE from `-0.407` to `0.044` and KGE from
`-0.081` to `-0.026`. The basin remains `exploratory` because final locked
skill is below research-grade thresholds, so the primary blocker is
`BELOW_RESEARCH_SKILL` without relaxing any claim gate.
This is especially important for `03353000`: its headline metrics pass the
numeric thresholds (`KGE=0.598`, `NSE=0.412`, `PBIAS=-19.3`), but it remains
exploratory because the evidence records degraded soils (`soil_mode=fallback`,
`pct_fallback_soils=100%`, `soil_overlay_gap_fraction=95.2%`), ET-dominated
physical conditions, missing basin-specific ET parameter screening, and a
routing `fail_mass_closure` warning. Metrics alone still cannot promote a
claim.

2026-05-16 gNATSGO mosaic update: the `03353000` fallback-soil result above
was traced to a package acquisition bug. Planetary Computer returned multiple
state/tile mukey rasters for the basin, but the fetch path previously clipped
and returned only the first overlapping item. Clean canonical reruns at
`demo_runs/workflow/gnatsgo_mosaic_03353000_2010_2019_nocal` and
`demo_runs/workflow/gnatsgo_mosaic_03353000_2010_2019_cal` now write
`soil_mode=high_fidelity`, `soil_provenance_mode=gnatsgo_raster`,
`pct_fallback_soils=0.0`, and `gnatsgo_unique_mukeys=460`. That fixes the
soil-fidelity/provenance blocker, but it also shows the earlier good metrics
were not defensible: with full gNATSGO coverage the calibrated-run baseline is
`NSE=0.123`, `KGE=-0.008`, and `PBIAS=-69.78%`, with failed physical gates
(`ET_DOMINATED`, `VOLUME_BIAS`, `BELOW_RESEARCH_SKILL`) and a
research-grade-blocking routed-flow warning (`fail_mass_closure`, four
terminal outlets, selected terminal carries about 62.5% of all terminal flow).
The basin-specific sensitivity screen retained `CN2`, `PERCO`, `LATQ_CO`,
`PET_CO`, `ESCO`, `EPCO`, `SURLAG`, `SFTMP`, `SMTMP`, and `LAT_TTIME`, while
`GW_DELAY`, `ALPHA_BF`, and `RCHG_DP` were blocked/dead for this basin.
Diagnostic calibration evaluated 33 fresh real-engine volume-phase candidates;
the best candidate reached `PBIAS=-35.72%`, `NSE=0.439`, and `KGE=0.342`, but
no candidate passed the required `abs(PBIAS) <= 30` promotion gate. Final
metric authority therefore remains `none`,
`temporary_candidate_metrics_allowed_as_final=false`, and the objective row is
`exploratory` with primary blocker `simulated_volume_deficit`.

2026-05-13 event-trace update: canonical workflow `events.jsonl` records now
include `run_id` and `usgs_id` on every event. This makes the structured event
stream bindable to `evidence_summary.json` and `run_manifest.json` without
path inference.

The original 2026-05-12 audit found several important components, but the
canonical agent-governed workflow was not yet authoritative. Documentation and
tests described `swat workflow ...`, but the CLI did not register the
`workflow` subcommand in that checkout. Parameter governance was also split
between the general registry and the full-mode bridge, and the CN2 bridge
behavior was not aligned with its own test expectation.

The immediate priority is no longer restoring the canonical runtime path; it is
using the current 11-basin evidence distribution to harden routing closure,
soil provenance, and calibration skill without relaxing claim gates.

## Audit Commands Run

```bash
PYTHONPATH=src python -m swatplus_builder.cli workflow run --help
PYTHONPATH=src pytest -q tests/test_cli_workflow.py tests/test_workflow_usgs_e2e.py
PYTHONPATH=src pytest -q tests/test_parameter_bridge.py tests/test_parameter_registry.py tests/test_sensitivity_screen.py
```

## Current Requirement Status

| Requirement | Current status | Evidence |
|---|---|---|
| Canonical `swat workflow run --model-family full --calibrate` path | implemented and active, but not yet producing research-grade basin outcomes | `docs/AGENT_WORKFLOW.md`, `src/swatplus_builder/workflows/usgs_e2e.py`, `tests/test_cli_workflow.py`, `tests/test_workflow_usgs_e2e.py` |
| Script policy demotion | implemented for the objective harness; scripts aggregate workflow evidence instead of defining claim tiers | `scripts/run_objective_10basin.py`, `tests/test_script_policy.py` |
| Unified full-mode parameter governance | implemented for `CN2`, `PERCO`, `LATQ_CO`, `PET_CO`, `ESCO`, `EPCO`, `SURLAG`, `ALPHA_BF`, `RCHG_DP`, and `GW_DELAY` | `src/swatplus_builder/params/governance.py`, `docs/CALIBRATION_PARAMETER_REGISTRY.md`, `docs/FULL_MODE_PARAMETER_BRIDGE_3L12.md` |
| Locked calibration auditability | implemented in the canonical workflow, including fresh objective runs, best-solution promotion, clean locked rerun, final gates, and provenance | `src/swatplus_builder/calibration/diagnostic_calibrator.py`, `tests/test_calibration_real_engine.py`, `tests/test_workflow_usgs_e2e.py` |
| Calibration hydrograph comparison | implemented when baseline and locked verification alignments exist; writes observed/baseline-simulated/calibrated-simulated plots and metrics | `src/swatplus_builder/calibration/diagnostic_calibrator.py`, `src/swatplus_builder/calibration/report.py`, `tests/test_workflow_usgs_e2e.py` |
| Volume-bias diagnostics | implemented for rows blocked by active final `VOLUME_BIAS` or `simulated_volume_*`; objective rows retain diagnostic flags, next actions, source-backed alternatives, and recommended probe order, with wetland-aware net water yield in water-balance diagnostics, while historical baseline volume diagnostics are suppressed from rows whose final physical gates pass | `src/swatplus_builder/output/volume_diagnostics.py`, `scripts/run_objective_10basin.py`, `scripts/audit_production_objective.py`, `tests/test_volume_diagnostics.py`, `tests/test_script_policy.py` |
| Skill diagnostics | implemented for locked calibration rows blocked by active final `BELOW_RESEARCH_SKILL` or `NEGATIVE_SKILL`; objective rows retain hydrograph diagnostic flags, structured evidence metrics, next actions, alternatives, probe order, sensitivity-screen coverage gaps, and locked-parameter bound context only while those skill blockers remain active, suppressing historical skill sidecars from rows whose final skill gates pass. Peak timing is now annual/event-window based, with high-flow attenuation reported separately so muted peaks are not misclassified as multi-year timing lag; objective JSON rows expose bound-hit and evidence-metric fields directly. | `src/swatplus_builder/diagnostics.py`, `src/swatplus_builder/calibration/diagnostic_calibrator.py`, `scripts/run_objective_10basin.py`, `scripts/audit_production_objective.py`, `tests/test_diagnostics.py`, `tests/test_workflow_usgs_e2e.py`, `tests/test_script_policy.py` |
| Governed snow process controls | implemented as extended full-mode controls; `SFTMP` and `SMTMP` write `snow.sno:fall_tmp` and `snow.sno:melt_tmp`, are bridge-tested, documented, and eligible only as weak governed controls | `src/swatplus_builder/params/governance.py`, `src/swatplus_builder/full_mode/parameter_bridge.py`, `docs/CALIBRATION_PARAMETER_REGISTRY.md`, `tests/test_parameter_bridge.py`, `tests/test_parameter_registry.py` |
| Governed lateral-flow recession control | implemented as an extended full-mode control; `LAT_TTIME` writes `hydrology.hyd:lat_ttime`, is source-backed by SWAT+ lateral-flow lag documentation and open-source calibration code, and is eligible only after basin-specific recession screening | `src/swatplus_builder/params/governance.py`, `src/swatplus_builder/full_mode/parameter_bridge.py`, `src/swatplus_builder/diagnostics.py`, `docs/CALIBRATION_PARAMETER_REGISTRY.md`, `tests/test_parameter_bridge.py`, `tests/test_parameter_registry.py`, `tests/test_diagnostics.py` |
| Governed channel-routing attenuation controls | implemented as extended full-mode controls; `CH_N2` writes `hyd-sed-lte.cha:mann` and `CH_K2` writes `hyd-sed-lte.cha:k`, are source-backed by SWAT+ channel hydrology and Manning flow/velocity documentation, and enter only through basin-specific locked channel-routing screens for attenuated peak diagnostics | `src/swatplus_builder/params/governance.py`, `src/swatplus_builder/full_mode/parameter_bridge.py`, `src/swatplus_builder/diagnostics.py`, `docs/CALIBRATION_PARAMETER_REGISTRY.md`, `tests/test_parameter_bridge.py`, `tests/test_parameter_registry.py`, `tests/test_diagnostics.py` |
| ET-dominated parameter context | implemented for ET physical blockers; `PET_CO`, `ESCO`, and `EPCO` are marked as requiring basin-specific ET-partition screening instead of being left as generic defaults | `src/swatplus_builder/workflows/usgs_e2e.py`, `scripts/run_objective_10basin.py`, `tests/test_workflow_usgs_e2e.py` |
| Soil-realism diagnostics | implemented for soil-realism build blockers; future full builds write `reports/soil_realism_diagnostics.json` when lower-level soil reports are absent, objective rows require a retained diagnostic artifact, and build-blocked rows are normalized to `soil_mode=not_verified` with `soil_provenance_mode=soil_realism_gate_failed` instead of inheriting requested `high_fidelity` metadata; objective summaries explicitly fail `soil_fidelity` for these rows while retaining `soil_realism_gate_failed` as the primary blocker | `src/swatplus_builder/workflows/full_build.py`, `src/swatplus_builder/orchestrate.py`, `src/swatplus_builder/workflows/usgs_e2e.py`, `scripts/run_objective_10basin.py`, `scripts/audit_production_objective.py`, `tests/test_full_build.py`, `tests/test_workflow_usgs_e2e.py`, `tests/test_script_policy.py` |
| Routing-flow diagnostics | implemented for active final failed/warning routed-flow rows and passed-but-partial terminal-scope blockers; objective rows retain `routing_flow_gates.json`, closure status, closure flags, source-backed alternatives, probe order, and terminal inventory while routing remains failed/warning or terminal scope blocks research-grade claims, while fully passed rows keep status/closure ratios without stale diagnostic flags | `src/swatplus_builder/workflows/usgs_e2e.py`, `scripts/run_objective_10basin.py`, `scripts/audit_production_objective.py`, `tests/test_script_policy.py` |
| Routing mass-closure root-cause flags | implemented for repeated `fail_mass_closure` rows; mass trace now distinguishes channel inflow exceeding basin water yield, selected terminal outflow excess, all-terminal excess, multi-terminal outlet inventory cases, and routing-unit output semantics suspects | `src/swatplus_builder/output/mass_trace.py`, `src/swatplus_builder/workflows/usgs_e2e.py`, `src/swatplus_builder/calibration/diagnostic_calibrator.py`, `tests/test_workflow_usgs_e2e.py` |
| Accepted `01654000` calibration smoke | volume-bias repair now succeeds, KGE/NSE both improve, and locked routing closure passes, but research-grade remains blocked by low final skill (`NSE=0.044`, `KGE=-0.026`, `PBIAS=-24.41`) | `demo_runs/workflow/canonical_cal_smoke_01654000_2010_2019/evidence_summary.json`, `calibration/hydrograph_comparison/` |
| Runtime claim governance | implemented for contract policy, fresh engine output artifact, existing benchmark-lock artifact, selected outlet provenance, terminal-scope blockers, physical gates, routed-flow gates, sensitivity, calibration verification, positive calibration improvement, metric gates, and effective tier downgrade | `src/swatplus_builder/workflows/usgs_e2e.py`, `docs/SCIENTIFIC_CLAIM_GOVERNANCE.md` |
| Soil fidelity claim gate | implemented for research-grade effective tier: degraded soil fallback, missing provenance, non-authoritative `soil_provenance_mode`, missing fallback fraction, or `pct_fallback_soils > 0` blocks `research_grade` but still permits diagnostic evidence generation. Explicit `soil_mode=high_fidelity`, `soil_provenance_mode=gnatsgo_raster`, and numeric zero fallback soils are required for the soil-fidelity pass. | `src/swatplus_builder/workflows/usgs_e2e.py`, `scripts/run_objective_10basin.py`, `src/swatplus_builder/orchestrate.py`, `src/swatplus_builder/workflows/full_build.py`, `tests/test_workflow_usgs_e2e.py`, `tests/test_orchestrate.py`, `tests/test_full_build.py`, `tests/test_script_policy.py` |
| Surface runoff/routing nonzero gate | implemented and covered: `ZERO_SURFACE_RUNOFF` blocks diagnostic/research claims, routed-flow closure blocks calibration and promotion | `src/swatplus_builder/full_mode/water_balance_gate.py`, `tests/test_water_balance_gate.py`, `tests/test_workflow_usgs_e2e.py` |
| Canonical evidence bundle | implemented for `evidence_summary.json`, `EVIDENCE_SUMMARY.md`, `outlet_provenance.json`, `calibration_provenance.json`, `parameter_screen.json`, `physical_gates.json`, `routing_flow_gates.json`, `run_manifest.json`, and `events.jsonl` | `tests/test_workflow_usgs_e2e.py` |
| Objective-suite validation report | implemented and refreshed on 2026-05-18 with 11 evidence summaries, explicit fresher-evidence overrides, 1 research-grade outcome after terminal-scope governance downgraded stale partial-outlet research claims, and selected-not-nearest outlet conflict classes for all 4 required rows | `docs/OBJECTIVE_BASIN_VALIDATION_REPORT.md`, `docs/objective_basin_validation_report.json` |
| HRU overlay gap repair | partially implemented: small categorical nodata gaps are filled by bounded nearest-neighbor repair; broad categorical extrapolation remains blocked for research-grade claims. If partial gNATSGO coverage leaves too many subbasins without valid soil overlay, the builder can rebuild HRUs with a dominant valid constant representative mukey so diagnostic artifacts continue, while the soil realism gate records fallback provenance and blocks research-grade promotion. | `src/swatplus_builder/gis/hru.py`, `examples/build_real_basin.py`, `src/swatplus_builder/gis/overlay_repair.py`, `tests/test_gis_hru.py`, `tests/test_overlay_repair.py`, `tests/test_full_build.py` |
| Soil-source fallback diagnostics | implemented for hard acquisition failures: the build now writes `reports/soil_acquisition_report.json` before raising, records the attempted fallback chain (`external_soils_json` → USDA SDA → optional SoilGrids v2.0 → synthetic diagnostic-only), and promotes the report through `build.diagnostic_artifacts`. | `examples/build_real_basin.py`, `src/swatplus_builder/workflows/full_build.py`, `tests/test_full_build.py`, `tests/test_soilgrids.py` |
| Remaining scientific blockers | not complete: `03351500` is currently research-grade; `02129000` is exploratory under current terminal-scope policy, and other real-basin evidence remains `exploratory` due build-realism, soil-fidelity, physical, routing, terminal-scope, calibration-promotion, or low-skill gates | `docs/OBJECTIVE_BASIN_VALIDATION_REPORT.md`, `docs/OBJECTIVE_COMPLIANCE_AUDIT.md` |

## Original Findings (2026-05-12)

The findings below are preserved as the historical audit baseline. Later
sections titled "Applied" record the fixes that closed many of these original
gaps. Treat the table above and the latest dated sections as the current state.

### 1. Canonical command is not currently authoritative

Required command:

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

Current evidence:

- `PYTHONPATH=src python -m swatplus_builder.cli workflow run --help` fails with
  `No such command 'workflow'`.
- `src/swatplus_builder/workflows/usgs_e2e.py` exists and exposes
  `RunUSGSWorkflowRequest`, but `src/swatplus_builder/cli.py` does not register
  a workflow Typer sub-app.
- `docs/AGENT_WORKFLOW.md` says `swat workflow run` is implemented, but the
  current CLI surface disagrees.

Impact:

Agents cannot use the documented canonical command. Any benchmark or
calibration path using scripts or lower-level commands can bypass workflow
claim policy.

Required fix:

Register `swat workflow negotiate` and `swat workflow run` in `cli.py`, including
`--model-family`, `--warmup-years`, `--calibrate`, `--claim-tier`, `--contract`,
and `--json`.

### 2. Scripts bypass scientific policy

Current evidence:

- `scripts/benchmark_10_basin.py` and `scripts/benchmark_full_10basin.py`
  contain their own calibration/tier logic.
- `scripts/cal_5_basin.py` derives tier labels from local strings.
- `scripts/run_objective_10basin.py` calls `run_usgs_workflow`, but it also
  post-processes calibration status and tier/blocker fields.

Impact:

Scripts can define scientific outcomes outside the package gate layer. This
violates the rule that scripts may call the workflow but cannot define claim
policy.

Required fix:

Demote scripts to harness/reporting only. They may aggregate
`evidence_summary.json`, but tier, blocker, gate, and calibration status must
come from the workflow evidence bundle.

### 3. Parameter registry and full-mode bridge are not aligned

Required review set:

`CN2`, `PERCO`, `LATQ_CO`, `PET_CO`, `ESCO`, `EPCO`, `SURLAG`, `ALPHA_BF`,
`RCHG_DP`, `GW_DELAY`.

Current evidence:

- `src/swatplus_builder/full_mode/parameter_bridge.py` supports writers for
  `PERCO`, `LATQ_CO`, `PET_CO`, `RCHG_DP`, and `GW_DELAY`.
- `src/swatplus_builder/params/registry.py` does not register `PERCO`,
  `LATQ_CO`, `PET_CO`, or `RCHG_DP`.
- `run_usgs_workflow` currently screens `["CN2", "ALPHA_BF", "SOL_K", "ESCO",
  "SURLAG"]`, not the requested full-mode parameter set.

Impact:

The sensitivity screen, registry, bridge, docs, and calibration logic do not
agree on what full-mode parameters are legal. A bridge-supported parameter may
be unknown to the registry, and a registry parameter may not be bridge-safe for
full-mode calibration.

Required fix:

Create one full-mode parameter governance table with:

`name`, `target_file`, `target_column`, `range`, `default`, `scope`,
`activity_class`, `evidence_source`, `supported_model_family`,
`claim_tier_allowance`.

### 4. CN2 bridge semantics are not settled

Current evidence:

- `tests/test_parameter_bridge.py::TestParameterBridge::test_cn2_shifts_wood_rows_by_delta_to_target`
  fails.
- The test expects `fal_bare` to remain unchanged and only `wood_*` rows to
  shift.
- `_apply_cn2()` currently shifts every parseable row in `cntable.lum`,
  including `fal_bare`.

Impact:

CN2 edits are not scientifically narrow. This can unintentionally modify land
uses outside the intended calibration scope and invalidate parameter provenance.

Required fix:

Decide the intended semantics:

- landuse-filtered CN2 calibration, e.g. only `wood_*`, or
- global CN table calibration with explicit documentation and tests.

Then update both implementation and tests. Until this is resolved, CN2 cannot
support research-grade full-mode claims.

### 5. Tests are not green in the current checkout

Failing command:

```bash
PYTHONPATH=src pytest -q tests/test_cli_workflow.py tests/test_workflow_usgs_e2e.py
```

Failure class:

- all `tests/test_cli_workflow.py` tests fail because `swat workflow` is not
  registered in the CLI.

Failing command:

```bash
PYTHONPATH=src pytest -q tests/test_parameter_bridge.py tests/test_parameter_registry.py tests/test_sensitivity_screen.py
```

Failure class:

- CN2 bridge test fails because `fal_bare` is modified.

Impact:

The current checkout does not satisfy the zero-regression requirement.

### 6. Calibration evidence is not yet canonical

Current evidence:

- `swat locked-calibrate` exists and writes verification artifacts.
- `run_usgs_workflow` writes `reports/diagnostic_calibration.json`, but its
  current diagnostic calibrator delegates to missing stage scripts
  (`scripts/calibrate_lte_stage1.py`, `scripts/calibrate_lte_stage2.py`,
  `scripts/calibrate_lte_stage3.py`) and does not promote a locked calibrated
  TxtInOut.
- Temporary candidate metrics are not yet prevented by a canonical workflow
  artifact contract.

Impact:

The repo has calibration verification machinery, but the canonical workflow
does not yet guarantee:

- candidate runs use clean outputs,
- best candidate is promoted to locked calibrated TxtInOut,
- locked artifact is rerun cleanly,
- final metrics and gates come from the same artifact.

Required fix:

Move locked-calibration verification into the canonical `workflow run
--calibrate` path, or make the workflow call the locked-calibration subsystem
directly.

### 7. Evidence bundle is incomplete relative to contract design

Required files per mission:

- `evidence_summary.json`
- `outlet_provenance.json`
- `calibration_provenance.json`
- `parameter_screen.json`
- `run_manifest.json`
- `events.jsonl` if feasible

Current evidence:

- `run_usgs_workflow` writes `evidence_summary.json` and
  `outlet_provenance.json`.
- It writes `reports/sensitivity_screen.json` and
  `reports/diagnostic_calibration.json`.
- It does not currently write canonical top-level
  `calibration_provenance.json`, `parameter_screen.json`, `run_manifest.json`,
  or `events.jsonl`.
- `evidence_summary.json` does not include explicit `allowed_claims` and
  `blocked_claims`.

Impact:

Agents must infer too much from implementation-specific report files. The
package does not yet emit the evidence bundle described by the agent-governed
software guide.

### 8. Documentation is partially restored but inconsistent

Current evidence:

- `docs/AGENT_WORKFLOW.md` describes `swat workflow run`.
- The CLI does not expose `workflow`.
- `PROJECT.md` was not present in the repo root during this audit.
- `docs/SWATPLUS_MODELING_PLAYBOOK.md` contains extensive historical evidence,
  but some entries refer to older phases and may not match the current checkout.

Impact:

The cold-start and executor docs can lead agents to commands that fail or to
status claims that are no longer true.

Required fix:

After restoring the canonical command, update:

- `PROJECT.md`
- `docs/AGENT_WORKFLOW.md`
- `docs/SWATPLUS_MODELING_PLAYBOOK.md`
- `docs/CALIBRATION_PARAMETER_REGISTRY.md`
- `SKILL.md`

Only implemented behavior should appear in `SKILL.md`.

## Immediate Fix Order

1. Restore `swat workflow negotiate/run` in `cli.py`.
2. Add `--model-family full` to workflow request and evidence.
3. Write top-level `parameter_screen.json`, `calibration_provenance.json`,
   `run_manifest.json`, and `events.jsonl`.
4. Add `allowed_claims` and `blocked_claims` to `evidence_summary.json`.
5. Align full-mode registry and bridge for the required parameter set.
6. Resolve CN2 semantics and make `tests/test_parameter_bridge.py` pass.
7. Move locked calibrated rerun/promotion into the canonical workflow path.
8. Demote benchmark/calibration scripts to harnesses that aggregate canonical
   evidence only.
9. Re-run targeted tests, then run the 10-basin validation harness.

## Phase 0 Exit Status

Phase 0 is complete as an audit, not as a production certification.

The pipeline should not be benchmarked for research-grade pass count until the
canonical workflow command and parameter governance issues above are fixed.

## Post-Audit Fixes Applied

Date: 2026-05-12

The first two blocking findings were corrected immediately after this audit:

1. `swat workflow negotiate/run` is now registered in `cli.py`.
2. `swat workflow run` now exposes `--model-family` and records model family in
   workflow evidence.
3. CN2 full-mode bridge semantics are now explicit and test-aligned:
   only `wood_*` rows in `cntable.lum` are shifted.
4. `PERCO`, `LATQ_CO`, `PET_CO`, and `RCHG_DP` were added to the central
   parameter registry.

Verification:

```bash
PYTHONPATH=src pytest -q tests/test_cli_workflow.py tests/test_workflow_usgs_e2e.py
PYTHONPATH=src pytest -q tests/test_parameter_bridge.py tests/test_parameter_registry.py tests/test_sensitivity_screen.py
```

## Phase 1 Evidence-Bundle Fixes Applied

Date: 2026-05-12

The canonical workflow now writes the required top-level evidence-bundle files
on every run, including blocked runs:

1. `evidence_summary.json`
2. `outlet_provenance.json`
3. `calibration_provenance.json`
4. `parameter_screen.json`
5. `run_manifest.json`
6. `events.jsonl`

`evidence_summary.json` now also contains explicit `allowed_claims` and
`blocked_claims`, so an executor agent does not need to infer claim status from
raw metrics or missing files.

## Phase 1 Locked-Calibration Authority Applied

Date: 2026-05-13

The canonical workflow no longer delegates calibration to missing stage scripts
or screens the old partial parameter set.

Implemented changes:

1. Added `src/swatplus_builder/params/governance.py` as the shared full-mode
   parameter governance source for:
   `CN2`, `PERCO`, `LATQ_CO`, `PET_CO`, `ESCO`, `EPCO`, `SURLAG`, `ALPHA_BF`,
   `RCHG_DP`, and `GW_DELAY`.
2. `swat workflow run --calibrate` writes those ten governed parameters into
   `parameter_screen.json` and `reports/sensitivity_screen.json`.
3. `run_diagnostic_calibration()` now uses the locked-benchmark subsystem when
   `benchmark/benchmark_lock.json` and a prepared `TxtInOut` exist:
   candidate evaluations use fresh copied outputs, verification is independent,
   and a verified run is promoted to `calibration/locked_calibrated_TxtInOut`.
4. When the lock or `TxtInOut` is missing, calibration is explicitly blocked
   with `missing_artifacts`, `final_metrics_authority=none`, and
   `temporary_candidate_metrics_allowed_as_final=false`.

Remaining blocker:

`run_pipeline()` still does not produce the locked benchmark and prepared
`TxtInOut` artifacts needed for a fresh canonical basin run to complete locked
calibration end-to-end.

## Phase 1 Fresh-Run Handoff Applied

Date: 2026-05-13

`run_pipeline()` now has a package-owned handoff from prepared SWAT+ artifacts
to locked calibration:

1. If `project/Scenarios/Default/TxtInOut` exists, `run_pipeline()` calls the
   clean solver wrapper, which deletes stale outputs before execution and
   verifies fresh SWAT+ output.
2. It loads `outputs/obs_q.csv` when present or fetches NWIS discharge for the
   requested period.
3. It calls `lock_benchmark()` to write `benchmark/benchmark_lock.json`,
   `benchmark/alignment.csv`, `benchmark/metrics.json`, and outlet provenance.
4. The workflow then has the artifacts required by
   `run_diagnostic_calibration()` to run locked calibration and verification.
5. If no prepared `TxtInOut` exists, `run_pipeline()` returns
   `status=BLOCKED`, `blocker_class=prepared_txtinout_missing`, and
   `locked_calibration_ready=false`; `swat workflow run` propagates that blocker
   instead of reporting a successful run.

Verification:

```bash
PYTHONPATH=src pytest -q tests/test_orchestrate.py tests/test_workflow_usgs_e2e.py tests/test_parameter_registry.py tests/test_parameter_bridge.py tests/test_sensitivity_screen.py tests/test_cli_workflow.py
```

Result: 27 passed.

CLI smoke:

```bash
PYTHONPATH=src python -m swatplus_builder.cli workflow run --usgs-id 01654000 --model-family full --start 2010-01-01 --end 2019-12-31 --warmup-years 3 --claim-tier diagnostic --out-dir /private/tmp/swat_workflow_blocker_smoke --json
```

Result: `success=false`, `blocker_class=prepared_txtinout_missing`.

Remaining blocker:

Empty run directories still need native full-mode build integration. The
existing real-basin build logic lives in `examples/build_real_basin.py`; it must
be promoted into package-owned workflow code before the 10-basin suite can be
treated as canonical production evidence.

## Phase 1 Package Build Handoff Applied

Date: 2026-05-13

The canonical workflow now has a package-owned full-mode build handoff:

1. Added `src/swatplus_builder/workflows/full_build.py`.
2. `run_pipeline()` calls `build_full_model()` when no prepared `TxtInOut`
   exists.
3. Build results are serialized into `run_config.json` under `build`.
4. Build failures are classified, including:
   - `external_data_provider_unreachable`
   - `engine_run_failed_during_build`
   - `full_model_build_topology_failed`
   - `full_model_build_missing_txtinout`
   - `full_model_build_failed`
5. Successful package build handoff must still be followed by a clean solver
   rerun and benchmark lock before calibration.

Verification:

```bash
PYTHONPATH=src pytest -q tests/test_orchestrate.py tests/test_workflow_usgs_e2e.py tests/test_parameter_registry.py tests/test_parameter_bridge.py tests/test_sensitivity_screen.py tests/test_cli_workflow.py
```

Result: 28 passed.

Remaining blocker:

`full_build.py` currently wraps `examples/build_real_basin.py` under a package
boundary. That is enough for the canonical workflow to own policy and blocker
classification, but the hydrologic build internals still need to be promoted
from example code into first-class package modules before this can be called
fully production-grade.

## Phase 1 Runtime Claim Gates Applied

Date: 2026-05-13

The workflow now writes and uses `physical_gates.json` as a canonical evidence
artifact.

Implemented behavior:

1. `swat workflow run` evaluates physical gates after build/run evidence is
   available.
2. `run_manifest.json` records `physical_gates.json`.
3. `allowed_claims` and `blocked_claims` now consider:
   - contract policy
   - fresh solver rerun status
   - benchmark lock provenance
   - physical gates
   - research metric thresholds (`KGE`, `NSE`, `PBIAS`)
   - calibration success/verification status
4. A research metric claim is blocked when `PBIAS` is missing or outside the
   gate, even if `NSE`/`KGE` are otherwise acceptable.
5. A physical gate failure blocks research claims even when headline metrics
   pass.

Verification:

```bash
PYTHONPATH=src pytest -q tests/test_workflow_usgs_e2e.py tests/test_orchestrate.py tests/test_parameter_registry.py tests/test_parameter_bridge.py tests/test_sensitivity_screen.py tests/test_cli_workflow.py
```

Result: 29 passed.

## Phase 1 Full-Mode Calibration Bridge Applied

Date: 2026-05-13

Locked calibration now uses the correct parameter bridge for the canonical
full-mode workflow.

Implemented behavior:

1. `make_real_objective()` accepts `parameter_mode`.
2. `parameter_mode="full"` applies parameters through
   `apply_parameters_to_full_swat_txtinout()`.
3. `calibrate_against_lock()` and `verify_calibration()` accept
   `parameter_mode`.
4. `run_diagnostic_calibration()` calls both locked calibration and verification
   with `parameter_mode="full"`.
5. Regression coverage confirms a full-mode `PERCO` calibration proposal edits
   `hydrology.hyd` inside the objective-run `TxtInOut`.

Verification:

```bash
PYTHONPATH=src pytest -q tests/test_calibration_real_engine.py tests/test_locked_benchmark.py tests/test_workflow_usgs_e2e.py tests/test_orchestrate.py tests/test_parameter_registry.py tests/test_parameter_bridge.py tests/test_sensitivity_screen.py tests/test_cli_workflow.py
```

Result: 50 passed.

## Phase 1 Staged Diagnostic Calibration Applied

Date: 2026-05-13

Locked calibration no longer selects the best candidate by NSE alone or from a
single pooled search. It now follows the required diagnostic sequence:
`volume -> baseflow_subsurface -> peaks_timing -> kge_nse_finetune`.

Implemented behavior:

1. `evaluate_run()` now emits `pbias`.
2. `calibrate_against_lock()` writes `metric_pbias` and
   `volume_gate_passed` to `calibration_reports_locked/history.csv`.
3. `history.csv` now includes:
   - `phase`
   - `phase_order`
   - `phase_parameters`
   - `phase_objective`
   - per-row candidate status.
4. Candidate selection is now staged and volume-first:
   - no candidate can become best unless `abs(pbias) <= 30`;
   - each phase carries the best volume-valid settings forward;
   - volume phase minimizes absolute PBIAS before skill terms;
   - baseflow/subsurface and peaks/timing phases maintain the volume gate;
   - KGE/NSE fine-tuning only ranks volume-valid candidates;
   - when candidate physical/process-gate evidence exists, KGE/NSE
     fine-tuning cannot start until a prior volume-valid candidate has passed
     the calibration process gate.
5. If no candidate passes the volume gate for an active phase, locked
   calibration raises a typed pipeline blocker. If prior full-mode candidates
   fail the process gate, locked calibration records
   `blocked_preceding_process_gate` and later-stage KGE/NSE fine-tuning is not
   allowed to define evidence. The phase-tagged
   `history.csv` is written before raising so blocked calibration still leaves
   candidate evidence.
6. `best_solution.json` and `calibration_provenance.json` record:
   - `selection_policy=staged_volume_baseflow_peaks_then_nse_kge`
   - `volume_gate=abs(pbias) <= 30`
   - `calibration_protocol=[...]`.

Verification:

```bash
PYTHONPATH=src pytest -q tests/test_weather_gridmet.py tests/test_gis_hru.py tests/test_full_build.py tests/test_nldi_fallback.py tests/test_script_policy.py tests/test_workflow_usgs_e2e.py tests/test_locked_benchmark.py tests/test_calibration_real_engine.py tests/test_orchestrate.py tests/test_parameter_registry.py tests/test_parameter_bridge.py tests/test_sensitivity_screen.py tests/test_cli_workflow.py tests/test_gis_snap_max_acc.py
```

Result: focused suite passed with one skipped live GridMET test.

## Phase 1 Accepted Research-Window Smoke Applied

Date: 2026-05-13

The canonical CLI can now express accepted research-grade workflow metadata
without hand-editing a contract file:

```bash
--contract-status accepted --accepted-by user
```

Implemented behavior:

1. `swat workflow run` accepts `--contract-status` and `--accepted-by`.
2. Contract-file metadata is still supported; explicit flags can provide
   acceptance when no contract file is supplied.
3. GridMET repair now handles bounded isolated provider gaps across longer
   windows while still failing consecutive or larger missing ranges.
4. An accepted 10-year research request for USGS `01654000`
   (`2010-01-01` to `2019-12-31`, 3-year warmup) was run through the canonical
   workflow.
5. The run completed:
   - NLDI boundary,
   - DEM and NLCD,
   - WhiteboxTools delineation,
   - gNATSGO and soils,
   - GridMET for 25 stations,
   - SWAT+ Editor operations,
   - SWAT+ engine execution,
   - benchmark lock,
   - sensitivity screen.
6. Calibration was correctly blocked before parameter search because
   `physical_gates.json` failed:
   - `NSE=-0.40657565608968316`
   - `KGE=-0.08092980170725572`
   - `PBIAS=78.26934844366399`
7. The evidence bundle reports `effective_claim_tier=exploratory`; this is the
   defensible outcome because physical gates failed despite successful build
   and fresh engine output.
8. `evidence_summary.json` now records runtime gate accounting explicitly:
   failed physical gates and blocked calibration verification appear in
   `gates_failed`; fresh engine output and benchmark lock evidence appear in
   `gates_passed`.
9. Physical gates now include explicit benchmark-volume bias from PBIAS. For
   the accepted `01654000` run, the blocker is classified as
   `VOLUME_BIAS` (`PBIAS=+78.3%`, simulated flow overpredicts observed volume)
   plus `NEGATIVE_SKILL`, so calibration remains blocked before search.
10. Physical gates emit `condition_codes`, `dominant_blocker`, and
    `recommended_next_action` for agent-readable blocker triage.

Verification:

```bash
PYTHONPATH=src pytest -q tests/test_cli_workflow.py tests/test_weather_gridmet.py
PYTHONPATH=src python -m swatplus_builder.cli workflow run --usgs-id 01654000 --model-family full --start 2010-01-01 --end 2019-12-31 --warmup-years 3 --claim-tier research_grade --contract-status accepted --accepted-by user --calibrate --out-dir demo_runs/workflow/canonical_cal_smoke_01654000_2010_2019 --json
```

Result: CLI/weather tests passed with one skipped live GridMET test; accepted
research-window smoke completed with `blocker_class=null`,
`physical_gates_status=failed`, `calibration_status=blocked_by_physical_gates`,
and `effective_claim_tier=exploratory`.

## Phase 1 Final Locked-Artifact Gate Applied

Date: 2026-05-13

Calibration success now requires gates on the promoted locked calibrated
`TxtInOut`, not only on temporary candidate runs or baseline outputs.

Implemented behavior:

1. After `verify_calibration()` independently reruns the best solution,
   `run_diagnostic_calibration()` copies the verified objective-run `TxtInOut`
   to `calibration/locked_calibrated_TxtInOut`.
2. The promoted locked `TxtInOut` is checked with the physical water-balance
   gate using verified NSE/KGE.
3. Calibration success requires:
   - independent verification improved over baseline,
   - promoted `locked_calibrated_TxtInOut` exists,
   - final physical gates pass on that promoted artifact.
4. `calibration_provenance.json` records `final_physical_gates`.

Verification:

```bash
PYTHONPATH=src pytest -q tests/test_workflow_usgs_e2e.py tests/test_locked_benchmark.py tests/test_calibration_real_engine.py tests/test_orchestrate.py tests/test_parameter_registry.py tests/test_parameter_bridge.py tests/test_sensitivity_screen.py tests/test_cli_workflow.py
```

Result: 52 passed.

## Phase 1 Script Policy Demotion Applied

Date: 2026-05-13

Benchmark/calibration scripts no longer define scientific policy.

Implemented behavior:

1. `scripts/run_objective_10basin.py` requests the canonical
   `research_grade` workflow and reads claim tier, blockers, allowed claims,
   and blocked claims from `evidence_summary.json`.
2. The script no longer:
   - imports local physical gates,
   - computes research tier from metrics,
   - invents blocker classes,
   - falls back to unrelated historical metric artifacts.
3. Legacy scripts were demoted to compatibility wrappers:
   - `scripts/benchmark_10_basin.py`
   - `scripts/benchmark_full_10basin.py`
   - `scripts/cal_5_basin.py`
4. Added `tests/test_script_policy.py` to prevent reintroducing ad hoc
   calibration, tier, or blocker logic in benchmark scripts.

Verification:

```bash
PYTHONPATH=src pytest -q tests/test_script_policy.py tests/test_workflow_usgs_e2e.py tests/test_locked_benchmark.py tests/test_calibration_real_engine.py tests/test_orchestrate.py tests/test_parameter_registry.py tests/test_parameter_bridge.py tests/test_sensitivity_screen.py tests/test_cli_workflow.py
```

Result: 54 passed.

## Phase 1 Calibration Sequencing Gate Applied

Date: 2026-05-13

Calibration is now gated before parameter search except for the volume-bias
repair path:

1. The workflow evaluates `physical_gates.json` immediately after pipeline
   build/run evidence is available.
2. `parameter_screen.json` is still written for auditability.
3. If routed-flow closure fails, or physical gates fail for anything other than
   a volume-bias-only blocker, calibration is not attempted and
   `calibration_provenance.json` records:
   - `status=blocked_by_physical_gates`
   - `reason=physical_gates_not_passed`
   - `calibration_sequence=blocked_before_volume_stage`
4. If routed-flow closure passes and the only physical blocker is
   `VOLUME_BIAS`, the workflow may run the locked diagnostic volume phase.
   Final claims still require the locked calibrated `TxtInOut` physical and
   routing gates to pass.
5. This prevents KGE/NSE fine-tuning from proceeding on a physically invalid
   artifact while still allowing the volume phase to repair the one gate it is
   designed to diagnose.

Verification:

```bash
PYTHONPATH=src pytest -q tests/test_workflow_usgs_e2e.py tests/test_orchestrate.py tests/test_parameter_registry.py tests/test_parameter_bridge.py tests/test_sensitivity_screen.py tests/test_cli_workflow.py
```

Result: 29 passed.

## Phase 1 Effective Claim Tier Applied

Date: 2026-05-13

The workflow now separates the contract/policy allowance from the highest tier
supported by the completed evidence.

Implemented behavior:

1. `evidence_summary.json` records:
   - `claim_tier`: the allowed tier after contract policy checks;
   - `effective_claim_tier`: the defensible tier after runtime evidence checks.
2. `effective_claim_tier` is downgraded unless the evidence includes:
   - fresh engine output,
   - benchmark lock provenance,
   - passing physical gates,
   - passing research metric thresholds,
   - successful calibration evidence.
3. `scripts/run_objective_10basin.py` reports `effective_claim_tier`, not
   policy allowance, in the 10-basin table.
4. Tests now assert that accepted research requests with incomplete or blocked
   evidence are not reported as research-grade outcomes.

Verification:

```bash
PYTHONPATH=src pytest -q tests/test_script_policy.py tests/test_workflow_usgs_e2e.py tests/test_locked_benchmark.py tests/test_calibration_real_engine.py tests/test_orchestrate.py tests/test_parameter_registry.py tests/test_parameter_bridge.py tests/test_sensitivity_screen.py tests/test_cli_workflow.py
```

Result: 55 passed.

## Phase 1 Empty-Basin Build Smoke Applied

Date: 2026-05-13

The canonical workflow was exercised against a real empty output directory for
USGS `01654000`.

Implemented behavior:

1. Added package-owned `swatplus_builder.gis.nldi_fallback` so the full-build
   path no longer fails on a missing boundary-cascade module.
2. Fixed `build_full_model()` so `USGS_ID` is set before importing the example
   builder. This prevents import-time globals such as `EXPECTED_AREA_KM2` and
   logger names from using the default station.
3. Classified provider DNS failures as
   `external_data_provider_unreachable`.
4. Classified missing flow-accumulation artifacts as
   `full_model_build_topology_failed`.
5. Fixed WhiteboxTools execution so the binary runs from a writable temp
   directory and expected raster outputs are verified.
6. Added constant-soil HRU recovery and Fiona-safe vector dtype coercion.
7. Repaired single-day GridMET provider gaps while preserving larger-gap
   failures.
8. With network/data-provider access, the smoke now completes:
   - NLDI boundary acquisition,
   - 3DEP DEM acquisition,
   - NLCD acquisition,
   - WhiteboxTools delineation,
   - gNATSGO mukey raster,
   - HRU overlay,
   - GisTables and soils,
   - GridMET weather,
   - SWAT+ Editor operations,
   - SWAT+ engine execution.

Current evidence status:

`swat workflow run` no longer blocks in the empty-directory smoke. The
evidence bundle records `blocker_class=null` and
`effective_claim_tier=exploratory`. The tier remains exploratory because this
smoke uses a deliberately short 2010-01-01 to 2010-01-10 diagnostic window
with no calibration and failed physical gates:
`baseline_nse=-11.945303709619012`,
`baseline_kge=-2.430756226602486`, `pbias=223.17774031627923`.

Verification:

```bash
PYTHONPATH=src pytest -q tests/test_weather_gridmet.py tests/test_gis_hru.py tests/test_full_build.py tests/test_nldi_fallback.py tests/test_script_policy.py tests/test_workflow_usgs_e2e.py tests/test_locked_benchmark.py tests/test_calibration_real_engine.py tests/test_orchestrate.py tests/test_parameter_registry.py tests/test_parameter_bridge.py tests/test_sensitivity_screen.py tests/test_cli_workflow.py tests/test_gis_snap_max_acc.py
PYTHONPATH=src python -m swatplus_builder.cli workflow run --usgs-id 01654000 --model-family full --start 2010-01-01 --end 2010-01-10 --warmup-years 3 --claim-tier diagnostic --no-calibrate --out-dir demo_runs/workflow/empty_basin_smoke_01654000_network --json
```

Result: focused suite passed with one skipped live GridMET test; smoke
completed with `success=true`, `blocker_class=null`,
`physical_gates_status=failed`, and `effective_claim_tier=exploratory`.

## Phase 1 Volume-Bias Diagnostics Applied

Date: 2026-05-13

The canonical workflow now creates a blocker-specific report when physical
gates include `VOLUME_BIAS`.

Implemented behavior:

1. `src/swatplus_builder/output/volume_diagnostics.py` synthesizes:
   - locked alignment observed/simulated volume,
   - `physical_gates.json` basin water-balance fields,
   - detailed outlet provenance when available.
2. `swat workflow run` writes:
   - `reports/volume_bias_diagnostics.json`
   - `reports/volume_bias_diagnostics.md`
3. `evidence_summary.json` records:
   - `values.volume_bias_diagnostics_path`
   - `values.volume_bias_diagnostics_md`
   - `values.volume_bias_primary_issue`
4. The report flags likely contributors without relaxing claim gates:
   - simulated volume excess/deficit,
   - high surface-runoff partition,
   - high basin water-yield fraction,
   - outlet terminal-count/provenance review conditions.
5. The report now retains source-backed alternatives and probe order for:
   - curve-number and landuse/soil mapping review (`CN2`),
   - developed-land and urban curve-number assumptions,
   - PET/ET partition controls (`PET_CO`, `ESCO`, `EPCO`),
   - subsurface partition controls after soil provenance is defensible
     (`LATQ_CO`, `PERCO`, `ALPHA_BF`, `RCHG_DP`),
   - outlet-selection and terminal-inventory review.

Verification:

```bash
PYTHONPATH=src pytest -q tests/test_volume_diagnostics.py tests/test_workflow_usgs_e2e.py tests/test_water_balance_gate.py
```

Result: 9 passed.

## Phase 1 Outlet Provenance Reason Fix Applied

Date: 2026-05-13

Outlet auto-selection provenance now records whether a non-terminal requested
outlet was upgraded in a single-terminal or multi-terminal topology.

Implemented behavior:

1. `evaluate_run()` keeps
   `requested_outlet_non_terminal_single_terminal` only when exactly one
   terminal outlet exists.
2. Multi-terminal non-terminal upgrades are now labeled
   `requested_outlet_non_terminal_largest_terminal_flow`.
3. Regression coverage prevents future evidence bundles from pairing a
   `single_terminal` reason with `terminal_outlet_count > 1`.

Verification:

```bash
PYTHONPATH=src pytest -q tests/test_output_eval.py tests/test_volume_diagnostics.py tests/test_workflow_usgs_e2e.py
```

Result: 18 passed.

## Validation Report Evidence Schema Applied

Date: 2026-05-13

The objective basin runner still delegates execution to `run_usgs_workflow`,
but its report schema now carries the full canonical evidence chain.

Implemented behavior:

1. `scripts/run_objective_10basin.py` uses `summarize_evidence()` to build
   rows from `evidence_summary.json`.
2. Each row records:
   - build/engine/warmup/calibration status,
   - `physical_gates`,
   - KGE/NSE/PBIAS,
   - `effective_claim_tier`,
   - `gates_passed` and `gates_failed`,
   - `physical_condition_codes` and `physical_dominant_blocker`,
   - build failure messages from `run_config.json`,
   - `volume_bias_primary_issue`,
   - sensitivity-context flags/classes,
   - evidence/provenance artifact paths.
3. The script writes:
   - `docs/OBJECTIVE_BASIN_VALIDATION_REPORT.md`
   - `docs/objective_basin_validation_report.json`

This is report infrastructure, not a completed suite run. The 10-basin
validation deliverable remains incomplete until the canonical suite is run
against all listed basins and the resulting evidence is inspected.

Verification:

```bash
PYTHONPATH=src pytest -q tests/test_script_policy.py
```

Result: 3 passed.

## Objective Basin Validation Run Executed

Date: 2026-05-13

The canonical objective validation suite was run with provider access:

```bash
SWATPLUS_EXE=bin/swatplus_exe PYTHONPATH=src python scripts/run_objective_10basin.py
```

The script exited with code 0 and wrote:

- `docs/OBJECTIVE_BASIN_VALIDATION_REPORT.md`
- `docs/objective_basin_validation_report.json`
- `demo_runs/objective_10basin/<usgs_id>/evidence_summary.json`

Result summary:

- rows: 11
- research-grade outcomes: 0
- build and engine success with physical-gate demotion: 4 basins
- package build or build-time engine blockers: 7 basins

Successful engine runs were not research-grade:

| Basin | Physical gate result | KGE | NSE | PBIAS | Volume diagnostic |
|---|---|---:|---:|---:|---|
| `01547700` | `BELOW_RESEARCH_SKILL` | 0.105 | 0.166 | -27.0 | n/a |
| `01654000` | `VOLUME_BIAS`, `NEGATIVE_SKILL` | -0.081 | -0.408 | 78.3 | `simulated_volume_excess` |
| `01491000` | `ET_DOMINATED`, `MASS_IMBALANCE`, `VOLUME_BIAS`, `NEGATIVE_SKILL` | 0.123 | -0.892 | 40.8 | `simulated_volume_excess` |
| `01493500` | `ET_DOMINATED`, `VOLUME_BIAS`, `NEGATIVE_SKILL` | -0.107 | -0.036 | -62.9 | `simulated_volume_deficit` |

Build-blocked basins were classified from `run_config.json`:

| Basin | Blocker class | Build message |
|---|---|---|
| `02129000` | `full_model_build_failed` | Soil realism gate failed: 100% fallback soils. |
| `03349000` | `full_model_build_failed` | `'NoneType' object has no attribute 'repaired'` |
| `01013500` | `full_model_build_failed` | `'NoneType' object has no attribute 'repaired'` |
| `03351500` | `engine_run_failed_during_build` | SWAT+ engine exited 151. |
| `03353000` | `full_model_build_failed` | `'NoneType' object has no attribute 'repaired'` |
| `12031000` | `engine_run_failed_during_build` | SWAT+ engine exited 151. |
| `09504500` | `full_model_build_failed` | Missing module `swatplus_builder.soil.soilgrids`. |

Shutdown caveat:

The process printed a `sys.excepthook` shutdown message after writing the
aggregate report, but the captured stream did not include a traceback body and
the process return code was 0. This should be tracked as a cleanup/noisy-exit
issue; it does not upgrade any scientific claim.

2026-05-16 update: JSON mode now redirects workflow-internal stdout and stderr
to non-closing, `/dev/null`-backed text sinks while the workflow runs, then
advertises run-local `logs/json_shutdown_stdout.log` and
`logs/json_shutdown_stderr.log` paths in the final JSON payload. Real CLI
processes redirect stdout/stderr to those files after the final JSON is
flushed, preserving machine-readable stdout if third-party libraries write
during interpreter shutdown. Regression tests cover retained stdout/stderr
streams, binary buffer writes, and process-owned stream redirection; the fast
JSON smoke exits with valid stdout JSON and empty stderr. A future long
calibrated run is still required before closing the long-run shutdown caveat.

Audit conclusion:

The multi-basin validation deliverable is now executed and auditable, but the
production objective is not complete. The canonical path correctly refuses
research-grade claims: the prior canonical suite predated the volume-bias
repair precheck and still reports no research-grade basins; several basins that
reach engine execution fail physical or routing gates, and build-blocked basins
still expose package-owned blockers before calibration can be considered.

## Post-Validation Build Blocker Hardening

Date: 2026-05-13

The suite exposed two engineering-quality blockers that prevented precise
scientific classification for several basins. These were addressed without
weakening any research-grade gate.

Implemented behavior:

1. `src/swatplus_builder/gis/overlay_repair.py` now returns a typed
   `OverlayRepairReport` instead of `None`.
   - Current status is intentionally conservative:
     `repaired=false`,
     `reason=categorical_overlay_repair_not_implemented`.
   - Low-HRU coverage basins should now fail as HRU overlay realism blockers,
     not as `'NoneType' object has no attribute 'repaired'`.
2. `src/swatplus_builder/soil/soilgrids.py` now exists as the optional
   SoilGrids v2.0 coarse fallback module.
   - Live provider access requires `SWATPLUS_ENABLE_SOILGRIDS_LIVE=1`.
   - Returned profiles are marked `source=soilgrids_v2_coarse`.
   - `examples/build_real_basin.py` treats any SoilGrids recovery as degraded
     provenance with `pct_fallback_soils=1.0`, preserving the soil realism gate
     for research runs.
3. `src/swatplus_builder/workflows/full_build.py` now classifies:
   - `hru_overlay_realism_failed`
   - `soil_realism_gate_failed`
   - `engine_hyd_connect_failed_during_build`

Verification:

```bash
PYTHONPATH=src pytest -q tests/test_overlay_repair.py tests/test_soilgrids.py tests/test_full_build.py tests/test_script_policy.py tests/test_workflow_usgs_e2e.py tests/test_orchestrate.py
git diff --check
```

Result: 17 passed; diff check passed.

The existing 11-row validation report was not rewritten from hypothetical
post-fix outcomes. It remains the evidence from the completed suite run.

Focused post-hardening validation:

```bash
PYTHONPATH=src SWATPLUS_EXE=bin/swatplus_exe python -m swatplus_builder.cli workflow run --usgs-id 03349000 --model-family full --start 2010-01-01 --end 2019-12-31 --warmup-years 3 --claim-tier research_grade --contract-status accepted --accepted-by policy --calibrate --out-dir demo_runs/post_hardening_03349000_network --json
```

Result:

- `success=false`
- `effective_claim_tier=exploratory`
- `blocker_class=hru_overlay_realism_failed`
- build message:
  `coverage_ratio=5.13%, required>=90.00% (n_hrus=2, n_subbasins=39);
  overlay_repair_reason=categorical_overlay_repair_not_implemented`
- no calibration attempt; physical gates not run because build was blocked.

This confirms the former `None.repaired` crash for `03349000` is now a precise
HRU overlay realism blocker. It does not improve basin skill or support a
research-grade claim.

Runner safety note:

`scripts/run_objective_10basin.py` now has explicit argument parsing.
`--help` exits without launching workflows, and `--summarize-existing` can
regenerate reports from existing evidence. This was added after a local
`--help` invocation exposed that the previous script ignored arguments and
started the full suite.

Hyd-connect blocker localization:

The build-time engine-151 failure in `03351500` was reproduced from the
prepared `TxtInOut`. The converter D1-D4 checks passed, so the failure was not
the earlier `file.cio` chandeg-slot defect. Inspection of `rout_unit.def`
showed duplicate negative SDC elements; for example, two routing units pointed
at `-17`. A temporary copy with each routing unit using its own negative SDC
element completed the SWAT+ engine run with exit code 0.

Package fix:

- `src/swatplus_builder/full_mode/routing_fixes.py` now writes the negative
  element in `rout_unit.def` from the routing unit's own id, not from the
  downstream target in `rout_unit.con`.
- The routing-fix validator now rejects duplicate negative SDC elements before
  engine execution.

Verification:

```bash
PYTHONPATH=src pytest -q tests/test_routing_fixes.py tests/test_topology_converter.py tests/test_full_build.py tests/test_orchestrate.py
/Users/mgalib/Library/CloudStorage/Box-Box/Obsidian/PyQSwatPlus/swatplus-builder/bin/swatplus_exe  # in temporary fixed 03351500 TxtInOut
```

Result: 27 passed; temporary fixed `03351500` engine run exited 0. This is
build-path evidence only. The basin still requires a fresh canonical workflow
rerun before any physical-gate, calibration, or claim-tier evidence can be
updated.

## Accepted 10-Year Smoke Refreshed

Date: 2026-05-13

The accepted `01654000` research-window smoke was rerun after the
volume-diagnostics and outlet-provenance fixes.

Command:

```bash
SWATPLUS_EXE=bin/swatplus_exe PYTHONPATH=src python -m swatplus_builder.cli workflow run --usgs-id 01654000 --model-family full --start 2010-01-01 --end 2019-12-31 --warmup-years 3 --claim-tier research_grade --contract-status accepted --accepted-by user --calibrate --out-dir demo_runs/workflow/canonical_cal_smoke_01654000_2010_2019 --json
```

Current evidence:

1. `evidence_summary.json` reports:
   - `success=true`
   - `blocker_class=null`
   - `effective_claim_tier=exploratory`
   - `gates_passed=["contract_policy","fresh_engine_output","benchmark_lock"]`
   - `gates_failed=["physical_gates","calibration_verification"]`
2. `physical_gates.json` reports:
   - `condition_codes=["VOLUME_BIAS","NEGATIVE_SKILL"]`
   - `dominant_blocker=VOLUME_BIAS`
   - `PBIAS=78.26934844366399`
3. `reports/volume_bias_diagnostics.json` reports:
   - `primary_issue=simulated_volume_excess`
   - `sim_to_obs_volume_ratio=1.7826934844366402`
   - `surface_runoff_to_precip=0.7189413925921952`
   - `wateryld_to_precip=0.7203711277308276`
   - `hru_cn_distribution_extreme`
   - `hru_fraction_cn_ge_95=0.8048780487804879`
   - `cn_p90=98.833`
   - `urban_landuse_dominates_runoff_response`
   - `landuse_raster.urban_fraction=0.7890114644170452`
   - `urban_curve_number_fixed_high`
   - `urban_assumptions.urban_hru_fraction=0.8048780487804879`
   - `urban_assumptions.hru_weighted_frac_imp=0.3675757575757576`
   - `urban_assumptions.hru_weighted_urb_cn=98.0`
4. Outlet provenance now reports the multi-terminal auto-upgrade explicitly:
   - `requested_outlet_gis_id=1`
   - `selected_outlet_gis_id=8`
   - `outlet_selection_reason=requested_outlet_non_terminal_largest_terminal_flow`
   - `terminal_outlet_count=4`
5. The parameter screen now records basin-context applicability:
   - global `CN2.activity_class=active`
   - `CN2.basin_context.effective_activity_class=active`
   - `values.sensitivity_screen_context_flags=["cn2_runtime_cn_table_scope_required"]`
   - `values.sensitivity_screen_effective_activity_classes={"CN2":"active"}`
6. `calibration_provenance.json` now carries the same blocker chain:
   - `provenance.volume_bias_diagnostics_path`
   - `provenance.volume_bias_primary_issue=simulated_volume_excess`
   - `provenance.volume_bias_diagnostic_flags`
   - `provenance.sensitivity_screen_effective_activity_classes={"CN2":"active"}`

The canonical path no longer treats urban-dominated CN2 as non-actionable.
Follow-up evidence showed that generated full-mode runtime CN uses
`landuse.lum:cn2` to select rows in `cntable.lum`; therefore the active
urban runoff lever is the referenced `cntable.lum` `urban` row. The bridge also
writes referenced `urban.urb:urb_cn` rows for provenance consistency, but claim
evidence must be judged from fresh SWAT+ output, not from static file edits.

Follow-up locked calibration rerun:

- Sensitivity retained all eligible parameters: `CN2`, `PERCO`, `LATQ_CO`,
  and `ESCO`.
- Volume bias was repaired: `PBIAS` improved from `78.269%` to `-0.491%`.
- Skill improved but remains below research threshold: `NSE` improved from
  `-0.4066` to `0.0158`; `KGE` improved from `-0.0809` to `0.0524`.
- Locked final routed-flow closure now passes on the promoted calibrated
  `TxtInOut`: selected terminal outlet `8`, closure ratio `1.0124`.
- Hydrograph artifacts are written under
  `calibration/hydrograph_comparison/`.

Result: the run remains `effective_claim_tier=exploratory` because the final
physical gate reports `BELOW_RESEARCH_SKILL`, not because of volume bias,
stale objective outputs, or routed-flow closure.

## 03351500 Post Engine-Compat Merge Check

Date: 2026-05-13

The suggested faster path, merging `phase-3L.8-engine-compat`, was checked.
The worktree was already on `phase-3L.8-engine-compat` and local `HEAD` matched
`origin/phase-3L.8-engine-compat` at `aaa6caf`; the merge command returned
`Already up to date.`

Local hardening added after that branch state:

- Removed a stale `swatplus_builder.gis.nldi` import in
  `examples/build_real_basin.py`; the function now imports the implemented
  `swatplus_builder.gis.nldi_fallback.fetch_basin_boundary_cascade`.
- Added bounded retry around `pygridmet.get_bycoords` in
  `src/swatplus_builder/weather/gridmet.py`.
- Classified Planetary Computer STAC timeouts as
  `external_data_provider_unreachable` in the full-build wrapper.

Focused rerun:

```bash
PYTHONPATH=src SWATPLUS_EXE=bin/swatplus_exe python -m swatplus_builder.cli workflow run --usgs-id 03351500 --model-family full --start 2010-01-01 --end 2019-12-31 --warmup-years 3 --claim-tier research_grade --contract-status accepted --accepted-by policy --calibrate --out-dir demo_runs/post_hardening_03351500_network --json
```

Observed result:

- NLDI boundary succeeded.
- DEM and NLCD acquisition succeeded.
- Delineation succeeded with 33 subbasins, 34 channel segments, and about
  413.8 km2.
- Build blocked at `fetch_mukey_raster` after four Planetary Computer STAC
  timeout attempts.
- No engine execution, physical gates, or calibration evidence was produced.

Interpretation: the previous `03351500` hyd-connect engine crash remains fixed
at the writer level, but the fresh canonical run is now blocked earlier by an
external soil raster provider timeout. This is not research-grade evidence and
does not support a basin claim.

## Provider Fallback Policy: gNATSGO Raster

Date: 2026-05-13

Repeated `03351500` failures at Planetary Computer `gnatsgo-rasters` STAC
search were not rerun blindly. The researched alternatives were:

1. Bound PySTAC result volume with `max_items` and page `limit`.
2. Set an explicit PySTAC client timeout.
3. Use the Planetary Computer collection GeoParquet item snapshot for local
   spatial filtering when access/signing is available.
4. Use direct state item lookup if collection item ids are confirmed.
5. Use USDA NRCS Soil Data Access spatial mukey functions as a standards-based
   fallback.

Implemented:

- `src/swatplus_builder/gis/soil.py` now sends bounded STAC search parameters,
  sets a client timeout, retries transient STAC failures, and treats missing
  `mukey` assets as schema drift.
- `src/swatplus_builder/gis/soil.py` now mosaics every intersecting gNATSGO
  mukey asset before polygon clipping. This prevents state/tile-edge basins
  from being silently reduced to one partial raster and then misclassified as
  diagnostic constant-soil fallback runs.
- `src/swatplus_builder/soil/sda.py` implements
  `fetch_sda_mukeys_for_geometry()` through
  `SDA_Get_Mukey_from_intersection_with_WktWgs84`.
- `examples/build_real_basin.py` now falls back from a failed or empty
  gNATSGO raster to a representative SDA spatial mukey with degraded
  provenance. This allows diagnostic builds to proceed while still blocking
  research-grade soil provenance because spatial soil heterogeneity is not
  preserved.
- Partial gNATSGO rasters are handled separately from empty rasters. If HRU
  coverage remains below `SWATPLUS_MIN_HRU_COVERAGE_RATIO` after bounded
  overlay repair, the builder chooses the dominant valid mukey from the partial
  raster as a constant representative, rebuilds HRUs, and marks
  `soil_provenance_mode=diagnostic_partial_gnatsgo_constant`. This keeps the
  run diagnostic-only; the soil realism gate still blocks research-grade
  claims unless authoritative spatial soil coverage is supplied.
- The canonical workflow now scopes diagnostic fallback environment overrides
  to package-owned builds and imports `metadata.json` soil provenance into
  `run_config.json`/`evidence_summary.json`. The `soil_fidelity` gate is listed
  in `gates_failed` for degraded soil runs and prevents `effective_claim_tier`
  from reaching `research_grade`.

External references used:

- PySTAC client documents `max_items` and `limit`; by default, `max_items=None`
  can iterate all matching items and `limit` controls page size.
- USDA SDA documents `SDA_Get_Mukey_from_intersection_with_WktWgs84`, which
  returns mukeys intersecting a WGS84 WKT geometry, and describes SDA as a
  service for real-time ad hoc area soil requests.

Verification:

```bash
PYTHONPATH=src pytest -q tests/test_gis_soil.py tests/test_soil_sda.py tests/test_full_build.py
```

Result: 33 passed.

2026-05-16 focused verification after the mosaic change:

```bash
PYTHONPATH=src pytest -q tests/test_gis_soil.py tests/test_gis_hru.py tests/test_full_build.py
python -m py_compile src/swatplus_builder/gis/soil.py tests/test_gis_soil.py
```

Result: 65 passed; py_compile passed.

## 03351500 Canonical Rerun Reached Physical Gates

Date: 2026-05-13

After provider fallback hardening, `03351500` was rerun through the canonical
workflow:

```bash
PYTHONPATH=src SWATPLUS_EXE=bin/swatplus_exe python -m swatplus_builder.cli workflow run --usgs-id 03351500 --model-family full --start 2010-01-01 --end 2019-12-31 --warmup-years 3 --claim-tier research_grade --contract-status accepted --accepted-by policy --calibrate --out-dir demo_runs/post_hardening_03351500_network --json
```

Build evidence:

- `success=true`
- `blocker_class=null`
- fresh SWAT+ engine execution succeeded with `engine_returncode=0`
- gNATSGO raster fetched: `unique_mukeys=149`,
  `soil_overlay_source=gnatsgo_raster`
- GridMET fetched for 25 stations from 31 subbasins
- requested outlet GIS 1 was auto-upgraded to terminal outlet GIS 23

Claim evidence:

- `effective_claim_tier=exploratory`
- `physical_gates_status=failed`
- condition codes:
  - `ET_DOMINATED`
  - `VOLUME_BIAS`
  - `BELOW_RESEARCH_SKILL`
- `dominant_blocker=VOLUME_BIAS`
- metrics:
  - NSE `0.0474`
  - KGE `0.2695`
  - PBIAS `-39.85`
- `volume_bias_primary_issue=simulated_volume_deficit`
- `calibration_status=blocked_by_physical_gates`
- `calibration_attempted=false`

Interpretation:

The previous `03351500` hyd-connect build blocker is fixed in the canonical
path. The basin still does not support diagnostic or research-grade claims
because physical and routed-flow gates fail. Calibration remains correctly
blocked until routing closure is fixed; volume-bias-only cases may now attempt
the locked volume repair phase, but final claims still require locked calibrated
gates.

## PET_CO Governance Correction

Date: 2026-05-13

The `03351500` physical gate originally emitted an out-of-range recommendation
to reduce `PET_CO` to `0.3-0.6`. Web review against SWAT+ documentation showed
that `hydrology.hyd` defines `pet_co` as a linear PET adjustment factor with
default `1.0` and documented range `0.8-1.2`. The SWAT+ calibration table uses
`petco` for the PET process with total limits `0.8-1.2`.

Correction:

- `src/swatplus_builder/full_mode/parameter_bridge.py` now rejects PET_CO
  outside `0.8-1.2`.
- `src/swatplus_builder/params/registry.py` uses PET_CO range `0.8-1.2`.
- `docs/CALIBRATION_PARAMETER_REGISTRY.md` and
  `docs/FULL_MODE_PARAMETER_BRIDGE_3L12.md` now match the governed range.
- `src/swatplus_builder/full_mode/water_balance_gate.py` no longer recommends
  out-of-range PET_CO values; it directs ET-dominated cases to diagnose
  PET_CO/ESCO/EPCO, soil water, weather, and management drivers within
  documented SWAT+ ranges.

This does not change the existing `03351500` evidence bundle. It fixes future
guidance so the agent does not apply undocumented PET corrections while trying
to clear ET-dominated physical gates.

## ET-Dominated Volume-Deficit Diagnostics

Date: 2026-05-13

The refreshed `03351500` report now separates simulated volume deficit from
the hydrologic partition symptoms behind it:

- `simulated_volume_deficit`
- `et_partition_high`
- `basin_water_yield_fraction_low`
- `soil_evaporation_dominates_et`
- `subsurface_partition_low`
- `outlet_provenance_needs_review`

The next-action guidance is constrained to documented SWAT+ ranges. It directs
future work to governed PET_CO `0.8-1.2`, ESCO/EPCO `0.01-1.0`, and
PERCO/LATQ_CO/aquifer-control screening through the parameter bridge followed
by locked engine reruns. This keeps the research-grade path from repeating the
previous out-of-range PET_CO recommendation while still giving a concrete
diagnostic path for ET-dominated, low-yield baselines.

The parameter registry now also uses the documented SWAT+ `hydrology.hyd`
ranges for ESCO and EPCO (`0.01-1.0`), matching the full-mode bridge and the
calibration registry document. Registry validation rejects `0.0` for both
parameters.

The same governance pass aligned the remaining full-mode bridge/search bounds:
CN2 now uses `35-98` in both registry and bridge, SURLAG uses the documented
`parameters.bsn` `surq_lag` range `1-24`, and ALPHA_BF uses the bridge-enforced
positive range `0.001-1.0` in both registry and docs.

The standalone sensitivity-screen helper now also uses
`FULL_MODE_PARAMETER_GOVERNANCE` for parameter-list fallback screens, so the
canonical workflow and helper API emit the same full-mode default activity
classes and evidence fields.

Runtime claim governance now treats sensitivity as an explicit research-grade
gate. A governance-default parameter screen is useful audit evidence, but it
does not authorize `research_grade`; `effective_claim_tier` requires
`sensitivity_screen_basis=basin_specific` plus at least one active, weak, or
limited basin-sensitive calibration parameter.

The locked calibration layer now provides that basin-specific screen through
`screen_parameters_against_lock()`. It uses the same fresh real-engine objective
machinery as calibration candidates, perturbs each governed eligible parameter
against the locked benchmark, writes `calibration/sensitivity_screen_locked/`,
and records the resulting activity classes in calibration provenance before
candidate calibration starts.

Candidate calibration now consumes that screen: only basin-specific
`active`, `weak`, or `limited` eligible parameters enter
`calibrate_against_lock()`. If no eligible parameter survives the screen,
calibration is blocked before parameter search and the blocker is written to
`reports/diagnostic_calibration.json`.

Locked calibration verification now records `improvement_basis` in
`verification_summary.json`. A verified rerun can be marked improved by NSE,
KGE, or both, while the final physical/skill gate still decides whether that
improvement can support a diagnostic or research-grade claim. This prevents the
canonical path from discarding KGE-only improvements that are otherwise allowed
by the project research-grade gate policy.

When locked calibration succeeds, workflow evidence now promotes verified
rerun metrics into canonical `values.metrics`, preserving the original baseline
under `values.baseline_metrics` and recording deltas under
`values.calibration_delta_metrics`. Claim gates and objective-suite summaries
therefore evaluate the promoted locked calibrated artifact, not temporary
candidate metrics or the pre-calibration baseline.

The objective-suite report now preserves that evidence by writing final metrics,
baseline metrics, calibration deltas, sensitivity basis, and sensitivity
activity classes to the machine-readable report, and by showing calibration
deltas plus sensitivity basis in the Markdown table.

The research metric gate now enforces the stated NSE/KGE exception literally:
negative NSE can be accepted with KGE >= 0.40 only when
`timing_limitation_documented` or `timing_limitation_basis` is present in the
workflow evidence. Otherwise the metric gate blocks `research_grade`.

## Runtime Routing-Flow Gate

Date: 2026-05-13

The canonical workflow now treats routed terminal flow as explicit claim
evidence, not an optional side diagnostic.

- `swat workflow run` writes `routing_flow_gates.json` from the existing
  `trace_mass_balance()` mass-conservation trace.
- The gate requires land-generated water to reach terminal channel output.
  Failures such as `fail_hru_to_channel`, `fail_channel_entry`,
  `fail_outlet_selection`, `fail_lte_transfer_scale`, and insufficient routing
  data block diagnostic calibration and research-grade claims.
- Terminal-outlet `fail_mass_closure` is retained as a research-grade blocker,
  but it is classified as a warning for diagnostic calibration when outlet and
  channel flow are otherwise present. This avoids treating SWAT+ basin water
  yield/channel-output semantic mismatch as a reason to skip a useful locked
  calibration attempt, while preserving the mismatch in claim evidence.
- Calibration is blocked before parameter search when routing-flow gates report
  hard calibration-blocking defects, even if the basin water-balance gates pass.
- `evidence_summary.json` now records `routing_flow` in `gates_passed` or
  `gates_failed`, and `allowed_claims`/`blocked_claims` include a
  `routing_flow_gate_*` claim.

This closes the runtime governance gap behind the policy that surface
runoff/routing must be nonzero unless physically justified. A successful build
and solver return code are no longer enough to enter calibration or promote a
research-grade claim unless routed terminal flow is also evidenced.

The locked calibration layer now repeats that routing check on the promoted
verified artifact. `run_diagnostic_calibration()` writes
`final_routing_flow_gates` beside `final_physical_gates` in calibration
provenance. Calibration verification may complete with a final
`fail_mass_closure` warning, but research-grade promotion still requires final
routing flow to pass on `calibration/locked_calibrated_TxtInOut`. The mass
trace reader accepts a
standalone `TxtInOut` so verification outputs do not need to be wrapped in a
synthetic full project tree just to prove routed terminal closure.

The objective-suite reporter now also preserves routing-flow evidence. Its
machine-readable rows include `routing_flow_gates`,
`routing_flow_closure_status`, and `routing_flow_gates_path`, and the Markdown
table shows a Routing column. This keeps the 10-basin validation report aligned
with the runtime claim gates.

The mass trace parser now handles the SWAT+ text-output quirks observed during
the canonical objective-suite rerun without weakening the generic output
reader. `basin_wb_yr.txt` and `lsunit_wb_yr.txt` can omit trailing blank/text
bookkeeping fields such as `mgt_ops`, while `ru_yr.txt` includes string columns
such as `name` and `type`; the mass-trace path now applies narrow relaxed
readers only for those optional diagnostic inputs. Real-basin rechecks now
produce scientific routing statuses instead of parser `not_run` failures:
`01491000` and `01547700` fail mass closure, while `01654000` passes terminal
flow closure.

## Weather Provider Fallback

Date: 2026-05-13

The real-basin builder now has a second real gridded weather source when
GridMET is unavailable. This addresses provider-unreachable failures without
switching to synthetic forcing or weakening claim gates.

- `src/swatplus_builder/weather/daymet.py` converts ORNL Daymet point data to
  the existing `WeatherBundle` interface for precipitation, temperature,
  relative humidity, and solar radiation.
- Daymet wind speed is intentionally unsupported because the Daymet source
  product does not provide wind. Runs using the fallback record
  `weather_variables` so downstream evidence makes the missing wind forcing
  explicit.
- `examples/build_real_basin.py` now tries distributed GridMET points,
  representative GridMET points, then representative Daymet points when the
  GridMET provider remains unreachable. Metadata records `weather_source`,
  `station_selection`, and `provider_fallback_reason`.
- The Daymet adapter uses the same bounded isolated-day repair pattern as
  GridMET and fails loudly on schema drift or partial date ranges.

Verification:

```bash
PYTHONPATH=src pytest -q tests/test_weather_daymet.py tests/test_weather_gridmet.py
PYTHONPATH=src python -m py_compile src/swatplus_builder/weather/daymet.py src/swatplus_builder/weather/__init__.py examples/build_real_basin.py tests/test_weather_daymet.py
```

This is an engineering/data-access hardening step only. A Daymet-backed run
still must pass the normal fresh-output, routing, physical, sensitivity,
calibration, and metric gates before any diagnostic or research-grade claim is
allowed.

Live `01013500` rechecks after this hardening no longer have an
external-provider blocker. GridMET was reachable in those runs, so Daymet was
not exercised, but the basin now has complete build/engine evidence:

- `build=pass`, `engine=pass`, `routing_flow_gates=passed`,
  `routing_flow_closure_status=pass`.
- A wetland-aware mass-closure fix now avoids double-counting `wet_oflo` as
  net basin water-yield loss. The fresh `01013500` rerun no longer reports
  `MASS_IMBALANCE`.
- `01013500` now reaches basin-specific sensitivity screening, attempted
  locked calibration, calibration provenance, and hydrograph comparison
  artifacts.
- It remains `exploratory` because final locked calibration is worse than the
  baseline (`NSE=-0.183`, `KGE=0.390`, `PBIAS=-3.4`) and soil fidelity remains
  degraded (`diagnostic_partial_gnatsgo_constant`, `pct_fallback_soils=1.0`).

The objective-suite report now points `01013500` at
`demo_runs/wetland_massfix_01013500_2010_2019/evidence_summary.json`; the
current compliance audit therefore records `NEGATIVE_SKILL` instead of the
previous provider or mass-accounting blockers.
