# Agent Workflow (Implemented Behavior)

## End-to-End Flow
`negotiate -> run -> evidence`

## 1) Negotiate
Command:
`swat workflow negotiate --task "..."`

Behavior:
1. Parses USGS id and date range.
2. Parses requested claim tier.
3. Validates policy preconditions for research/publication requests:
   - requires >=10-year window.
4. Emits:
   - `workflow_contract.json`
   - `WORKFLOW_CONTRACT.md`

If policy fails, returns `status=needs_input` with `policy_issues`.

## 2) Run
Command:
`swat workflow run --usgs-id <id> --model-family full --start <YYYY-MM-DD> --end <YYYY-MM-DD> --warmup-years <N> --calibrate --claim-tier <tier> [--hru-mode dominant_only|full_overlay] [--min-hru-fraction <fraction>] [--contract <path>]`

Research-grade CLI runs can pass accepted contract metadata directly with:
`--contract-status accepted --accepted-by user` or
`--contract-status accepted --accepted-by policy`.

Research-grade land-use fidelity probes should request `--hru-mode full_overlay`
and an explicit `--min-hru-fraction`; dominant-only HRUs remain the default
first-run mode and are disclosed/gated as degraded land-use fidelity.

Behavior:
1. Enforces runtime claim policy from contract/status.
2. Executes pipeline run.
   - If no prepared `project/Scenarios/Default/TxtInOut` exists, the package
     calls its full-build handoff for `model_family=full`.
   - The canonical workflow allows explicit diagnostic-only fallback during
     package-owned builds so provider gaps or partial soil coverage can still
     produce evidence artifacts. Degraded soil provenance is carried into the
     evidence bundle and blocks `research_grade` through the `soil_fidelity`
     gate.
   - If a prepared `TxtInOut` exists after build/discovery, the pipeline
     performs a clean SWAT+ solver rerun, fetches/uses observed discharge,
     evaluates the outlet, and writes `benchmark/benchmark_lock.json`.
   - If build, provider, topology, engine, or output discovery fails, the run is
     blocked with a structured `blocker_class`; no calibration metrics are
     allowed.
3. Executes sensitivity screen artifact generation.
4. Executes phased diagnostic calibration attempt.
   - Calibration is blocked before the volume stage when routing evidence
     shows hard defects such as no land generation, no HRU-to-channel
     transfer, no channel entry, transfer-scale failure, wrong outlet, or
     insufficient routing data.
   - Terminal-outlet `fail_mass_closure` is retained as a research-grade
     blocker but may enter diagnostic calibration when outlet/channel flow is
     otherwise present. The mismatch is preserved in baseline and final
     routing evidence.
   - Selected-vs-all terminal scope is classified from package-owned routing
     evidence even when the physical blocker is low skill rather than volume
     bias. Failed or warning routing gates can therefore block
     `terminal_scope_claim` through `values.terminal_scope_blocker`; passed
     routing gates do not receive terminal-scope blockers.
   - When terminal hydrograph diagnostics are written, the workflow promotes
     the package-owned diagnostic interpretation into `values` and calibration
     provenance as `terminal_hydrograph_scope_class`,
     `terminal_hydrograph_scope_flags`,
     `terminal_hydrograph_scope_recommended_focus`, and
     `terminal_hydrograph_scope_claim_impact`. It also promotes the
     package-owned `terminal_scope_decision_request` when emitted by the
     diagnostic sidecar. These fields remain diagnostic-only and do not promote
     all-terminal or nearest-terminal metrics to claim evidence.
   - Terminal inventory traces also classify selected-vs-nearest outlet
     conflicts as `terminal_outlet_conflict_class` with flags and claim impact.
     A selected terminal that is largest-flow/largest-area but not nearest to
     the gauge requires hydrofabric or gauge outlet-authority reconciliation
     before terminal-scope claims can advance.
   - Objective-suite summaries must preserve row-level `blocker_domain` and
     `blocker_action_items` for every non-research basin. These fields are
     diagnostic governance evidence, not claim promotion evidence.
   - Objective-suite summaries must also preserve `target_hypothesis_evaluation`
     at the report root. A shortfall from the target remains `not_supported_by_current_evidence`
     unless current evidence supports the target under unchanged gates.
   - Objective-suite summaries must preserve a root-level
     `science_blocker_summary` for non-research rows whose blocker domain is
     `science`. This summary documents current skill or mass-balance
     limitations without adding them to `pipeline_improvement_plan`; it must
     retain package-owned diagnostic evidence, blocked claims,
     `claim_authority=false`, and `gate_weakening_permitted=false`.
   - Objective-suite summaries must preserve a root-level
     `pipeline_improvement_plan` for active non-science blocker domains. The
     plan is diagnostic/provenance guidance only: each per-basin item must
     retain current artifact pointers, first routing/volume probes,
     `claim_authority=false`, `temporary_metrics_allowed_as_final=false`, and
     `fresh_locked_rerun_required_before_claim=true`. Provenance items must
     expose a typed package-owned `decision_request` with
     `status=needs_input` and `accepted_by_required=user_or_policy`;
     when official authority-area and virtual-outlet evidence is available,
     that request must carry `outlet_scope_evidence` with selected-vs-all
     authority-area fractions, virtual candidate status, terminal IDs, conflict
     flags, and required-before-claim steps before recommending a virtual
     all-terminal authorization path;
     diagnostics items must expose `status=diagnostic_only` until
     source-backed evidence identifies a repairable package gap.
     Diagnostics decisions should use retained package evidence when available:
     post-aggregation process context can narrow `diagnostic_only` options to
     soil-provenance repair, high-runoff forcing/area audit, ET partition
     screening, subsurface partition screening, or post-aggregation
     water-balance diagnosis. These choices guide the next package experiment
     but do not grant claim authority.
     Post-aggregation process context must also preserve candidate explanations
     for each retained process domain, with evidence, next action, fresh locked
     rerun requirement, and claim impact. Domain labels alone are not enough
     to guide a diagnostic rerun.
     Root `pipeline_improvement_plan` diagnostic `decision_request` payloads
     must preserve those candidate explanations directly so agents can choose a
     next package-owned experiment without inventing or re-deriving the
     evidence basis.
     High-runoff forcing/area audit rows must also preserve candidate
     explanations for precipitation/area/external inflow basis, snow storage,
     aquifer release, selected-terminal scope, and model water-yield deficit,
     plus the fresh locked rerun requirement before any claim can advance.
   - Objective-suite summaries must preserve calibration phase coverage from
     `calibration_reports_locked/history.csv`: phase order, evaluation counts,
     per-phase gate-pass counts, and phase parameter coverage for every row
     with retained calibration history. This proves the staged protocol was
     exercised without using temporary candidate metrics as final evidence.
   - Terminal-scope hydrograph diagnostics must preserve
     `terminal_scope_resolution_plan`. All-terminal and nearest-terminal
     hydrographs remain diagnostic-only; a fresh locked rerun is required after
     outlet scope is made claim-authoritative before any terminal/outlet claim
     can advance.
   - Terminal inventory diagnostics must retain official USGS Site Service
     drainage-area context when available. `terminal_authority_area_check`
     compares selected-terminal and all-terminal upstream area against the
     official gauge drainage area before NLDI fallback; it is provenance
     evidence, not permission to promote all-terminal metrics.
   - If the official area supports the all-terminal footprint while the
     selected terminal remains partial, `terminal_virtual_outlet_candidate` is
     diagnostic-only. It can guide the next experiment only after explicit
     virtual outlet provenance, a fresh locked rerun, and the normal physical,
     routing, sensitivity, calibration, and metric gates.
     The package-owned `swat lock-benchmark` path supports this as a guarded
     experiment through `--virtual-all-terminal-outlet` plus a required
     `--virtual-outlet-authority`; the resulting lock records
     `outlet_scope=virtual_all_terminal`, and sensitivity, calibration, and
     verification score candidate runs with the same explicit virtual scope.
     The canonical `swat workflow run` path exposes the same guarded experiment
     flags and relocks the fresh workflow output before calibration, so scripts
     do not need to define or infer virtual-outlet science policy. Runtime
     routing evidence must then pass `virtual_outlet_scope_gate`, which requires
     documented authority, terminal GIS IDs, non-overlapping terminal topology,
     nonzero all-terminal outflow, and all-terminal routed/mass closure before
     the virtual outlet can support same-scope calibration or claims. The same
     scope is applied again to the final locked-calibrated `TxtInOut` routing
     gate, so verified calibration cannot promote a single-outlet routing check
     for a virtual all-terminal benchmark. Objective-suite summaries must
     preserve the same virtual outlet scope, policy, selected terminal GIS IDs,
     authority, and `virtual_outlet_scope_gate` payload at row level; a virtual
     row without that evidence is not auditable claim evidence.
     When `virtual_outlet_scope_gate` passes, that explicit virtual scope is the
     claim-authoritative outlet scope. Selected-terminal hydrograph diagnostics
     may still be retained as diagnostic contrast evidence, but they must not
     reintroduce `terminal_scope_blocker=outlet_scope_volume_mismatch` for the
     same virtual run.
   - If valid all-terminal aggregation still misses the hard volume gate,
     `post_aggregation_process_context` must remain diagnostic-only and drive
     process/forcing/soil follow-up. It cannot grant outlet authority or
     substitute for locked physical, routing, calibration, and metric gates.
     Future workflow runs must promote it into `evidence_summary.json` values
     and calibration provenance when the diagnostic sidecar emits it.
   - Physical gates may enter diagnostic calibration only when they pass or
     report calibration-target metric blockers (`VOLUME_BIAS`,
     `NEGATIVE_SKILL`, `BELOW_RESEARCH_SKILL`). Hard physical blockers such as
     zero surface runoff still stop calibration before parameter search.
   - If a volume-bias repair attempt proceeds, final claims use the locked
     calibrated `TxtInOut` gates, while baseline gate evidence remains in the
     evidence summary for auditability.
   - Before candidate calibration, the locked calibration layer runs a
     basin-specific sensitivity screen using fresh locked-objective
     perturbation runs. Governance-default screens are audit evidence only and
     cannot authorize `research_grade`.
   - Locked calibration then runs a staged protocol:
     `volume -> baseflow_subsurface -> peaks_timing -> kge_nse_finetune`.
     The default volume-stage probe order follows SWAT+ soft-calibration
     practice by testing ET partition controls (`PET_CO`, `ESCO`, `EPCO`)
     before surface-runoff controls (`CN3_SWF`, `CN2`) and subsurface
     partition controls (`LATQ_CO`, `PERCO`). `CN3_SWF` is diagnostic until
     the final locked rerun passes all claim gates.
     Within the volume phase, candidates in the preferred `|PBIAS| <= 15%`
     tier are ranked by KGE/NSE before residual volume closeness, so the
     workflow does not carry forward a near-zero-PBIAS candidate that destroys
     hydrograph skill.
   - Candidate history rows are tagged with phase metadata, and
     `best_solution.json` plus `calibration_provenance.json` record
     `selection_policy=staged_volume_baseflow_peaks_then_nse_kge`.
   - No candidate can be promoted unless `abs(pbias) <= 30`; KGE/NSE
     fine-tuning only ranks candidates that pass the volume gate and
     candidate calibration process gates.
   - When prior candidate physical/process-gate evidence exists, the
     `kge_nse_finetune` phase itself is blocked until at least one earlier
     volume-valid candidate has passed the calibration process gate. The
     history records `blocked_preceding_process_gate` before raising, so a
     skill-only search cannot start from a physically invalid staged result.
   - Locked verification and research-claim success are separate evidence
     states. A promoted locked `TxtInOut` can be rerun cleanly and improve over
     baseline while still leaving final physical, routing, or skill gates
     failed. In that case the workflow records
     `calibration_status=verified_diagnostic_claim_blocked`,
     `calibration_locked_verification_succeeded=true`, and
     `calibration_final_claim_gates_passed=false`; agents may cite the locked
     diagnostic verification, but must not report a calibrated model skill
     claim or `research_grade`.
   - When locked verification alignments are available, the workflow writes an
     observed/baseline-simulated/calibrated-simulated hydrograph comparison
     under `calibration/hydrograph_comparison/`.
5. Writes outlet provenance artifact.
6. Writes canonical evidence artifacts with:
   - requested tier, allowed claim tier, and effective claim tier
   - contract fields (`contract_status`, `accepted_by`)
   - gates passed/failed
   - blocker class
   - calibration status/provenance
   - terminal hydrograph scope class/flags/focus when terminal-scope
     diagnostics are available
   - build diagnostic artifact pointers for blocked build stages
   - provenance hash
   - model family
   - soil mode, soil provenance mode, and fallback-soil fraction when degraded
     soil fallback was needed
   - allowed claims and blocked claims

## 3) Evidence Expectations
A valid run directory contains at least:
1. `evidence_summary.json`
2. `EVIDENCE_SUMMARY.md`
3. `outlet_provenance.json`
4. `calibration_provenance.json`
5. `parameter_screen.json`
6. `physical_gates.json`
7. `run_manifest.json`
8. `events.jsonl`

Implementation-specific report files may also exist under `reports/`, but
agents should treat the top-level files above as the canonical evidence bundle.
When a package-owned build stage blocks, `evidence_summary.json` exposes
`values.build_diagnostic_artifacts` and `run_manifest.json` mirrors those paths
under `artifacts.build_*` so agents can inspect the machine-readable blocker
report before retrying.

Claim summaries must use `physical_gates.json`, metric thresholds, fresh-output
status, benchmark-lock provenance, sensitivity status, calibration verification,
and contract status. Metrics alone never authorize a `research_grade` claim.
Agents may report `effective_claim_tier`; `claim_tier` is only the maximum tier
allowed by contract policy.

## 4) Claim-Tier Rules
1. `research_grade`/`publication_grade` blocked unless:
   - `contract_status in {accepted, executed}`
   - `accepted_by in {user, policy}`
   - window >= 10 years
   - warmup >= 3 years
2. Short diagnostic windows (<5 years or warmup <3) are downgraded to `exploratory`.
3. `effective_claim_tier` is downgraded unless runtime evidence supports the
   higher tier. Research-grade effective claims require a fresh engine rerun
   with a non-empty simulation output artifact, an existing benchmark-lock
   artifact, selected outlet provenance, basin-specific sensitivity evidence,
   explicit high-fidelity soil provenance (`soil_mode=high_fidelity`,
   `soil_provenance_mode=gnatsgo_raster`, `pct_fallback_soils=0.0`), passing
   physical gates, passing research metric thresholds, positive locked-rerun
   calibration improvement over baseline, and successful final claim-gate
   calibration evidence. Verified locked diagnostic calibration with failed
   final claim gates is audit evidence, not research-grade evidence.
4. If NSE is negative, KGE >= 0.40 can satisfy the research metric gate only
   when the evidence explicitly documents the timing limitation.
