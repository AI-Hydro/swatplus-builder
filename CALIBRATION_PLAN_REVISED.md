# Calibration Integration Plan — Revised

**Supersedes:** Phase 3C of `ROADMAP.md` (sections 3C.1–3C.7)
**Date:** April 2026
**Status:** Proposed — pending review
**Key change vs prior plan:** Adopt `pySWATPlus` as the calibration engine rather than building a parallel SpotPy-based stack.

---

## 1. Why this revision

An investigation of available SWAT / SWAT+ calibration tooling changed the recommendation materially. The prior plan (Phase 3C in `ROADMAP.md`) proposed building a SpotPy-based calibration wrapper plus a neural surrogate from scratch. That plan predated a proper survey of the ecosystem. Doing so now would be duplicate engineering against active, official tooling.

### Landscape survey (April 2026)

| Tool | Target model | Language | Maintained | License | Fit for `swatplus-builder` |
|------|--------------|----------|------------|---------|---------------------------|
| **pySWATPlus** (swat-model org) | **SWAT+** native | Python | Actively (v1.3.0, Nov 2025) | GPL-3.0 | **Adopt as engine** |
| SWATdoctR (Plunge et al. 2024, EMS) | SWAT+ | R | Actively | Open | Port diagnostic *concepts* |
| SWATtunR (OPTAIN project) | SWAT+ | R | Actively | Open | Reference for soft/hard calibration concepts |
| R-SWAT (Nguyen et al. 2022, EMS) | SWAT & SWAT+ | R + Shiny | Actively | Open | UX/algorithm reference |
| Ercan NSGA-II tool (2016, EMS) | **SWAT 2012 only** | Python 2-era | **Inactive ~9 years** | Research | Historical reference only — not adoptable |
| Py-SWAT-U-NSGA-III (2023, EMS) | SWAT | Python + pymoo | Research | Academic | Methodology reference only |

### What pySWATPlus already provides

- `TxtinoutReader`: reads/writes SWAT+ input folder, modifies parameters via `calibration.cal`
- `PerformanceMetrics`: NSE, KGE, MSE, RMSE, MARE
- `SensitivityAnalyzer`: Sobol global sensitivity analysis via SALib
- `Calibration`: single-objective (GA, DE) and multi-objective (NSGA-II) via pymoo
- Parallel execution via `ProcessPoolExecutor`
- Generation-by-generation history persistence
- High-level configuration API: `parameters`, `extract_data`, `observe_data`, `objective_config`

This is essentially the feature set the prior plan would have taken 4–5 weeks to build. It is maintained by the SWAT+ project itself, which means tracking the SWAT+ engine's evolution is someone else's problem.

### What pySWATPlus does NOT provide

This is where `swatplus-builder` still has work to do:

1. **Integration with our build pipeline.** pySWATPlus assumes an existing `TxtInOut` folder; `swatplus-builder` is the thing that *produces* that folder. Gluing them is our responsibility.
2. **Artifact schema and run provenance.** pySWATPlus persists calibration history per its own conventions; our artifact store is a superset that captures lineage, content hashes, and metadata across the full pipeline (build + run + calibrate).
3. **Parameter registry with physical meaning.** pySWATPlus accepts parameters as dicts with `name`, `change_type`, bounds. Our registry adds physical meaning, tier, scope, and diagnostic heuristics that agents need.
4. **Diagnostic layer.** SWATdoctR's key contribution — structured diagnosis of model-setup issues — has no Python equivalent. We port the concepts (not the R code).
5. **Agent-native interface.** pySWATPlus is a Python library for researchers; MCP tool contracts for autonomous agents are our responsibility.
6. **Surrogate-accelerated search.** pySWATPlus runs the real engine every evaluation. For agent-driven autoresearch with expensive engine runs, a neural surrogate is still the right architectural addition — but it sits *on top* of pySWATPlus, not in place of it.

---

## 2. Revised Phase 3C — Calibration via `pySWATPlus`

Replaces `ROADMAP.md` Phase 3C.1 through 3C.7. Total revised effort: **3–4 weeks** (down from 4–5 weeks, because we are not reimplementing the optimizer stack).

### 3C.1 — Dependency Integration (3 days)

- [ ] Add `pySWATPlus >= 1.3.0` to `pyproject.toml` dependencies
- [ ] Add `pymoo`, `SALib` as transitive-but-verified dependencies (document versions)
- [ ] Write a `DECISIONS.md` entry: "Adopt pySWATPlus as calibration engine" — rationale, alternatives rejected, consequences
- [ ] Write a minimal integration test: build a basin → run calibration with 2 parameters × 2 generations × population 4 → assert artifacts written
- [ ] Document GPL-3.0 implications (pySWATPlus is GPL-3.0; `swatplus-builder` license choice needs a decision — currently needs to be confirmed in DECISIONS.md)

### 3C.2 — Parameter Registry (4–5 days)

pySWATPlus takes parameters as dicts. We layer a registry on top that the rest of the system (agents, diagnostics, UI) can reason about.

- [ ] Define `Parameter` dataclass with: `name`, `file`, `scope`, `range`, `default`, `units`, `description`, `change_type` (`absval`/`pctchg`/`abschg`), `tier` (1=most sensitive), `physical_meaning` (short prose)
- [ ] Populate the registry with the standard set (see `ROADMAP.md` Appendix B — unchanged, still correct)
- [ ] Add conversion helpers: `Parameter.to_pyswatplus_dict()`, `Parameter.to_pyswatplus_bounds_dict()`
- [ ] Expose: `from swatplus_builder.params import registry`
- [ ] Registry doubles as documentation: each parameter has enough metadata that an agent or human can reason about *why* to calibrate it

### 3C.3 — Build → Calibrate Bridge (4–5 days)

`swatplus-builder` produces `TxtInOut`; pySWATPlus consumes it. The bridge makes the handoff seamless.

- [ ] `swatplus_builder.calibration.Calibrator` class wraps `pySWATPlus.Calibration`
- [ ] Inputs: our `BasinSpec`, list of `Parameter` objects (or parameter names resolved via registry), objective config, algorithm
- [ ] Handles path management: points pySWATPlus at our built `TxtInOut`, receives its output back into our artifact store
- [ ] Persists: every calibration run writes a calibration artifact under `runs/calibrations/<hash>/` containing config, per-generation history, best parameters, Pareto front (if multi-objective), convergence plot
- [ ] Each evaluation within the calibration also writes a standard run artifact (content-hashed so duplicates are skipped)
- [ ] CLI: `swat calibrate --basin <id> --algo nsga2 --n-gen 50 --pop-size 32 --objectives nse,kge`
- [ ] Algorithms supported via pySWATPlus passthrough: `GA`, `DE` (single-objective), `NSGA2` (multi-objective)

### 3C.4 — Sensitivity Analysis Bridge (2 days)

pySWATPlus also provides `SensitivityAnalyzer` via SALib. Expose it.

- [ ] `swatplus_builder.sensitivity.SensitivityAnalyzer` thin wrapper
- [ ] CLI: `swat sensitivity --basin <id> --parameters cn2,esco,perco,alpha_bf --n-samples 512`
- [ ] Outputs first-order and total-order Sobol indices, ranked
- [ ] Used to prune parameter sets *before* calibration — a sensitivity pass in 2 hours can save 2 days of calibration compute

### 3C.5 — Diagnostic Layer (5–6 days)

This is the novel contribution on top of pySWATPlus. Ports the *concepts* from SWATdoctR (Plunge, Schürz, et al. 2024, EMS) without porting the R code. The value is giving agents and humans structured hypotheses for why a calibration is failing.

- [ ] `swatplus_builder.diagnostics.diagnose(run_artifact) → List[Diagnosis]`
- [ ] Each `Diagnosis` has: `symptom` (observable fact), `hypothesis` (suspected cause), `evidence` (supporting metric), `suggested_parameters` (from registry), `suggested_action` (concrete next step)
- [ ] Initial rule set (explicit, not learned):
  - Peak lag > 1 day → suspect SURLAG
  - Baseflow too low / flashy → suspect ALPHA_BF, GW_DELAY, GWQMN
  - Total volume bias > 15% → suspect CN2, ET params (ESCO, EPCO)
  - Snowmelt timing off → suspect SFTMP, SMTMP
  - Flat hydrograph with positive observed flow → check outlet selection, routing mode
  - High PBIAS on water yield but acceptable NSE → suspect ET balance
  - Recession too fast → suspect ALPHA_BF
  - Recession too slow → suspect GW_DELAY
- [ ] Each rule cites its source (SWATdoctR protocol, SWAT+ documentation, or internal empirical)
- [ ] Output is agent-consumable (typed structure) and human-readable (Markdown report option)

### 3C.6 — Calibration Workflow Patterns (2–3 days)

Opinionated higher-level patterns. Most users shouldn't need to think about "which algorithm, how many generations" — we provide defaults that work.

- [ ] `swat calibrate --preset quick` → DE, 10 generations, pop 16, single objective (NSE). Hours of runtime. Good for iteration.
- [ ] `swat calibrate --preset standard` → NSGA-II, 30 generations, pop 32, multi-objective (NSE + KGE + PBIAS). Day of runtime. Publication-grade starting point.
- [ ] `swat calibrate --preset thorough` → NSGA-II, 80 generations, pop 64. Multi-day. For final reporting.
- [ ] All presets can be overridden; they just set sensible defaults.

### 3C.7 — Exit criteria for revised Phase 3C

- `swat calibrate` operational using pySWATPlus as engine, via all three presets
- Multi-objective calibration produces Pareto fronts persisted in artifact store
- Parameter registry complete and wired to pySWATPlus input format
- Diagnostic layer produces actionable output for at least 8 failure modes
- Sensitivity analysis runnable via `swat sensitivity`
- Every calibration evaluation cached via content-hash (re-running identical configs hits cache)
- At least one curated basin fully calibrated end-to-end with benchmark-report-quality output

---

## 3. Surrogate-Accelerated Search — Deferred to Phase 3D+

The prior plan put the neural surrogate in Phase 3C. **Move it to Phase 3D as part of the agent loop**, not a calibration primitive. Rationale:

1. **For human-driven calibration, pySWATPlus is sufficient.** Humans calibrate once per project; engine cost is acceptable.
2. **The surrogate's value is agent-driven autoresearch**, where *thousands* of parameter evaluations happen across experiments. That's a Phase 3D problem.
3. **The surrogate needs training data.** Phase 3C calibrations populate the artifact store, providing the training corpus for free. The surrogate becomes feasible precisely *after* 3C, not during.
4. **Decoupling reduces risk.** If surrogate accuracy is poor, Phase 3C still ships. If surrogate work slips, Phase 3C still ships.

This is reflected in the revised `ROADMAP.md` sequencing (see §4 below).

---

## 4. Revised Phase 3D — Agent Loop (updated)

The main change: the surrogate work moves here. Target duration increases from 3–4 weeks to **4–5 weeks**.

### New subsections in 3D (added)

- [ ] **3D.X Neural surrogate training** — small MLP trained on artifact-store-derived `(config, parameters) → metrics` pairs. Input: flattened parameter vector + basin attributes. Output: daily discharge summary statistics. 2–4 hidden layers, ensemble of 5 for uncertainty.
- [ ] **3D.Y Surrogate-aware proposal routing** — when an agent proposes parameters, surrogate predicts; if ensemble variance low, use surrogate result; if high, invoke pySWATPlus.Calibration single-shot via our Calibrator and update surrogate with the new observation.
- [ ] **3D.Z Surrogate evaluation harness** — hold-out testing: surrogate NSE vs engine NSE on unseen basins. Target: median agreement > 0.8 before surrogate is used in the agent loop.

### Unchanged in 3D

- MCP tool surface (8 tools)
- SKILL.md
- Diagnostic heuristics (now largely implemented in 3C.5)
- Autoresearch loop

---

## 5. What we are NOT doing (and why)

These options were considered and rejected.

### Not adopting Ercan's NSGA-II tool

- Built for SWAT 2012, calls `swat2012_627` executable, wired to SWAT-CUP
- Not maintained since ~2017
- NSGA-II capability is already in pySWATPlus via pymoo
- **Status: historical reference only. Cite in related work if writing a paper.**

### Not porting SWATdoctR directly

- R package; porting to Python would be a 2–3 month effort for a feature already adequately covered (diagnostics + calibration) by combining pySWATPlus + our diagnostic layer
- Its *conceptual contribution* — structured model-setup verification — is captured in 3C.5 diagnostic rules
- **Status: cite the 2024 EMS paper; credit the conceptual inspiration; port rules, not code.**

### Not building a SpotPy wrapper

- SpotPy is excellent for generic calibration
- It has no SWAT+ awareness; we would have to build a SWAT+ adapter ourselves, which is exactly what pySWATPlus already is
- **Status: rejected in favor of pySWATPlus.**

### Not building a from-scratch optimizer

- pymoo (accessed via pySWATPlus) covers GA, DE, NSGA-II, U-NSGA-III, and more
- Writing our own would be worse, slower, and unsupported
- **Status: not applicable.**

### Not implementing SWAT-CUP SUFI-2 independently

- SUFI-2 is proprietary to SWAT-CUP; it's not in the open ecosystem
- DDS (dynamically dimensioned search) would be a close open alternative, but NSGA-II covers the multi-objective use case better and is already available via pySWATPlus
- **Status: deferred indefinitely; add to BACKLOG.md if a user requests it.**

---

## 6. Migration from current `ROADMAP.md`

Apply these edits to `ROADMAP.md`:

1. Replace sections 3C.1–3C.7 with the content of this document's §2
2. Update §4 Phase Overview table: Phase 3C duration from "4–5 weeks" to "3–4 weeks"; Phase 3D from "3–4 weeks" to "4–5 weeks"
3. Update §12 Milestones: M4 wording from "Classical calibration shipped" to "Calibration shipped (pySWATPlus-based)"; M5 from "Neural surrogate operational" stays but shifts one milestone later
4. Update Appendix B: add `change_type` field to Parameter dataclass (required for pySWATPlus compatibility)
5. Add new top-level dependency note in §2.1: `pySWATPlus >= 1.3.0` is a primary dependency
6. Update `DECISIONS.md` with three entries: (a) adopt pySWATPlus as calibration engine, (b) defer surrogate to Phase 3D, (c) GPL-3.0 license implications

---

## 7. Licensing note — requires human decision

pySWATPlus is GPL-3.0. Adopting it as a dependency has licensing implications for `swatplus-builder`:

- If `swatplus-builder` is intended to be GPL-3.0 or compatible → no issue
- If `swatplus-builder` is intended to be permissively licensed (MIT, Apache-2.0, BSD) → GPL-3.0 dependency may force `swatplus-builder` to also be GPL-3.0, depending on linkage interpretation. This requires a conscious licensing decision before Phase 3C starts.

**Action:** Before beginning 3C.1, confirm `swatplus-builder`'s target license in `DECISIONS.md`. If permissive licensing is preferred, the alternatives are (a) accept GPL-3.0 for `swatplus-builder`, (b) shell out to pySWATPlus as an external process rather than importing (looser coupling, likely acceptable), or (c) consult legal/licensing expert.

---

## 8. Summary

| Question | Answer |
|----------|--------|
| Build SpotPy wrapper from scratch? | **No.** pySWATPlus covers it. |
| Port Ercan's NSGA-II tool? | **No.** SWAT 2012 only, 9 years stale, functionality duplicated in pySWATPlus. |
| Port SWATdoctR? | **No — port the concepts, not the code.** Our diagnostic layer (3C.5) captures the value in Python. |
| Neural surrogate / differentiable approach? | **Yes, but in Phase 3D, not 3C.** Surrogate value is agent autoresearch, not single-project calibration. |
| What's our novel contribution if pySWATPlus does calibration? | **The end-to-end agent-native pipeline.** pySWATPlus calibrates an existing `TxtInOut`; we produce the `TxtInOut` from GIS primitives, run the full loop, diagnose failures with structured rules, surface everything through typed MCP tools. That whole integration is the product. |

**End of document.**
