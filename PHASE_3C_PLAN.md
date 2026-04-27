# Phase 3C Plan — Calibration (Two-Track)

Date: 2026-04-23  
Roadmap reference: `ROADMAP.md` -> Phase 3C (Track 1 + Track 2, 3C.1–3C.7)  
Status: Active

## Scope

Deliver Phase 3C in roadmap order while preserving artifact-first execution:

1. Parameter registry foundation (3C.1)
2. SpotPy calibration wrapper (3C.2)
3. Calibration reporting (3C.3)
4. Typed parameter->output function (3C.4)
5. Neural surrogate training/inference path (3C.5)
6. Surrogate framing and docs (3C.6)
7. Exit-criteria proof and closeout (3C.7)

## PR Decomposition (mergeable in isolation)

### PR-3C-01: Parameter Registry Core

Roadmap mapping:
- 3C.1 all bullets

Planned changes:
- Add typed `Parameter` model + scope enums + validation.
- Populate initial parameter set from roadmap table.
- Expose import surface: `from swatplus_builder.params import registry`.
- Add bounds/scoping validation helpers.

Test plan:
- Unit tests for schema validation and range checks.
- Registry completeness assertions for required canonical parameters.

Deliberately not done:
- Calibration algorithm execution.

### PR-3C-02: SpotPy Adapter Skeleton + Artifact Integration

Roadmap mapping:
- 3C.2 bullets 1, 3, 5

Planned changes:
- Add calibration runner scaffolding with SpotPy adapter hooks.
- Ensure every sampled parameter vector writes to artifact store.
- Add warm-start load from existing artifacts.

Test plan:
- Unit tests with deterministic mock objective function.
- Artifact-write assertions per sampled iteration.

Deliberately not done:
- Final CLI UX and full algorithm matrix in this PR.

### PR-3C-03: `swat calibrate` CLI + Multi-objective support

Roadmap mapping:
- 3C.2 bullets 2, 4

Planned changes:
- Add `swat calibrate --basin ... --algo ... --n-iter ... --objectives ...`.
- Support DDS (primary), SCE-UA, and random baseline routing to adapter layer.
- Implement multi-objective bookkeeping (`nse`, `log_nse`, `pbias`).

Test plan:
- CLI integration tests with mocked calibration backend.
- Objective parsing and failure-mode tests.

Deliberately not done:
- Surrogate components.

### PR-3C-04: Calibration Reporting Artifacts

Roadmap mapping:
- 3C.3 all bullets

Planned changes:
- Generate dotty/convergence/Pareto artifacts from calibration runs.
- Persist report outputs under artifact lineage.

Test plan:
- Plot/report generation tests from synthetic calibration histories.

Deliberately not done:
- Neural surrogate.

### PR-3C-05: Typed Forward Function + Surrogate Dataset Bridge

Roadmap mapping:
- 3C.4 all bullets

Planned changes:
- Implement typed `f(theta, basin) -> simulated_timeseries` entrypoint.
- Route through artifact cache prior to engine invocation.
- Build dataset extraction utility from artifact store for surrogate training.

Test plan:
- Determinism tests with fixed seeds/config.
- Cache short-circuit tests on repeated parameter vectors.

Deliberately not done:
- Full surrogate model training stack.

### PR-3C-06: Neural Surrogate MVP + Uncertainty Gate

Roadmap mapping:
- 3C.5 all bullets

Planned changes:
- Add surrogate training/inference module (MLP v1).
- Ensemble-based uncertainty estimate and engine fallback routing logic.

Test plan:
- Training smoke tests on synthetic artifact dataset.
- Uncertainty-gate behavior tests (surrogate vs engine path selection).

Deliberately not done:
- Advanced architectures beyond MVP.

### PR-3C-07: Surrogate Positioning Docs + Phase Closeout

Roadmap mapping:
- 3C.6 and 3C.7

Planned changes:
- Document surrogate as emulator (not engine replacement) in user/developer docs.
- Write `PHASE_3C_CLOSEOUT.md` with evidence against 3C.7 criteria.

Test plan:
- End-to-end calibration smoke on small basin subset.
- Exit-criteria checklist with artifact links.

## Risks (Phase-specific)

1. Calibration runtime explosion.
   - Mitigation: strict iteration budgets in CI; long runs only in scheduled/manual workflows.
2. Surrogate data quality lagging behind schema completeness.
   - Mitigation: gate surrogate training on artifact completeness checks.
3. Objective conflicts masking structural issues.
   - Mitigation: keep structural gates independent from calibration objectives.

## Mapping Matrix

- 3C.1 -> PR-3C-01
- 3C.2 -> PR-3C-02, PR-3C-03
- 3C.3 -> PR-3C-04
- 3C.4 -> PR-3C-05
- 3C.5 -> PR-3C-06
- 3C.6 -> PR-3C-07
- 3C.7 -> PR-3C-07

