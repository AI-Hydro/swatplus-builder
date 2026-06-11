# swatplus-builder Roadmap

Last updated: 2026-05-12.

## Mission

Build a research-grade, agent-governed SWAT+ production pipeline through
iterative evidence-backed improvement. The package must emit enough logs,
diagnostics, gates, provenance, and claim decisions that an agent cannot
silently overclaim.

## Phase 0 — Research-Grade Audit

Status: complete as audit, not as certification.

Exit artifacts:

- `docs/PIPELINE_RESEARCH_GRADE_AUDIT.md`

Key outcome:

- The canonical workflow command, evidence bundle, parameter governance, and
  calibration provenance were identified as the immediate production blockers.

## Phase 1 — Canonical Workflow Authority

Status: active.

Goal:

- Make `swat workflow run --model-family full --calibrate` the authoritative
  research-grade path.

Acceptance criteria:

- Every workflow run writes `evidence_summary.json`,
  `outlet_provenance.json`, `calibration_provenance.json`,
  `parameter_screen.json`, `run_manifest.json`, and `events.jsonl`.
- `evidence_summary.json` includes `allowed_claims` and `blocked_claims`.
- Scripts aggregate canonical evidence only; they do not define scientific
  policy.

## Phase 2 — Calibration Auditability

Goal:

- Ensure final calibration evidence comes from a locked calibrated artifact,
  not temporary candidates.

Acceptance criteria:

- Candidate runs use clean outputs and verified engine completion.
- Best candidate is promoted to locked calibrated `TxtInOut`.
- Locked artifact is rerun cleanly.
- Final metrics and gates come from the locked artifact.
- Candidate table records accepted/rejected parameters and reason codes.

## Phase 3 — Unified Parameter Governance

Goal:

- Unify registry, bridge, sensitivity screen, documentation, and tests for
  full-mode calibration parameters.

Acceptance criteria:

- Each governed parameter records target file, target column, range, default,
  scope, activity class, evidence source, supported model family, and claim-tier
  allowance.
- Bridge-supported parameters have tests.
- Registry-only parameters cannot support research-grade claims.
- Dead/unsupported parameters fail loudly.

## Phase 4 — Iterative Diagnostic Calibration

Goal:

- Implement automated phased calibration: volume and water balance, baseflow
  partition, peak/timing response, then KGE/NSE finetuning after physical gates.

Acceptance criteria:

- Each candidate is classified as accepted, rejected by physics, rejected by
  sensitivity, rejected by structure, rejected by engine, rejected by data,
  needs diagnostic, needs bridge, or needs model-family change.

## Phase 5 — Runtime Claim Governance

Goal:

- Enforce contracts and claim tiers at runtime.

Acceptance criteria:

- `contract_status`, `accepted_by`, and `claim_tier` affect allowed claims.
- Missing/draft contract downgrades claims.
- Research-grade requires contract, provenance, physical, statistical,
  sensitivity, and calibration gates.

## Phase 6 — Validation Harness

Goal:

- Use basins as a stress test for improving the pipeline, not as pass-count
  targets.

Initial suite:

- `02129000`, `01547700`, `03349000`, `01654000`, `01491000`,
  `01013500`, `03351500`, `03353000`, `01493500`, `12031000`, `09504500`.

Acceptance criteria:

- Each basin has build, warmup, fresh engine run, outlet detection,
  diagnostics, sensitivity screen, calibration-if-allowed, locked rerun, gates,
  claim tier, evidence bundle, and learning note.

## Phase 7 — Learning System And Docs

Goal:

- Keep the agent-governed method reusable and honest.

Acceptance criteria:

- `PROJECT.md`, `PROGRESS.md`, `DECISIONS.md`,
  `docs/SWATPLUS_MODELING_PLAYBOOK.md`, `docs/AGENT_WORKFLOW.md`,
  `docs/CALIBRATION_PARAMETER_REGISTRY.md`, and
  `docs/PIPELINE_LEARNING_LOG.md` stay synchronized with implementation.

