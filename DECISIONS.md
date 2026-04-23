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
