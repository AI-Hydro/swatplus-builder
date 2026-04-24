# `swatplus-builder` — Roadmap to v1.0

**Document version:** 1.0
**Last updated:** April 2026
**Status:** Alpha v0.4.0 → targeting v1.0 (agent-native SWAT+ MCP server)
**Scope:** Definitive AI-agent-native Python interface to SWAT+. Broader hydrological modeling ambitions live in AI-Hydro / HYDRO-ATOMS.

---

## Table of Contents

1. [Vision & Scope](#1-vision--scope)
2. [Current State](#2-current-state-v040)
3. [Guiding Principles](#3-guiding-principles)
4. [Phase Overview](#4-phase-overview)
5. [Phase 3A — Hardening](#phase-3a--hardening-3-4-weeks)
6. [Phase 3B — Artifact System & Validation Layer](#phase-3b--artifact-system--validation-layer-2-3-weeks)
7. [Phase 3C — Calibration (Two-Track)](#phase-3c--calibration-two-track-4-5-weeks)
8. [Phase 3D — Agent Loop & Autoresearch](#phase-3d--agent-loop--autoresearch-3-4-weeks)
9. [Phase 3E — Packaging & Distribution](#phase-3e--packaging--distribution-2-weeks)
10. [Phase 3F — Physical Fidelity (Parallel Track)](#phase-3f--physical-fidelity-parallel-track)
11. [Risks & Mitigations](#11-risks--mitigations)
12. [Milestones & Success Criteria](#12-milestones--success-criteria)
13. [Appendix A — Artifact Schema Specification](#appendix-a--artifact-schema-specification)
14. [Appendix B — Parameter Registry](#appendix-b--parameter-registry)
15. [Appendix C — Agent SKILL.md Structure](#appendix-c--agent-skillmd-structure)

---

## 1. Vision & Scope

### 1.1 What this package is

`swatplus-builder` is the **definitive AI-agent-native interface to SWAT+**. It produces valid SWAT+ model inputs from GIS primitives using pure-Python tooling (no QGIS, no PyQGIS, no QSWATPlus plugin at runtime), runs the engine, evaluates outputs, and exposes every step as typed tool functions callable by AI agents (via MCP) or humans (via CLI / notebooks).

### 1.2 What this package is NOT

- Not a replacement for SWAT+ itself (the Fortran engine is vendored)
- Not a general hydrological modeling framework
- Not a research vehicle for making SWAT+ itself differentiable
- Not a GIS toolkit (that is QGIS / ArcGIS)

This scope discipline is intentional. Over-scoping is the single largest risk.

### 1.3 Target users

| User | Primary interface | Primary goal |
|------|-------------------|--------------|
| Hydrology researcher | Python API / notebooks | Build & calibrate SWAT+ models reproducibly |
| AI agent (MCP-capable) | MCP tools | Autonomous SWAT+ experimentation |
| Practitioner | CLI (`swat run`, `swat calibrate`) | Standard workflows without QGIS |
| CI / regression infrastructure | Python API | Automated testing |

---

## 2. Current State (v0.4.0)

### 2.1 What works

- End-to-end automated pipeline on real data: delineation → HRU → DB → editor → engine → evaluation → plots
- Structural routing failures fixed (ID mismatches, NaN subbasin/channel issues, outlet linkage, STAC soil overlap fallback)
- Multi-basin evidence: successful 4-basin final batch and unseen-basin validation
- Hydrograph flatline issue diagnosed and fixed (auto outlet detection when configured outlet is dry)
- Regression tests for new failure classes
- Structured hypothesis/evidence logs for investigation

### 2.2 What is missing

- CI regression automation (multi-basin smoke with non-zero terminal flow assertions)
- Content-addressed caching / resume; structured run-state logs
- Large-basin scalability controls
- Soil realism signaling when fallback soils are used
- Phase 2 fidelity: HAND LSU split, waterbody subtraction, full routing / elevation-bands completeness, benchmark parity report
- Container / service packaging, docs site, notebook polish
- **Calibration layer (entirely absent)**
- **Agent-native tool contracts and SKILL.md**

### 2.3 Honest assessment

The project is structurally stable and demonstrably functional across multiple basins, but not yet production-hardened nor physically validated for all basin classes. Highest-value next moves: CI routing-regression gate → outlet metadata persistence → soil quality flags → artifact schema → calibration → agent loop.

---

## 3. Guiding Principles

These principles govern every design decision in this roadmap.

1. **Every run is an artifact.** If a run is not captured in the artifact store, it did not happen. This enables caching, reproducibility, comparison, and autoresearch as side effects of normal use.

2. **Narrow, typed, opinionated agent interfaces.** Flexible interfaces degrade into agent flailing. Expose 6–10 well-typed tools, not 50 loose ones.

3. **Calibration is first-class, not a bolt-on.** SWAT+ models are judged by calibration credibility. Ship a calibration story on day one of v1.0.

4. **Differentiable-adjacent, not differentiable-everywhere.** SWAT+ is Fortran; making it differentiable is a 3-year research problem. A differentiable surrogate of SWAT+ is a 3-week engineering problem with most of the benefit.

5. **Scope discipline.** Every feature request is evaluated against "does this belong in `swatplus-builder` or in a separate project?" Features outside the agent-native SWAT+ interface mission are declined or deferred. Over-scoping is the single largest timeline risk.

6. **Scientific transparency is non-negotiable.** Fallback soils, auto-detected outlets, synthetic weather — all must be surfaced, flagged, and persisted.

---

## 4. Phase Overview

| Phase | Name | Duration | Dependencies | Deliverable |
|-------|------|----------|--------------|-------------|
| 3A | Hardening | 3–4 weeks | None | CI gate, metadata persistence, guardrails |
| 3B | Artifact System & Validation | 2–3 weeks | 3A | Artifact schema, curated basin suite, benchmark report |
| 3C | Calibration (Two-Track) | 4–5 weeks | 3B | SpotPy wrapper + differentiable surrogate |
| 3D | Agent Loop & Autoresearch | 3–4 weeks | 3B, 3C | MCP tools, SKILL.md, experiment loop |
| 3E | Packaging & Distribution | 2 weeks | 3A–3D | Docker image, docs site, CLI polish |
| 3F | Physical Fidelity | Parallel | Independent | HAND LSU, waterbody subtraction (research track) |

**Total mainline timeline:** ~14–18 weeks (~3.5–4.5 months) to v1.0.

Phase 3F runs parallel and does not block v1.0 release.

---

## Phase 3A — Hardening (3–4 weeks)

**Goal:** Prevent regressions, build trust, and make the pipeline debuggable. Non-negotiable foundation.

### 3A.1 CI Routing Regression Gate

Automated test suite running on every commit.

- [ ] Select 2–3 representative basins (small, medium, mixed climate)
- [ ] Pin reference inputs (DEM, land use, soil, weather) to a versioned location
- [ ] Assert per basin:
  - Engine does not crash
  - Terminal channel flow > 0
  - Alignment output exists
  - Outlet auto-detection works when configured outlet is dry
  - **Baseline metric floor: NSE > −1 with default parameters** (detects silent regressions where calibration might later mask upstream bugs)
- [ ] Wire into GitHub Actions; fail PR on violation
- [ ] Add runtime budget (e.g., 15 min); fail on timeout

### 3A.2 Evaluation Metadata Persistence

Every run writes full metadata so debugging is traceable, not guesswork.

- [ ] Design `metadata.json` schema (see Appendix A)
- [ ] Capture on every run:
  - Selected outlet GIS ID + auto-detection flag
  - Routing mode (`lte_stable`, etc.)
  - Soil mode + fallback usage percentage
  - Engine version + git SHA
  - Input dataset hashes
  - Weather source (GridMET / synthetic) + coverage flags
- [ ] Add `swat inspect <run_id>` CLI command to display metadata

### 3A.3 Soil Realism Flags

Expose fidelity clearly.

- [ ] Add `soil_mode` field to all outputs: `high_fidelity` | `fallback` | `synthetic`
- [ ] Compute `pct_fallback_soils` per run
- [ ] Emit warning when `pct_fallback_soils > 25%` (threshold configurable)
- [ ] Propagate flag through to plots (watermark on figures generated from fallback runs)
- [ ] Document soil fidelity levels in user-facing docs

### 3A.4 Large Basin Guardrails

Prevent hang / crash scenarios.

- [ ] Measure subbasin count and HRU count before engine invocation
- [ ] Define thresholds (tuned empirically; start with `n_subbasins > 500` or `n_hrus > 5000`)
- [ ] On threshold breach:
  - Log warning with guidance
  - Offer auto-adjusted thresholds (HRU aggregation)
  - Fail fast if user opts out of adjustment
- [ ] Add `--max-hrus`, `--max-subbasins` CLI flags

### 3A.5 Exit criteria for Phase 3A

- CI gate running green on 2–3 basins
- Every run produces complete `metadata.json`
- Soil fidelity flags visible in outputs and figures
- Large-basin paths fail fast or auto-adjust; no silent hangs

---

## Phase 3B — Artifact System & Validation Layer (2–3 weeks)

**Goal:** Establish the run artifact as the universal currency of the project. Build the validation infrastructure on top of it.

**Key deviation from the plan given:** The run artifact system is pulled forward from Phase 3D to Phase 3B. Every subsequent component (calibration, agent loop, benchmark reports) writes to this schema. Design it once, early.

### 3B.1 Run Artifact Schema

See Appendix A for full specification. Summary:

```
runs/
  <content_hash>/
    config.json          # inputs, parameter values, basin ID, options
    metadata.json        # engine version, soil mode, outlet info, git SHA
    metrics.json         # NSE, KGE, PBIAS, BFI, log-NSE, timing stats
    timeseries.parquet   # observed + simulated per outlet, daily resolution
    plots/               # PNG + PDF for each standard figure type
    logs/                # engine stdout/stderr, pipeline logs
    provenance.json      # lineage: parent run, proposal source, agent context
```

- [ ] Define JSON schemas (use `pydantic` for validation)
- [ ] `content_hash` = SHA256 of canonicalized `config.json` + engine version + code SHA
- [ ] Implement `ArtifactStore` class with: `write()`, `read()`, `exists()`, `query()`, `lineage()`
- [ ] Support local filesystem backend (v1); pluggable backend interface for future S3 / cloud
- [ ] **Content-addressed caching falls out for free:** check `exists(hash)` before running

### 3B.2 Standard Validation Runner

Single command, benchmark-grade output.

- [ ] `swat validate --basins curated_set.json` CLI command
- [ ] Runs each basin, writes artifacts, aggregates results
- [ ] Outputs:
  - Per-basin NSE, KGE, PBIAS, log-NSE, BFI
  - Hydrograph plots (observed vs simulated, full + peak-zoom)
  - Summary CSV + Markdown report
  - Pass/fail status per basin against configurable thresholds

### 3B.3 Curated Basin Suite

Define the truth dataset. Target 6–10 basins spanning:

- [ ] 2 small flashy basins (urban / steep headwater)
- [ ] 2 baseflow-dominated (karst / groundwater-fed)
- [ ] 2 mixed regime (moderate lowland)
- [ ] 2 with different climates (arid West, humid Southeast, snow-affected)
- [ ] Optional: 1–2 ungauged-prediction cases (held-out for generalization testing)

Each basin spec includes: USGS gauge ID, bounding box, expected simulation window, reference NSE range, notes on known difficulties.

Store as `basins/curated_v1.json` in repo; version bumps require justification.

### 3B.4 Benchmark Report

Auto-generated from artifact store.

- [ ] Per-basin metrics table
- [ ] Cross-basin summary (median, quantiles, fail count)
- [ ] Comparison plots
- [ ] Markdown + PDF output
- [ ] **This becomes the paper backbone, the demo, and the regression reference.**

### 3B.5 Exit criteria for Phase 3B

- Artifact store operational; every run from here on writes artifacts
- Curated basin suite defined and stored in repo
- `swat validate` produces complete benchmark report end-to-end
- Content-addressed caching operational (re-runs with identical config skip engine invocation)

---

## Phase 3C — Calibration (Two-Track) (4–5 weeks)

> Note (2026-04-23): For active execution, this section is superseded by
> `CALIBRATION_PLAN_REVISED.md` (pySWATPlus-based calibration integration).
> Historical content below is retained for provenance until full roadmap text migration.

**Goal:** Ship a calibration story that serves both classical practitioners and agent-native autoresearch workflows.

**Rationale for two tracks:** Classical calibration is what practitioners expect (SpotPy, DDS, SCE-UA). Surrogate-based calibration is the architectural moat that makes agent-driven autoresearch tractable given SWAT+ is expensive to run.

### Track 1 — Classical Calibration (SpotPy-based)

#### 3C.1 Parameter Registry

First-class data structure for SWAT+ parameters. See Appendix B for full specification.

- [ ] Define `Parameter` dataclass: name, file, range, units, physical meaning, tier (global / HRU / subbasin)
- [ ] Populate with the standard set: CN2, ALPHA_BF, GW_DELAY, ESCO, EPCO, SURLAG, CH_N2, CH_K2, SOL_AWC, SOL_K, GWQMN, REVAPMN, GW_REVAP, PLAPS, TLAPS, SFTMP, SMTMP
- [ ] Add validation: bounds-checking, HRU/subbasin scoping
- [ ] Expose as importable: `from swatplus_builder.params import registry`

#### 3C.2 SpotPy Calibration Wrapper

Classical optimization on top of the parameter registry.

- [ ] Support algorithms: DDS (primary — closest to SWAT-CUP SUFI-2), SCE-UA, random search (sanity baseline)
- [ ] Multi-objective from day one: NSE, log-NSE, PBIAS (KGE components)
- [ ] Write every sampled parameter set as an artifact (auto-caching via content hash)
- [ ] CLI: `swat calibrate --basin <id> --algo dds --n-iter 500 --objectives nse,log_nse,pbias`
- [ ] Support warm-start from existing artifacts

#### 3C.3 Calibration Reporting

- [ ] Dotty plots (parameter sensitivity)
- [ ] Convergence plot (objective vs iteration)
- [ ] Best-parameter summary with uncertainty bounds
- [ ] Pareto front for multi-objective runs

### Track 2 — Differentiable-Friendly Surrogate

#### 3C.4 Typed Parameter → Output Function

Expose the SWAT+ forward pass as a callable.

- [ ] `f(θ: ParameterVector, basin: BasinSpec) → SimulatedTimeseries`
- [ ] Fully typed; amenable to automatic differentiation tooling (via surrogate)
- [ ] Artifact-aware (skips engine if hash exists)

#### 3C.5 Neural Surrogate

Small neural network that learns `f` from the artifact store.

- [ ] Architecture: MLP (v1) or small Transformer (v2); 2–4 hidden layers, ~64–128 units
- [ ] Training data: drawn from artifact store (calibration runs populate this naturally)
- [ ] Input: flattened parameter vector + basin attributes
- [ ] Output: daily discharge timeseries (or summary statistics)
- [ ] Uncertainty quantification: ensemble of N=5 surrogates, disagreement = uncertainty
- [ ] Hot-path: when agent proposes θ, surrogate predicts; if uncertainty < threshold, use surrogate; else invoke real engine and update surrogate

#### 3C.6 Surrogate Positioning

This surrogate is a neural emulator of SWAT+, not a differentiable replacement of the engine. It is decoupled from the engine: the engine remains authoritative; the surrogate accelerates search. This distinction matters for scientific framing — document it explicitly in methods sections and in user-facing docs.

### 3C.7 Exit criteria for Phase 3C

- `swat calibrate` operational with DDS + SCE-UA + random search
- Multi-objective calibration produces Pareto fronts
- Parameter registry complete and documented
- Neural surrogate trains from artifact store and predicts SWAT+ output within acceptable error bounds (target: median NSE agreement > 0.8 between surrogate and engine)
- Hot-path logic routes between surrogate and engine based on uncertainty

---

## Phase 3D — Agent Loop & Autoresearch (3–4 weeks)

**Goal:** Enable autonomous SWAT+ experimentation by AI agents. Ship the MCP-native interface.

**Key adaptation from Karpathy's autoresearch loop:** SWAT+ runs are expensive, so the loop routes through the surrogate first. This is the reason Phase 3C Track 2 exists.

### 3D.1 Agent Loop Architecture

```
propose → surrogate_predict → uncertainty_check →
  [if confident]   → use surrogate result
  [if uncertain]   → run real engine → update surrogate → store artifact
→ evaluate → compare_to_history → iterate
```

- [ ] Implement loop orchestrator as standalone module
- [ ] Support proposal sources: random, grid, SpotPy (DDS), LLM-proposed
- [ ] Track experiment lineage in `provenance.json`
- [ ] Configurable stopping criteria: n_iterations, objective_threshold, convergence

### 3D.2 MCP Tool Surface

Narrow, typed, opinionated. **Target: 8 tools, not 50.**

- [ ] `build_project(basin_spec)` → project artifacts
- [ ] `run_basin(config)` → run artifact
- [ ] `calibrate(basin, algo, objectives, budget)` → calibration artifact set
- [ ] `propose_parameters(basin, history, strategy)` → parameter vector
- [ ] `compare_runs(run_ids)` → comparison artifact
- [ ] `query_artifacts(filters)` → artifact metadata list
- [ ] `diagnose_failure(run_id)` → structured diagnosis with suggested fixes
- [ ] `validate(basin_suite)` → benchmark report

Each tool has: typed inputs (Pydantic), typed outputs, clear docstrings with examples, failure modes enumerated.

### 3D.3 SKILL.md for Agents

Ship co-located with `swatplus-builder`. Any MCP-capable agent picks it up.

See Appendix C for structure. Key sections:

- [ ] Tool catalog with usage patterns
- [ ] Parameter registry with physical meaning
- [ ] Common failure modes and diagnostic heuristics
- [ ] Basin taxonomy (flashy vs baseflow vs mixed)
- [ ] Evaluation protocol (metrics, splits, significance)
- [ ] Example agent workflows (calibrate → diagnose → re-calibrate)

### 3D.4 Diagnostic Heuristics Module

Encode hydrological knowledge for agents.

- [ ] Peak lag > 1 day → suspect SURLAG
- [ ] Baseflow too low → suspect ALPHA_BF, GW_DELAY, GWQMN
- [ ] Total volume bias > 15% → suspect CN2, ET parameters
- [ ] Snowmelt timing off → suspect SFTMP, SMTMP
- [ ] Flat hydrograph → check outlet selection, routing mode
- [ ] Expose as callable: `diagnose(observed, simulated) → List[Diagnosis]`

### 3D.5 Exit criteria for Phase 3D

- All 8 MCP tools operational and typed
- `SKILL.md` complete and tested with at least one external MCP-capable agent
- Autoresearch loop completes end-to-end on a curated basin
- Diagnostic heuristics produce actionable output for at least 5 common failure modes

---

## Phase 3E — Packaging & Distribution (2 weeks)

**Goal:** Make the package installable, reproducible, and documented. Done last intentionally — containerizing an in-flight interface is costly to un-do.

### 3E.1 Containerization

- [ ] Dockerfile with SWAT+ engine, all Python dependencies, WhiteboxTools binaries
- [ ] Multi-stage build to minimize image size
- [ ] Publish to Docker Hub / GHCR
- [ ] Tag strategy: semantic versions + `latest` + `dev`

### 3E.2 CLI Polish

- [ ] Unified `swat` command with subcommands: `run`, `validate`, `calibrate`, `inspect`, `diagnose`
- [ ] Consistent flag conventions
- [ ] `--help` output reviewed for clarity
- [ ] Tab completion for bash / zsh

### 3E.3 Documentation Site

- [ ] MkDocs or Sphinx; hosted on ReadTheDocs or GitHub Pages
- [ ] Sections: Getting Started, Concepts, Tool Reference, Tutorials, API Reference, Agent Integration, Troubleshooting
- [ ] Example notebooks: single-basin workflow, calibration, agent-driven autoresearch, custom basin

### 3E.4 Release Engineering

- [ ] Semantic versioning enforced
- [ ] Changelog maintained (keep-a-changelog format)
- [ ] PyPI publication via GitHub Actions on tag
- [ ] Zenodo DOI minted for v1.0

### 3E.5 Exit criteria for Phase 3E (and v1.0)

- `pip install swatplus-builder` works end-to-end
- Docker image pulls and runs the benchmark suite unchanged
- Docs site live with all example notebooks executing correctly
- v1.0 tagged, released to PyPI, DOI minted

---

## Phase 3F — Physical Fidelity (Parallel Track)

**Goal:** Track physical realism improvements as a parallel research effort. Does NOT block v1.0.

These items are important but deferred from mainline because: (a) they are research problems with open questions, (b) they benefit from having the rest of the system stable to measure against, and (c) including them in v1.0 risks timeline slip.

- [ ] HAND-based LSU split (Height Above Nearest Drainage)
- [ ] Waterbody subtraction from HRU computation
- [ ] Full routing realism parity with QSWATPlus
- [ ] Elevation bands for snow-dominated basins
- [ ] Benchmark parity report against QSWATPlus outputs

Progress here informs v1.1 or v2.0 scope.

---

## 11. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Scope creep into general hydrological modeling | High | High | Principle 5 enforcement; decline out-of-scope features |
| Calibration surrogate accuracy insufficient | Medium | Medium | Track 1 (SpotPy) always works; surrogate is additive |
| Agent loop degrades into flailing | Medium | High | Narrow MCP surface (8 tools); strong typing; opinionated defaults |
| Competing priorities delay roadmap execution | High | Medium | Phase 3F is parallel, not blocking; protect focused development blocks |
| Engine version drift breaks reproducibility | Medium | High | Engine version in artifact metadata; CI gate pins engine version |
| Large-basin use cases expose fundamental design issues | Medium | Medium | Phase 3A guardrails fail fast; address in v1.1 if structural |

---

## 12. Milestones & Success Criteria

| Milestone | Target week | Success criterion |
|-----------|-------------|-------------------|
| M1: CI gate green | Week 4 | 3 basins pass on every commit, NSE > −1 floor enforced |
| M2: Artifact store operational | Week 7 | Every run writes complete artifact; content-addressed caching skips re-runs |
| M3: Benchmark report on curated suite | Week 9 | 6–10 basins produce full benchmark report; published in repo |
| M4: Classical calibration shipped | Week 12 | `swat calibrate` with DDS produces Pareto fronts on curated basins |
| M5: Neural surrogate operational | Week 14 | Surrogate NSE vs engine > 0.8 on held-out basins |
| M6: Agent loop end-to-end | Week 17 | Autoresearch loop completes on one basin via MCP tools + SKILL.md |
| M7: v1.0 released | Week 18 | PyPI, Docker, docs site, DOI all live |

---

## Appendix A — Artifact Schema Specification

### Directory structure

```
runs/
  <content_hash>/
    config.json
    metadata.json
    metrics.json
    timeseries.parquet
    plots/
      hydrograph.png
      hydrograph.pdf
      peak_zoom.png
      flow_duration.png
      scatter_obs_sim.png
    logs/
      engine.stdout
      engine.stderr
      pipeline.log
    provenance.json
```

### `config.json` (inputs — used for content hashing)

```json
{
  "basin_id": "usgs_01594440",
  "bbox": [-77.0, 39.0, -76.5, 39.5],
  "simulation_start": "2010-01-01",
  "simulation_end": "2019-12-31",
  "parameters": {
    "CN2": {"value": 75.0, "scope": "global"},
    "ALPHA_BF": {"value": 0.048, "scope": "global"}
  },
  "options": {
    "routing_mode": "lte_stable",
    "weather_source": "gridmet",
    "soil_source": "stac"
  }
}
```

### `metadata.json` (provenance — not used for hashing)

```json
{
  "run_id": "a7f3c9...",
  "timestamp_utc": "2026-04-23T14:32:10Z",
  "engine_version": "swatplus-61.0.6",
  "builder_version": "0.5.0",
  "git_sha": "3a4b5c6...",
  "outlet": {
    "gis_id": 12,
    "auto_detected": true,
    "reason": "configured outlet was dry"
  },
  "soil_mode": "fallback",
  "pct_fallback_soils": 0.34,
  "weather_coverage": {
    "pct_gridmet_native": 1.0,
    "pct_synthetic": 0.0
  },
  "n_subbasins": 14,
  "n_hrus": 127,
  "runtime_seconds": 182
}
```

### `metrics.json`

```json
{
  "outlet_id": 12,
  "period": {"start": "2015-01-01", "end": "2019-12-31"},
  "nse": 0.62,
  "log_nse": 0.54,
  "kge": 0.71,
  "pbias": -8.3,
  "bfi_observed": 0.42,
  "bfi_simulated": 0.38,
  "peak_flow_error_pct": 12.1
}
```

### `provenance.json`

```json
{
  "parent_run": "b4e2a1...",
  "proposal_source": "dds_iteration_47",
  "agent_context": {
    "agent_id": "mcp-agent-v0.3",
    "experiment_id": "calibration_usgs_01594440_20260423"
  }
}
```

### Content hash computation

```
content_hash = SHA256(
  canonical_json(config) || engine_version || builder_git_sha
)
```

Canonical JSON: sorted keys, no whitespace, UTF-8. Identical hash → identical outputs → cache hit.

---

## Appendix B — Parameter Registry

### Structure

```python
@dataclass
class Parameter:
    name: str                    # e.g. "CN2"
    file: str                    # e.g. "hydrology.hyd"
    scope: ParameterScope        # GLOBAL | HRU | SUBBASIN | CHANNEL
    range: Tuple[float, float]   # physical bounds
    default: float
    units: str
    description: str
    adjustment_type: str         # "replace" | "multiply" | "add"
    tier: int                    # 1=most sensitive, 3=least
```

### Initial set (v1.0)

| Parameter | File | Scope | Range | Tier | Notes |
|-----------|------|-------|-------|------|-------|
| CN2 | hydrology.hyd | HRU | [35, 98] | 1 | SCS curve number |
| ALPHA_BF | aquifer.aqu | SUBBASIN | [0, 1] | 1 | Baseflow recession |
| GW_DELAY | aquifer.aqu | SUBBASIN | [0, 500] | 1 | Groundwater delay (days) |
| ESCO | hydrology.hyd | HRU | [0, 1] | 2 | Soil evap compensation |
| EPCO | hydrology.hyd | HRU | [0, 1] | 2 | Plant uptake compensation |
| SURLAG | parameters.bsn | GLOBAL | [0.05, 24] | 1 | Surface runoff lag |
| CH_N2 | channel-lte.cha | CHANNEL | [0.014, 0.15] | 2 | Manning's n, main channel |
| CH_K2 | channel-lte.cha | CHANNEL | [0, 500] | 2 | Channel hydraulic conductivity |
| SOL_AWC | soils.sol | HRU | [0, 1] | 2 | Available water capacity |
| SOL_K | soils.sol | HRU | [0, 2000] | 2 | Saturated hydraulic conductivity |
| GWQMN | aquifer.aqu | SUBBASIN | [0, 5000] | 2 | Threshold for baseflow |
| REVAPMN | aquifer.aqu | SUBBASIN | [0, 500] | 3 | Threshold for revap |
| GW_REVAP | aquifer.aqu | SUBBASIN | [0.02, 0.2] | 3 | Groundwater revap coefficient |
| PLAPS | subbasin.sub | SUBBASIN | [−1000, 1000] | 3 | Precipitation lapse rate |
| TLAPS | subbasin.sub | SUBBASIN | [−10, 10] | 3 | Temperature lapse rate |
| SFTMP | parameters.bsn | GLOBAL | [−5, 5] | 2 | Snowfall temperature |
| SMTMP | parameters.bsn | GLOBAL | [−5, 5] | 2 | Snowmelt base temperature |

Tier 1 parameters are default for calibration; tier 2/3 are optional extensions.

---

## Appendix C — Agent SKILL.md Structure

Ship `SKILL.md` at the root of the package. Structure:

```markdown
---
name: swatplus-builder
description: "Use this skill when building, running, calibrating, or
  diagnosing SWAT+ hydrological models. Triggers include: any mention of
  SWAT+, watershed modeling, streamflow simulation, hydrograph calibration,
  or requests involving USGS gauges and discharge prediction."
---

# SWAT+ Builder — Agent Skill

## When to use this skill
[Concrete triggers, non-triggers, boundary cases]

## Tool catalog
[One section per MCP tool with typed signatures and usage examples]

## Parameter registry
[Table from Appendix B with physical meaning]

## Diagnostic heuristics
[Failure mode → suspected parameters → verification steps]

## Basin taxonomy
[Flashy / baseflow / mixed / snow — and what to prioritize for each]

## Evaluation protocol
[Which metrics, which splits, significance thresholds]

## Example workflows
[Calibrate → diagnose → re-calibrate, with concrete tool call sequences]

## Common pitfalls
[Outlet selection, soil fidelity flags, calibration over short windows,
  over-fitting to a single metric]
```

The skill must be **narrow and opinionated**, not flexible. Agents that have to choose between 10 valid approaches will choose poorly.

---

## Document Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | April 2026 | Initial roadmap |

---

**End of document.**
