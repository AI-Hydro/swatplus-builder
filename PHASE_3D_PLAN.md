# Phase 3D Plan — Agent Loop & Autoresearch (Revised)

Date: 2026-04-24  
Roadmap reference:
- `ROADMAP.md` -> Phase 3D (3D.1 through 3D.5)
- `CALIBRATION_PLAN_REVISED.md` -> Revised Phase 3D additions (3D.X, 3D.Y, 3D.Z)  
Status: Active

## Scope

Deliver Phase 3D in revised order:

1. MCP typed tool surface (8 tools) and server wiring.
2. Agent-facing `SKILL.md` and operational usage patterns.
3. Agent loop orchestrator with artifact lineage and stopping criteria.
4. Surrogate training + uncertainty ensemble (moved from legacy 3C).
5. Surrogate-aware routing between predictor and real engine.
6. Surrogate evaluation harness on hold-out basins.
7. Phase 3D exit evidence package.

Non-goals in this phase:

- No new calibration algorithm design beyond existing bridge interfaces.
- No Phase 3E packaging/containerization work.
- No Phase 3F physical-fidelity expansion.

## PR Decomposition (mergeable in isolation)

### PR-3D-01: MCP Server Foundation + Typed Tool Contracts

Roadmap mapping:
- 3D.2 all bullets
- 3D.5 bullet 1 (partial)

Planned changes:
- Replace current MCP placeholder server with operational stdio server wiring.
- Register exactly 8 typed tools:
  - `build_project`
  - `run_basin`
  - `calibrate`
  - `propose_parameters`
  - `compare_runs`
  - `query_artifacts`
  - `diagnose_failure`
  - `validate`
- Ensure each tool has:
  - typed inputs/outputs,
  - examples in docstrings,
  - enumerated failure modes.

Test plan:
- MCP tool registration tests (expected count + names).
- Schema/typing tests for tool IO payloads.
- Failure-mode tests for representative invalid inputs.

Deliberately not done:
- Surrogate logic integration (handled in PR-3D-04/05).

### PR-3D-02: Agent `SKILL.md` + Workflow Guidance

Roadmap mapping:
- 3D.3 all bullets
- Appendix C structure alignment

Planned changes:
- Add root `SKILL.md` with:
  - tool catalog,
  - parameter registry semantics,
  - failure diagnosis patterns,
  - basin taxonomy,
  - evaluation protocol,
  - example workflows (`calibrate -> diagnose -> recalibrate`).

Test plan:
- Lint/structure test for required sections in `SKILL.md`.
- Smoke test ensuring docs examples align with current CLI/tool signatures.

Deliberately not done:
- External publishing/docs-site work (Phase 3E).

### PR-3D-03: Agent Loop Orchestrator (Artifact-native)

Roadmap mapping:
- 3D.1 all bullets

Planned changes:
- Add loop orchestrator module implementing:
  - proposal -> predict/execute -> evaluate -> compare -> iterate.
- Support proposal sources:
  - random,
  - grid,
  - calibration-history informed.
- Persist lineage/provenance per iteration in artifact metadata.
- Add stopping criteria:
  - `n_iterations`,
  - objective threshold,
  - convergence tolerance.

Test plan:
- Deterministic loop test on synthetic evaluator.
- Stopping-criteria tests for each stop mode.
- Lineage persistence tests (`parent_run`, proposal source propagation).

Deliberately not done:
- Neural surrogate training (PR-3D-04).

### PR-3D-04: Surrogate Training + Uncertainty Ensemble

Roadmap mapping:
- Revised 3D.X

Planned changes:
- Add surrogate training pipeline from artifact-store rows:
  - inputs: flattened parameters + basin attributes,
  - targets: discharge summary metrics and/or calibration objective proxies.
- Train ensemble (`N=5`) models for uncertainty from inter-model spread.
- Persist surrogate model cards and training metadata artifacts.

Test plan:
- Unit tests for dataset extraction and feature shaping.
- Reproducibility test with fixed seed.
- Ensemble uncertainty test (non-zero spread on perturbed inputs).

Deliberately not done:
- Routing decisions in agent loop (PR-3D-05).

### PR-3D-05: Surrogate-aware Routing + Hold-out Harness

Roadmap mapping:
- Revised 3D.Y
- Revised 3D.Z
- 3D.5 bullets 3-4 (partial)

Planned changes:
- Add uncertainty-gated routing policy:
  - low uncertainty -> surrogate prediction,
  - high uncertainty -> authoritative engine run + artifact write.
- Implement hold-out evaluation harness:
  - compare surrogate-vs-engine agreement on unseen basins,
  - report median agreement metric (`NSE` agreement target > 0.8 per revised plan).

Test plan:
- Routing threshold tests (both branches forced).
- Incremental update tests (engine result feeds training corpus).
- Hold-out harness tests with deterministic fixture basins.

Deliberately not done:
- Full-scale benchmark report publication (Phase 3E).

### PR-3D-06: Phase 3D Closeout Evidence

Roadmap mapping:
- 3D.5 all bullets

Planned changes:
- Add `PHASE_3D_CLOSEOUT.md` with:
  - MCP tool evidence,
  - SKILL validation evidence,
  - autoresearch-loop run trace on curated basin,
  - diagnostic output evidence for >=5 failure modes.

Test plan:
- End-to-end smoke run from MCP entrypoint through loop for one curated basin.
- Artifact presence checks for loop lineage + surrogate routing outcomes.

Deliberately not done:
- Packaging/release actions (Phase 3E).

## Risks (Phase-specific)

1. MCP surface bloat / weak typing causes agent flailing.
- Mitigation: enforce fixed 8-tool contract and schema tests.

2. Surrogate quality insufficient for safe routing.
- Mitigation: keep authoritative fallback mandatory when uncertainty exceeds threshold; gate routing by hold-out agreement metrics.

3. Artifact lineage drift under iterative loops.
- Mitigation: assert lineage fields in tests for every loop step.

4. Licensing constraints around pySWATPlus coupling remain unresolved.
- Mitigation: keep lazy coupling boundaries; do not broaden hard dependency assumptions without explicit decision update.

## Mapping Matrix

- 3D.1 -> PR-3D-03
- 3D.2 -> PR-3D-01
- 3D.3 -> PR-3D-02
- 3D.4 -> PR-3D-03 + PR-3D-05 (existing diagnostics integration)
- 3D.5 -> PR-3D-06
- Revised 3D.X -> PR-3D-04
- Revised 3D.Y -> PR-3D-05
- Revised 3D.Z -> PR-3D-05
