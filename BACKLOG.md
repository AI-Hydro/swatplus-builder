# Backlog (Append-Only)

Use this file for discovered work that is explicitly deferred.

Format:

- `[YYYY-MM-DD] [Title]`
  - `Source: [Phase X discovery | user feedback | bug triage]`
  - `Description: ...`
  - `Why deferred: [out of scope | blocked on X | low priority]`
  - `Rough effort: [S | M | L]`

---

- [2026-04-23] Migrate legacy historical logs from `docs/` to root canonical docs
  - Source: Phase 3A discovery
  - Description: Port major historical milestones from `docs/PROGRESS.md` and `docs/DECISIONS.md` into root-level tracked `PROGRESS.md`/`DECISIONS.md` while preserving chronology.
  - Why deferred: out of scope for immediate Phase 3A.1 CI regression gate work.
  - Rough effort: M

- [2026-05-08] Fix 03351500 LSU-to-channel topology foreign-key failure
  - Source: 16-basin experiment-suite bug triage
  - Description: `03351500` failed with an LSU-to-channel foreign-key violation during topology/table construction. Investigate the channel/LSU writer handoff and add a regression fixture for dangling channel references.
  - DONE [2026-05-08]: Did not reproduce after STAC/mosaic changes; rerun reached calibrated NSE improvement (`-4.47` to `+0.03`).
  - Rough effort: M

- [2026-05-08] Add arid/western soil fallback provider
  - Source: 16-basin experiment-suite bug triage
  - Description: `09504500` and `13185000` fetched gNATSGO mukeys but SDA returned no usable soil profiles. Add a documented POLARIS or SoilGrids fallback with explicit degraded provenance.
  - DONE [2026-05-09]: SoilGrids v2.0 coarse fallback implemented in `src/swatplus_builder/soil/soilgrids.py` and wired into `build_real_basin.py` as Tier 2. Verified E2E on `09504500`: 6 profiles recovered, `soil_provenance_mode="soilgrids_coarse"`, engine runs.
  - Rough effort: L

- [2026-05-08] Add direct WBD/HUC boundary fallback for NLDI-missing gauges
  - Source: 16-basin experiment-suite bug triage
  - Description: `03352162` exhausted current NLDI-based cascade tiers. Add a direct WBD/HUC containing-gauge lookup that does not depend on NLDI navigation.
  - DONE [2026-05-08]: direct WBD HUC12 + NWIS coordinate + `resolve_usgs_outlet` fallback reaches delineation. Follow-up HUC12-vs-DEM validation mismatch resolved [2026-05-09].
  - Rough effort: M

- [2026-05-08] Rework Stage 3 calibration expansion trigger
  - Source: 16-basin experiment-suite calibration evidence
  - Description: Stage 3 degraded the objective on most calibrated basins while Stage 2 was usually best. Make Stage 3 opt-in based on stronger diagnostics, gentler parameter ranges, or early stopping.
  - DONE [2026-05-08]: Stage 3 now skips when Stage 2 NSE is below the configured floor (`0.10`); `03349000` skips while `01654000` still runs.
  - Rough effort: M

- [2026-05-08] Resolve HUC12-vs-DEM mismatch after direct WBD fallback
  - Source: 16-basin experiment-suite bug triage
  - Description: `03352162` now reaches delineation through direct WBD HUC12 fallback, but the administrative HUC12 polygon can fail validation against the DEM-derived watershed. Promote DEM-first delineation as the primary recovery when HUC12 fails validation.
  - DONE [2026-05-09]: `build_real_basin.py` now skips area/IoU validation when boundary source is non-authoritative, treating DEM-derived watershed as ground truth. NLDI fallback tests pass (5/5).
  - Rough effort: M

- [2026-05-08] Reconcile 03353000 and 03351500 experiment identifiers
  - Source: 16-basin experiment-suite evidence audit
  - Description: The scorecard reports `03353000` as calibration-ready while the failure notes mention `03351500` topology failure. Confirm whether these are two separate runs or a transcription mismatch, then update `docs/USGS_EXPERIMENT_SUITE.csv` and result artifacts.
  - Why deferred: requires artifact inspection from the experiment run.
  - Rough effort: S

- [2026-05-10] Implement LTE bridge support for registry-only parameters (GWQMN, REVAPMN, GW_REVAP, SOL_K, SOL_AWC, CH_N2, CH_K2, ESCO, EPCO)
  - Source: Phase 3H calibration maturity
  - Description: 9 parameters exist in the registry but the LTE bridge (`apply_parameters_to_lte_txtinout`) does not write them. Implement file/table/field injection for each so they can move from `not_tested` to testable.
  - Why deferred: requires SWAT+ LTE file format audit and safe field mapping per parameter.
  - Rough effort: L

- [2026-05-10] Implement nearest-subbasin geometry fallback for channels with sub_id=NaN
  - Source: 10-basin validation suite — 03351500 intermittent topology FK failure
  - Description: WhiteboxTools intermittently emits channels with `sub_id=nan` after vectorization. Current `_emit_channels` correctly drops them (fail-loud), but when the dropped channel is in the LSU channel mapping, it causes FK failures. A nearest-subbasin geometry fallback would preserve topology instead of dropping.
  - Why deferred: fail-loud is the correct posture for now; this is a delineation improvement, not a pipeline defect. Documented in PLAYBOOK §3.
  - Rough effort: M

- [2026-05-09] Run pilot overclaiming experiment (5 tasks × 2 conditions × 5 reps)
  - Source: docs/OVERCLAIMING_EXPERIMENT_PROTOCOL.md
  - Description: Execute the 50-run pilot to estimate effect size of contract-governed execution on agent overclaiming behavior. Requires 2 agent models (frontier + weaker), task prompts, human rating.
  - Why deferred: requires external agent runs and human rater — not an infrastructure task.
  - Rough effort: L
  - Source: 10-basin validation suite — 03351500 intermittent topology FK failure
  - Description: WhiteboxTools intermittently emits channels with `sub_id=nan` after vectorization. Current `_emit_channels` correctly drops them (fail-loud), but when the dropped channel is in the LSU channel mapping, it causes FK failures. A nearest-subbasin geometry fallback would preserve topology instead of dropping.
  - Why deferred: fail-loud is the correct posture for now; this is a delineation improvement, not a pipeline defect. Documented in PLAYBOOK §3.
  - Rough effort: M

- [2026-05-09] Improve 03352162 delineation for small WBD HUC12 polygons
  - Source: 10-basin validation suite
  - Description: NLDI cascade recovers boundary for 03352162 via WBD HUC12 (43 km²), but DEM delineation produces only 1 subbasin with 20 channels — `avg_subbasin_area_too_small`. Needs lower stream threshold or adaptive percent-area policy to produce viable topology from small administrative boundaries.
  - Why deferred: requires threshold policy tuning — not a fallback-path bug.
  - Rough effort: M

- [2026-05-09] Clean 13185000 re-run with current SoilGrids code
  - Source: 10-basin validation suite
  - Description: Earlier run proved SoilGrids fallback works on 13185000 (NSE=-4.884), but current artifacts were cleared during testing. Re-run to confirm the path with current code.
  - Why deferred: artifact management — the path was already proven.
  - Rough effort: S

- [2026-05-09] Prototype `swat workflow negotiate`
  - Source: Scientific Agent Workflow Contract design discussion
  - Description: Implement a deterministic intent-to-contract command that returns known inputs, missing inputs, assumptions, gates, expected artifacts, allowed claims, and blocked claims before executing a USGS workflow.
  - Why deferred: design documented first; implementation should be done as a focused agent-native workflow sprint.
  - Rough effort: M

- [2026-05-09] Formalize scientific claim governance v0.1
  - Source: Agent governance publishable roadmap critique
  - Description: Define the formal claim tuple, claim statuses, claim tiers, acceptance policy (`contract_status`, `accepted_by`, `claim_tier`), and gate-to-claim transition rules.
  - Why deferred: next methods sprint; needed before overclaiming experiment scoring.
  - Rough effort: M

- [2026-05-09] Pre-register overclaiming experiment protocol
  - Source: Agent governance publishable roadmap critique
  - Description: Write the empirical protocol for raw-agent vs contract-governed-agent comparison, including tasks, agents, replicates, scoring rubric, hypotheses, exclusion rules, and synthesis plan.
  - Why deferred: next methods sprint; should precede pilot execution.
  - Rough effort: M

- [2026-05-09] Add minimal RO-Crate evidence packaging command
  - Source: Agent governance publishable roadmap critique
  - Description: Implement `swat workflow package-evidence` to export a run directory as a minimal RO-Crate-compatible research object with `ro-crate-metadata.json`, `manifest.json`, and `README.md`.
  - Why deferred: next methods sprint; high-credibility bridge to existing reproducibility standards.
  - Rough effort: M

- [2026-05-09] Run overclaiming pilot before threat model and taxonomy
  - Source: Agent governance publishable roadmap critique
  - Description: Run a pilot with 5 ill-posed tasks, 2 agents, raw and contract-governed conditions, and at least 5 replicates per task-condition pair. Use results to ground threat model and failure taxonomy.
  - Why deferred: requires claim governance and protocol first.
  - Rough effort: L

- [2026-05-10] Add full SWAT+ mode support
  - Source: Phase 3K.7-3L.1 — 01547700 classified as full_swatplus_required
  - Feasibility: docs/FULL_SWATPLUS_MODE_FEASIBILITY.md
  - Phase 3L.2: Build + run full-mode 01547700 (no calibration) — DONE
    - Build successful, engine rc=0, channel flow all zeros
    - ET=760mm (73% ET/P) — physically realistic out of the box
    - surq_gen=0mm — CN2 defaults need investigation
  - Phase 3L.3: Routing audit — DONE
    - Routing chain verified correct (HRU→RU→channel→outlet)
    - Blocker: surq_gen=0 + water held in soil/groundwater
  - Phase 3L.4: Full-mode water balance investigation — DONE
    - Routing chain was correct; zero channel flow was not a routing defect.
    - Full SWAT+ computed CN2 from soil hydrologic group + landuse CN table (`frsd`/`wood_f`, A/B soils), producing CN values around 36-60, realistic ET (~760mm, 73% ET/P), and near-zero surface runoff.
    - Interpretation: full mode is physically coherent; observed storm peaks likely require calibrated full-mode CN/hydrology parameters rather than routing repair.
  - Phase 3L.5: Full-mode parameter bridge (deferred)
    - apply_parameters_to_full_swat_txtinout()
    - Registry updates for full-mode file targets
    - Estimate: L
  - Priority: high — unlocks calibration on flashy basins
  - Rough effort: XL (total)

- [2026-05-10] Add CN provenance and runoff-activation diagnostics for full SWAT+ mode
  - Source: Phase 3L.4 — full-mode zero flow initially looked like routing failure but was physically low runoff from CN table defaults.
  - Description: Add diagnostics/logs that report curve-number provenance (landuse, soil hydrologic group, CN table values), surface/lateral/baseflow partition, ET/P, and hydrology activation status for full-mode runs. The report should distinguish `routing_disconnected` from `runoff_generation_low_but_physical`.
  - Why deferred: next diagnostics hardening task; not required to prove the Phase 3L.4 finding but important for agent friendliness.
  - Rough effort: M

- [2026-05-10] DONE — Add RCHG_DP to LTE bridge and calibration pipeline
  - Source: Phase 3K.3 — discovered as primary volume control on 01547700
  - Implemented Phase 3K.4: registry entry, LTE bridge, smoke verified
  - Range [0.0, 0.8], default 0.01, tier 1
  - Bridge: apply_parameters_to_lte_txtinout() → hru-lte.hru rchg_dp

- [2026-05-10] Implement setup/water-balance verification command
  - Source: Phase 3J result + SWATdoctR/SWATtunR reference review
  - Description: Add a first-class `swat calibration-verify-setup` (or equivalent workflow stage) that writes `setup_verification.json`, `setup_verification.md`, and `water_balance_components.csv` before calibration and after best-solution verification. Include P, PET, ET, ET/P, runoff partitioning, percolation, water yield, PBIAS, BFI ratio, and mass-closure status.
  - Why deferred: next focused calibration-hardening sprint; Phase 3J result is documented but not yet generalized as a reusable command.
  - Rough effort: M

- [2026-05-10] Add FDC-segment metrics and parameter-identifiability artifacts to calibration evidence
  - Source: SWATtunR hard-calibration workflow review
  - Description: Add high/mid/low-flow FDC segment metrics, dotty-data tables, and best-performing parameter range summaries to calibration outputs so NSE/KGE cannot hide flow-regime failures.
  - Why deferred: depends on stabilizing the verification-first calibration command and current constrained calibration artifact format.
  - Rough effort: M

- [2026-05-10] Repeat Phase 3J constrained calibration on 01547700 and 4-6 calibration-ready basins
  - Source: Phase 3J completion report
  - Description: Apply the two-phase protocol (`volume gate -> timing optimization`) to `01547700` first, then a small calibration-ready basin set. Produce a claim matrix by basin: exploratory, diagnostic, research_grade.
  - Why deferred: requires setup-verification artifacts and FDC metrics to avoid repeating NSE-only optimization mistakes.
  - Rough effort: L

## Phase 3L.6 — Full-mode QSWAT routing parity

Status: OPEN

Problem: `01547700_full` can generate surface runoff and non-zero routing-unit output after CN2 activation, but channel flow remains zero. A QSWAT+ source audit shows the likely gap is incomplete full-mode GIS routing semantics, not gross topology.

Tasks:

- Add a full-mode routing parity audit command.
- Align `HydType` with QSWAT+ values, especially `rhg` and `nil`.
- [2026-05-10] Phase 3L.8: Engine/editor compatibility audit — DONE
  - Verdict: `reference_runs_with_builder_engine` → `builder_full_routing_generation_incomplete`
  - Evidence: Tordera reference produces 32,213 non-zero channel flow on builder engine
  - Phase 3L.7 hypothesis (engine version mismatch) SUPERSEDED
  - Fix direction confirmed: writer-side post-processing, not engine bundling

- [2026-05-10] Phase 3L.9: Implement rout_unit→cha routing in builder post-processing (NEXT)
  - Source: Phase 3L.8 — engine can route, builder output is incomplete
  - Approach: Post-process editor-generated rout_unit files to add working cha routing
  - Reference format provides template; need to map to cha (not sdc)
  - Estimate: M

- Phase 3L.8 removed from NEXT (completed). Phase 3L.9 added to NEXT.
- [2026-05-10] Phase 3L.8: Direct HRU→channel routing for full SWAT+ (NEXT)
  - Source: Phase 3L.7 — rout_unit→channel blocked by engine version

- Detect and block flattened full-mode routing graphs such as direct `HRU tot -> CH` and `LSU tot -> CH` without `sur`/`lat`/`rhg` rows.
- Generate full-mode HRU -> LSU, LSU -> CH/AQU, AQU/DAQ -> downstream routing rows following QSWAT+ semantics.
- Re-run `01547700_full` with activated CN2 and verify RU water reaches `channel_day` and the strict outlet.
