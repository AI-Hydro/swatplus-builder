# Sealed Calibration Resume Plan

## Goal

Resume exact sensitivity/candidate objective vectors after interruption without
re-running valid SWAT+ evaluations or weakening final evidence authority.

## Contract

- Compact traces are reusable only when parameter values and a context
  signature match exactly.
- The signature covers the sealed benchmark/input identity, scoring window,
  engine binary, builder version, and calibration implementation hashes.
- Legacy, edited, incomplete, or mismatched traces are ignored.
- Final locked verification and withheld-period validation always run fresh.

## Acceptance Criteria

- A repeated exact candidate returns the persisted metrics without another
  engine call.
- Changing context, parameters, or trace content forces a fresh engine call.
- Canonical sensitivity and calibration use sealed reuse; verification does not.
- Focused tests, lint, compilation, and real trace inspection pass.

## Outcome

- Implemented tamper-evident compact trace reuse under a sealed objective
  context.
- Exact reuse, tamper rejection, and changed-context rejection tests pass.
- A real sealed `01547700` exact repeat returned identical metrics in
  `0.00035 s` after a `66.54 s` fresh objective.
- The legacy interrupted run is deliberately ineligible because its traces
  predate the context signature.
