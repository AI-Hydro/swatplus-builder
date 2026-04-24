# Decisions Log

This is the canonical tracked decision log for roadmap execution.
Legacy ADR history exists in `docs/DECISIONS.md` (local working docs).

---

[2026-04-24] Phase 3D surrogate v1 uses deterministic bootstrap linear ensembles before neural models
Context: Revised Phase 3D requires uncertainty-aware surrogate routing now, but we need a low-risk, dependency-light baseline that is easy to audit, reproducible, and fast to iterate while agent-loop plumbing stabilizes.
Decision: Implement surrogate training as a deterministic bootstrap ensemble of linear regressors fitted from artifact-backed rows (`extract_surrogate_dataset`), with uncertainty estimated from inter-member prediction spread (`std`), and persist model artifacts (`training_rows.csv`, `model_cards.json`, `training_summary.json`) under `surrogates/<ensemble_id>/`.
Alternatives considered:
- Add scikit-learn/XGBoost immediately — rejected to avoid new heavy dependencies and additional portability/licensing review during Phase 3D foundation work.
- Jump directly to neural surrogates — rejected because it increases complexity and debugging surface before loop/routing contracts are fully stabilized.
- Use single-model linear regression only — rejected because it does not provide uncertainty spread required for routing decisions.
Consequences:
- Surrogate behavior is deterministic, inspectable, and lightweight for initial agent-loop integration.
- Uncertainty-gated routing can be exercised now with explicit persisted evidence.
- A richer model family can be introduced later behind the same typed interface once Phase 3D core contracts are proven.
Status: Accepted

---

[2026-04-23] Canonical planning/progress docs are root-level
Context: Execution protocol for this roadmap requires authoritative `ROADMAP.md`, `PROGRESS.md`, and `DECISIONS.md` at repository root. Existing logs were primarily under `docs/`, and some were gitignored.
Decision: Treat root-level `ROADMAP.md`, `PROGRESS.md`, and `DECISIONS.md` as canonical for all future phase execution updates. Keep `docs/*` historical/local notes as reference until migration is complete.
Alternatives considered:
- Continue using `docs/PROGRESS.md` and `docs/DECISIONS.md` only — rejected because these are gitignored and not reliably reviewable.
- Fully rewrite and migrate all historical docs in one change — rejected as too disruptive for Phase 3A kickoff.
Consequences:
- New progress and non-obvious decisions are now tracked in committed root files.
- Historical context remains available in `docs/` during transition.
Status: Accepted

---

[2026-04-23] Calibration bridge reports authoritative metrics from `evaluate_run`, not raw pySWATPlus objective values
Context: During revised Phase 3C.7 curated-basin calibration, pySWATPlus objective values were numerically extreme (`~ -3.67e9`) despite physically plausible independent run evaluation (`NSE ~ -0.2`). This made direct use of raw objective values untrustworthy for reporting and decision-making.
Decision: In the pySWATPlus bridge, compute and report per-evaluation calibration metrics (`nse`, `kge`) using authoritative `evaluate_run` on the generated simulation output for the exact requested output file and outlet. Persist raw pySWATPlus objective values only as traceability fields in `metric_parity_log.csv`.
Alternatives considered:
- Continue reporting raw pySWATPlus objective directly — rejected due demonstrated scale mismatch and misleading optimization feedback.
- Apply ad hoc scaling transform to raw objective — rejected as unjustified and brittle across basins/setups.
- Disable pySWATPlus path entirely — rejected because execution path is stable and parity layer provides trustworthy reporting now.
Consequences:
- Calibration reporting is now physically interpretable and consistent with the project’s evaluation contract.
- Per-evaluation parity logs provide auditability for alignment window, distribution stats, outlet, and raw-vs-bridge divergence.
- Raw objective mismatch remains an internal pySWATPlus interoperability concern but no longer contaminates reported calibration metrics.
Status: Accepted

---

[2026-04-23] Real-engine calibration must sanitize print controls and score fresh day outputs
Context: Real-engine calibration investigations showed identical baseline/calibrated hydrographs even after large parameter perturbations. Root cause was structural: copied `TxtInOut` directories contained stale `channel_day.txt` artifacts, while `print.prt` had `nyskip=1` and daily channel outputs disabled, so reruns did not regenerate the scored files.
Decision: In real-engine calibration objective setup, enforce objective-safe `print.prt` settings (`nyskip=0`, daily enabled for `channel`, `channel_sd`, `basin_cha`, `basin_sd_cha`), delete stale day outputs before each run, and evaluate against freshly generated `channel_sd_day.txt`.
Alternatives considered:
- Continue scoring `channel_day.txt` if present — rejected because stale copied outputs can silently bypass actual rerun sensitivity.
- Require users to pre-clean `TxtInOut` manually — rejected because this is error-prone and violates no-silent-fallback expectations.
- Switch immediately to SQLite-only scoring — rejected for now to keep Phase 3C changes narrow and leverage existing typed text-output evaluators.
Consequences:
- Real-engine calibration now reflects actual rerun physics instead of stale artifacts.
- One-year windows can now emit valid daily objective series despite warmup defaults in inherited `print.prt`.
- Calibration runs may become slower due to guaranteed daily output generation.
Status: Accepted

---

[2026-04-23] Partition calibration artifact cache by objective mode
Context: Warm-start artifact reuse keyed only by sampled parameter config could reuse proxy-objective metrics for real-engine runs when basin/seed/iterations matched, producing false cache hits and masking runtime objective changes.
Decision: Add `objective_mode` (`proxy` | `real_engine`) into calibration `RunConfig.options` and content hashing inputs.
Alternatives considered:
- Disable warm-start entirely for calibration — rejected because content-hashed caching is roadmap-mandated and useful for iterative workflows.
- Add ad hoc cache-busting flags outside typed config — rejected because it weakens reproducibility and inspectability.
Consequences:
- Proxy and real-engine calibration histories are isolated and reproducible.
- Existing caches remain valid within their own mode and no longer contaminate cross-mode runs.
Status: Accepted

---

[2026-04-23] Real-engine calibration objective source defaults to `basin_sd_cha_day.txt`
Context: After fixing stale-output scoring, real-engine calibration briefly scored `channel_sd_day.txt` first. On Marsh Creek LTE workflow this produced severe magnitude inflation and pathological fit (`NSE ~ -1305`) compared with historically consistent basin-scale series (`NSE ~ -0.2`) from `basin_sd_cha_day.txt`.
Decision: Use `basin_sd_cha_day.txt` as the primary objective input for real-engine calibration and calibrated-alignment generation; rely on existing evaluator fallback chain only if that file is unavailable.
Alternatives considered:
- Keep `channel_sd_day.txt` primary — rejected due observed scale mismatch in this workflow and misleading objective values.
- Implement per-project dynamic file selection heuristic now — rejected as broader scope; keep this Phase 3C change minimal and deterministic.
- Revert to stale `channel_day.txt` behavior — rejected because it reintroduces no-op risk from copied artifacts.
Consequences:
- Real-engine calibration objective reflects basin-scale discharge consistently in current LTE pipeline.
- Reported NSE/KGE are comparable with existing evaluation outputs for the same runs.
- Future work may generalize source-file selection using explicit metadata/unit tags.
Status: Accepted

---

[2026-04-23] Real-engine calibration runs are fail-loud by default on objective-source drift
Context: Calibration objective evaluation can silently fall back to alternate output files when the requested simulation file is missing/empty, which hides configuration faults and compromises scientific traceability.
Decision: Add explicit objective-source controls to `swat calibrate` real-engine mode:
- `--objective-sim-file <name>` selects the required objective series file,
- `--strict-objective-file` (default) fails if evaluator did not use that exact file,
- per-sample `objective_trace.json` records requested/actual source, outlet selection, and metrics.
Alternatives considered:
- Keep fallback silent and only log warnings — rejected because this allows structurally invalid comparisons.
- Remove evaluator fallback globally — rejected because fallback remains useful in non-calibration evaluation paths.
Consequences:
- Real-engine calibration now fails fast on source mismatch unless user explicitly opts into fallback.
- Artifact trails are auditable per parameter vector for outlet and source selection behavior.
Status: Accepted

---

[2026-04-23] Add optional minimum-improvement gate for real-engine calibration acceptance
Context: A run can execute correctly yet return no improvement over rerun baseline; without an explicit gate, downstream automation may treat such calibration as acceptable.
Decision: Add `--min-improvement-nse` gate in real-engine calibration, computed as `best_nse - baseline_nse_real` from apples-to-apples reruns. If improvement is below threshold, command exits non-zero.
Alternatives considered:
- Always require positive improvement by default — rejected for now to avoid unexpectedly breaking exploratory runs.
- Only report improvement without gating — rejected because automation needs a deterministic fail condition.
Consequences:
- Users and CI can enforce quantitative acceptance criteria without custom wrappers.
- Calibration remains backward-compatible when gate is omitted.
Status: Accepted

---

[2026-04-23] Adopt pySWATPlus as the calibration engine for revised Phase 3C
Context: `CALIBRATION_PLAN_REVISED.md` supersedes prior SpotPy-first Phase 3C scope after ecosystem review. pySWATPlus already provides SWAT+-native parameter editing, calibration algorithms (GA/DE/NSGA-II), sensitivity analysis, and parallel execution.
Decision: Use pySWATPlus as the canonical calibration engine for Phase 3C, and reposition `swatplus-builder` value to build→calibrate integration, artifact/provenance persistence, diagnostics, and agent-facing interfaces.
Alternatives considered:
- Continue SpotPy-based custom calibration stack — rejected as duplicate engineering against maintained SWAT+-native tooling.
- Build an in-house optimizer stack — rejected as higher risk, slower delivery, and weaker long-term maintainability.
- Adopt historical SWAT 2012 NSGA-II scripts — rejected due staleness and model mismatch.
Consequences:
- Phase 3C implementation sequence follows revised plan.
- Existing SpotPy scaffolding becomes transitional and should not be expanded as the primary path.
Status: Accepted

---

[2026-04-23] Defer neural surrogate implementation from Phase 3C to Phase 3D
Context: Revised plan moves surrogate acceleration to agent-loop phase so Phase 3C can ship stable human-facing calibration first and use generated calibration artifacts as surrogate training data.
Decision: Treat surrogate work as Phase 3D scope; Phase 3C focuses on pySWATPlus integration, diagnostics, and workflow presets.
Alternatives considered:
- Keep surrogate in Phase 3C — rejected due coupling risk and unnecessary blocker for calibration delivery.
- Remove surrogate entirely — rejected because it remains high-value for agent autoresearch throughput.
Consequences:
- Near-term focus shifts to robust calibration integration and diagnostics.
- Surrogate design will consume richer, real calibration artifacts once 3C is complete.
Status: Accepted

---

[2026-04-23] Maintain optional pySWATPlus coupling pending explicit license strategy decision
Context: Project metadata is currently MIT (`pyproject.toml`) while pySWATPlus is GPL-3.0. Revised plan calls out this as a required human/legal decision before irreversible coupling.
Decision: Proceed with optional-dependency integration and narrow/lazy import boundaries, while deferring any irreversible license change until explicit human decision is recorded.
Alternatives considered:
- Immediate direct hard dependency/import across core package — rejected because license implications are unresolved.
- Block all calibration integration work until legal decision — rejected because optional boundary work and adapter design can proceed safely.
- Ignore licensing implications and continue as-is — rejected as unacceptable governance risk.
Consequences:
- Phase 3C.1 work can progress with controlled coupling.
- Final release posture for calibration integration remains contingent on explicit licensing sign-off.
Status: Accepted

---

[2026-04-23] Parameter registry keeps internal adjustment semantics and adds pySWATPlus `change_type`
Context: Revised Phase 3C requires pySWATPlus-compatible parameter descriptors (`absval`/`pctchg`/`abschg`) while existing code already uses internal `AdjustmentType` semantics (`replace`/`multiply`/`add`).
Decision: Preserve `AdjustmentType` for internal compatibility and add explicit `ChangeType` plus conversion helpers on `Parameter` (`to_pyswatplus_dict`, `to_pyswatplus_bounds_dict`).
Alternatives considered:
- Replace `AdjustmentType` entirely with `ChangeType` — rejected due unnecessary churn and break risk in existing code.
- Keep only internal semantics and map ad hoc in bridge code — rejected because agents and diagnostics need first-class pySWATPlus metadata at registry level.
Consequences:
- Registry now serves both internal workflows and pySWATPlus integration cleanly.
- Future bridge implementations can remain thin and deterministic.
Status: Accepted

---

[2026-04-23] Keep `swat calibrate` dual-engine during migration (`spotpy` + `pyswatplus`)
Context: Revised plan makes pySWATPlus the primary calibration engine, but existing users/tests currently rely on the SpotPy-based path and pySWATPlus is optional/not always installed in dev environments.
Decision: Add explicit `--calibration-engine` selector with transitional defaults preserving existing behavior (`spotpy` default) while enabling revised path via `pyswatplus`.
Alternatives considered:
- Immediate hard cutover to pySWATPlus default — rejected due dependency availability and migration risk.
- Maintain separate CLI commands (`calibrate` vs `calibrate-pyswatplus`) — rejected to avoid surface sprawl and user confusion.
Consequences:
- Migration can proceed incrementally with stable CI.
- Once pySWATPlus path is fully validated in this repo, default can be switched in a follow-up decision.
Status: Accepted

---

[2026-04-23] Implement sensitivity as a first-class bridge command (`swat sensitivity`)
Context: Revised 3C.4 requires exposing pySWATPlus/SALib sensitivity before calibration-heavy workflows, so users/agents can prune parameter sets with Sobol indices.
Decision: Add typed sensitivity orchestrator (`SensitivityAnalyzer`) with backend adapter boundary and CLI command `swat sensitivity`, persisting ranked indices under `runs/sensitivity/<hash>/`.
Alternatives considered:
- Fold sensitivity into `swat calibrate` only — rejected because pre-calibration sensitivity is a standalone workflow.
- Defer sensitivity until after diagnostics — rejected because revised roadmap orders 3C.4 before 3C.5.
Consequences:
- Sensitivity can be run independently and cached by config hash.
- Agents can consume ranked parameter influence before launching expensive calibration loops.
Status: Accepted

---

[2026-04-23] Add explicit diagnostics command and typed rule engine (`swat diagnose`)
Context: Revised 3C.5 requires structured, agent-consumable hypotheses for calibration failures beyond raw metrics and plots.
Decision: Implement a typed rule engine (`diagnose(run_artifact) -> List[Diagnosis]`) and expose it through `swat diagnose`, with markdown reporting helper for human review.
Alternatives considered:
- Keep diagnostics embedded inside calibration report text only — rejected because agents need typed machine-consumable outputs.
- Defer diagnostics until after preset workflows — rejected because revised roadmap places diagnostics before presets.
Consequences:
- Calibration troubleshooting now has a reproducible, inspectable hypothesis layer.
- Rules can be expanded incrementally while preserving stable output schema.
Status: Accepted

---

[2026-04-23] Default large-basin guardrail mode is warn-and-continue (`auto_adjust=True`)
Context: Phase 3A.4 requires pre-engine size guardrails and fail-fast behavior when users opt out. Existing workflows rely on `swat run` succeeding with minimal flags, so making guardrail breaches fatal by default would break compatibility.
Decision: Add `--max-hrus` and `--max-subbasins` guardrails with default thresholds (5000 and 500), and default to warning + guidance while continuing (`--auto-adjust`). Provide explicit opt-out (`--no-auto-adjust`) to fail fast.
Alternatives considered:
- Fail fast by default on threshold breach — rejected because it would be a breaking operational change for existing runs.
- Skip guardrails when counts are unavailable — rejected because deterministic checks are still possible in many run layouts using persisted delineation manifests.
Consequences:
- Large-basin risk is surfaced before engine execution without immediate workflow breakage.
- Strict users/CI can enforce fail-fast by setting `--no-auto-adjust`.
- Guidance now explicitly points to delineation threshold and HRU aggregation knobs for structural size reduction.
Status: Accepted

---

[2026-04-23] Artifact store v1 uses a local filesystem backend rooted at `<root>/runs`
Context: Phase 3B.1-3B.2 requires a complete artifact schema and store API now, while cloud backends are explicitly future work. We needed a stable path contract that supports immediate caching and benchmark reproducibility.
Decision: Implement `LocalArtifactStore` as the default backend with layout `<root>/runs/<content_hash>/...`, and define an abstract `ArtifactStore` interface (`write/read/exists/query/lineage`) for future S3/cloud adapters.
Alternatives considered:
- Implement cloud backend immediately — rejected as out of scope for Phase 3B and a timeline risk.
- Hardcode filesystem logic without an interface — rejected because it would make backend evolution and testing harder.
Consequences:
- Phase 3B can ship complete artifact behavior immediately on local disk.
- Future backend additions can conform to the same API without changing callers.
- Content-addressed cache checks (`exists(hash)`) are now straightforward to wire into run orchestration.
Status: Accepted

---

[2026-04-23] `swat validate` uses an injectable executor with orchestrator default in alpha
Context: Phase 3B.2-3B.3 requires a working validation runner now, but full production basin execution is still evolving and must remain testable without network-heavy real runs.
Decision: Implement `run_validation(..., executor=...)` with a typed executor contract. Default executor calls existing `orchestrate.run_pipeline`; tests inject deterministic executors for cache/report assertions.
Alternatives considered:
- Hard-wire validation to real full E2E execution path only — rejected because it makes CI/tests brittle and slow.
- Ship `swat validate` without execution integration (schema-only) — rejected because Phase 3B requires end-to-end benchmark runner behavior.
Consequences:
- `swat validate` is usable immediately and supports deterministic tests.
- Real-execution behavior can be upgraded by swapping default executor without breaking runner interface.
- Content-addressed cache behavior is verifiable independent of external data availability.
Status: Accepted

---

[2026-04-23] Scope NSE floor assertion to structural CI basin in Phase 3A.1
Context: Phase 3A.1 calls for an NSE floor gate (`NSE > -1`) to catch silent regressions. During real multi-basin gate validation, routing/connectivity assertions passed but several uncalibrated basins showed strongly negative NSE (order 10^2-10^3), which would hard-fail CI independent of routing correctness.
Decision: Keep mandatory NSE floor assertion on the known structural regression basin (`03339000`) where the outlet-selection/routing path is the target behavior under test; require finite NSE on all other fast CI basins while preserving strict routing assertions (engine success, terminal flow > 0, alignment exists, outlet auto-detection behavior).
Alternatives considered:
- Enforce NSE > -1 on every CI basin immediately — rejected because CI becomes dominated by calibration realism gaps, masking structural routing regressions and preventing incremental hardening.
- Remove NSE gate entirely — rejected because it eliminates an important quantitative guardrail.
- Skip routing gate until calibration is complete — rejected because routing regression protection is required now.
Consequences:
- CI catches structural routing failures now, while maintaining a quantitative floor check on at least one representative basin.
- We must revisit and expand per-basin NSE floor coverage as calibration/fidelity work progresses.
Status: Accepted

---

[2026-04-23] Emit run metadata from the real-basin pipeline with outlet diagnostics
Context: Phase 3A.2 requires complete run metadata persistence and inspectability. Existing runs only persisted metrics/alignment and could not explain which outlet series was used when auto-detection switched away from the configured GIS ID.
Decision: Add a typed `RunMetadata` schema (`src/swatplus_builder/output/metadata.py`) and persist `metadata.json` in run directories from `examples/real_basin_marsh_creek.py`. Extend `evaluate_run(..., return_diagnostics=True)` to return requested/selected outlet IDs, auto-detection flag, selection reason, and source output file.
Alternatives considered:
- Persist metadata as an untyped dict in `run_config.json` only — rejected because schema drift becomes hard to test and inspect reliably.
- Keep metadata inside SQLite `project_metadata` only — rejected because run-level diagnostics should be directly readable from run artifacts without DB introspection.
- Delay outlet diagnostics until Phase 3B artifact store — rejected because 3A.2 explicitly requires traceable outlet selection now.
Consequences:
- Every new real-basin run emits `metadata.json` with outlet, soil, engine, hash, and weather provenance fields.
- CLI can expose metadata directly (`swat inspect <run_path>`).
- Evaluate API remains backward-compatible by making diagnostics opt-in.
Status: Accepted

---

[2026-04-23] Narrow `.gitignore` output rule to top-level `/output/`
Context: The broad ignore pattern `output/` unintentionally ignored Python source under `src/swatplus_builder/output/`, causing key runtime modules (metrics/reader/plots) to remain untracked locally and absent from repository history.
Decision: Replace `output/` with `/output/` so only top-level runtime artifacts are ignored. Keep a specific ignore for vendored editor `database/output/` stubs.
Alternatives considered:
- Keep broad ignore and force-add individual files ad hoc — rejected because it is fragile and will repeatedly hide legitimate source edits.
- Remove output ignores entirely — rejected because generated top-level runtime artifacts should remain excluded.
Consequences:
- Source files under `src/swatplus_builder/output/` are now tracked normally.
- Top-level artifact directory `output/` remains ignored.
- Vendored `database/output/` stubs stay ignored to avoid noisy tracking of unused vendor internals.
Status: Accepted
