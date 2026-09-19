# Preprint hardening and evidence refresh — 2026-09-19

## Goal

Resolve the blockers in `docs/PREPRINT_READINESS_REVIEW_2026-09-19.md`, align
the manuscript with the implemented evidence contract, and produce fresh
same-version evidence suitable for a bounded public preprint.

## Work

1. Isolate all observation-conditioned preparation to the calibration window,
   including the corresponding model water-balance diagnostics.
2. Fail closed on wrong GridMET calendars, non-finite values, invalid physical
   ranges, and unsupported timeout semantics.
3. Recompute claim-gate decisions from typed evidence rather than free text.
4. Bind engine receipts to inputs, executable identity, and execution settings.
5. Add focused regression and fault-injection coverage and run release checks.
6. Revise the manuscript, claim ledger, figures, gap inventory, and related work.
7. Freeze a portable local code/evidence package and attempt fresh positive and
   negative workflow runs under the resulting version.

## Acceptance

- Changing only validation observations cannot change prepared model inputs.
- Weather dates and raw values are validated before conversion or reuse.
- Contradictory or untyped claim declarations fail.
- A post-run input mutation invalidates freshness evidence.
- Manuscript claims and visuals state the actual validation scope.
- Fresh runs, if completed, use one frozen source state and preserve failures.

The user's 2026-09-19 instruction to incorporate all findings authorizes this
plan. Public publication, DOI minting, and author-only declarations remain
external finalization actions.
