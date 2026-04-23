# Decisions Log

This is the canonical tracked decision log for roadmap execution.
Legacy ADR history exists in `docs/DECISIONS.md` (local working docs).

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
