# Calibration Throughput And Warm-Start Plan

## Goal

Reduce real-engine calibration wall time without weakening sealed-input,
fresh-output, or withheld-period evidence requirements.

## Scope

1. Evaluate deterministic, sensitivity-derived phase anchors concurrently.
2. Write an explicit warm-start artifact from locked sensitivity evidence.
3. Keep adaptive DDS, candidate selection, locked verification, and temporal
   transfer evaluation serial and fresh.

## Acceptance Criteria

- Parallel anchor execution uses isolated SWAT+ objective directories.
- History ordering and selected result remain deterministic regardless of
  worker completion order.
- Warm-start artifacts are explicitly exploratory and cannot act as final
  metric or claim authority.
- Workflow provenance records requested worker counts and warm-start paths.
- Focused regression tests and a real locked-objective integration screen pass.

## Non-Goals

- No cache may substitute for final verification or withheld validation.
- No blind high-budget global optimiser or external SWAT2012 package is added.
- No publication or PyPI release occurs until a fresh complete workflow has
  measured the end-to-end effect.

## Outcome

- Implemented bounded parallel fixed-anchor evaluation and a hash-linked,
  exploratory-only warm-start artifact.
- Focused regression suites pass. A sealed `01547700` real-engine four-anchor
  integration completed in `74.4 s` with deterministic five-row history.
- A full end-to-end wall-time measurement remains the release gate.
