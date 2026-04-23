# Phase 3B Plan — Artifact System & Validation Layer

Date: 2026-04-23  
Roadmap reference: `ROADMAP.md` -> Phase 3B (3B.1 through 3B.5)  
Status: Active

## Scope

Deliver all Phase 3B items in order:

1. Run artifact schema + content-addressed store (3B.1)
2. Standard validation runner CLI (3B.2)
3. Curated basin suite definition (3B.3)
4. Benchmark report generation (3B.4)
5. Demonstrate Phase 3B exit criteria (3B.5)

Non-goals in this phase:

- No Phase 3C calibration implementation.
- No cloud backend implementation beyond local filesystem pluggable interface.

## PR Decomposition (mergeable in isolation)

### PR-3B-01: Artifact Schema Models + Hashing Core

Roadmap mapping:
- 3B.1 bullets 1-2

Planned changes:
- Add typed pydantic schemas for:
  - `config.json`
  - `metadata.json` (compatible with Phase 3A metadata)
  - `metrics.json`
  - `provenance.json`
- Implement canonical config serialization + deterministic content hash:
  - `SHA256(canonical_config_json + engine_version + code_sha)`
- Add helpers for schema validation and hash computation.

Test plan:
- Unit tests for schema validation and required fields.
- Golden tests for canonicalization/hash determinism.
- Negative tests for schema mismatch.

Deliberately not done:
- Full artifact read/write API.

### PR-3B-02: Local ArtifactStore (Pluggable Backend Interface)

Roadmap mapping:
- 3B.1 bullets 3-5

Planned changes:
- Implement `ArtifactStore` interface with local FS backend:
  - `write()`, `read()`, `exists()`, `query()`, `lineage()`
- Directory contract under `runs/<content_hash>/...` exactly as Appendix A.
- Add pre-run cache check hook (`exists(hash)` short-circuit).

Test plan:
- Integration tests that write/read full artifact directory.
- Query and lineage tests over multiple synthetic run artifacts.
- Caching test: repeated identical config skips engine invocation path.

Deliberately not done:
- S3/cloud backend (keep pluggable contract only).

### PR-3B-03: `swat validate` Runner

Roadmap mapping:
- 3B.2 all bullets

Planned changes:
- Add CLI: `swat validate --basins curated_set.json`
- Execute per-basin runs through artifact store.
- Aggregate metrics and statuses.
- Persist:
  - summary CSV
  - markdown summary
  - per-basin artifacts and logs

Test plan:
- CLI integration test on small synthetic basin list fixture.
- Failure-path tests (basin fails, continue with status capture).
- Caching path test (second run faster, engine skipped).

Deliberately not done:
- Calibration or surrogate logic.

### PR-3B-04: Curated Basin Suite v1

Roadmap mapping:
- 3B.3 all bullets

Planned changes:
- Add `basins/curated_v1.json` with 6-10 representative basins.
- Include required fields:
  - USGS ID
  - bounding box
  - simulation window
  - expected NSE range
  - known-difficulty notes
- Add schema validation for curated suite file.

Test plan:
- Schema-validation test for curated file.
- CLI test: validate command loads curated suite.

Deliberately not done:
- Basin expansion beyond v1 set.

### PR-3B-05: Benchmark Report Generator + Phase Closeout

Roadmap mapping:
- 3B.4 all bullets
- 3B.5 exit criteria

Planned changes:
- Auto-generate benchmark outputs from artifact store:
  - per-basin metrics table
  - cross-basin summary (median/quantiles/fail count)
  - comparison plots
  - markdown and PDF report outputs
- Add `PHASE_3B_CLOSEOUT.md` with explicit exit-criteria evidence.

Test plan:
- End-to-end validation run on curated subset in CI-compatible mode.
- Assertions for report files and aggregate metrics presence.

Deliberately not done:
- Manuscript drafting beyond generated report artifacts.

## Risks (Phase-specific)

1. Artifact schema churn creates compatibility pain.
   - Mitigation: pin schema versions and add migration notes when fields evolve.
2. Validation runtime may exceed practical CI budget.
   - Mitigation: keep CI smoke subset small and move full suite to scheduled run.
3. Cache correctness bugs could hide regressions.
   - Mitigation: deterministic hash tests plus explicit cache-hit logging assertions.

## Mapping Matrix

- 3B.1 -> PR-3B-01, PR-3B-02
- 3B.2 -> PR-3B-03
- 3B.3 -> PR-3B-04
- 3B.4 -> PR-3B-05
- 3B.5 -> PR-3B-05 (closeout evidence)

