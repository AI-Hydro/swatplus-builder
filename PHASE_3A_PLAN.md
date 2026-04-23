# Phase 3A Plan — Hardening

Date: 2026-04-23
Roadmap reference: `ROADMAP.md` -> Phase 3A (3A.1 through 3A.5)
Status: Active

## Scope

Deliver all Phase 3A items in order:

1. CI Routing Regression Gate (3A.1)
2. Evaluation Metadata Persistence (3A.2)
3. Soil Realism Flags (3A.3)
4. Large Basin Guardrails (3A.4)
5. Demonstrate Phase 3A exit criteria (3A.5)

No Phase 3B artifact store implementation in this phase except compatibility hooks needed to avoid rework.

## PR Decomposition (mergeable in isolation)

### PR-3A-01: CI Routing Regression Gate

Roadmap mapping:
- 3A.1 all bullets

Planned changes:
- Add deterministic regression harness for 2-3 representative basins.
- Add assertions:
  - engine run success
  - terminal channel flow > 0
  - alignment output file exists
  - outlet auto-detection path validated by test fixture
  - baseline metric floor NSE > -1
- Wire to GitHub Actions with explicit timeout budget and clear failure output.

Test plan:
- New pytest integration marker for routing regression suite.
- Local dry run on selected basins.
- CI workflow run on branch validates gate behavior.

Deliberately not done:
- Full curated basin suite for Phase 3B.
- Artifact store hashing/caching logic (Phase 3B).

### PR-3A-02: Evaluation Metadata Persistence

Roadmap mapping:
- 3A.2 all bullets

Planned changes:
- Define `metadata.json` schema (pydantic model).
- Persist metadata per run with:
  - selected outlet GIS ID
  - outlet auto-detection flag + selection reason
  - routing mode
  - soil mode + fallback percentage
  - engine version + code SHA
  - input dataset hashes
  - weather source + coverage flags
- Add CLI: `swat inspect <run_id>` to display metadata.

Test plan:
- Unit tests for schema validation and serialization.
- Integration test that run outputs include complete metadata.
- CLI test for `swat inspect`.

Deliberately not done:
- Artifact store object model and lineage graph (Phase 3B).

### PR-3A-03: Soil Realism Flags

Roadmap mapping:
- 3A.3 all bullets

Planned changes:
- Add unified soil realism fields:
  - `soil_mode`: `high_fidelity | fallback | synthetic`
  - `pct_fallback_soils`
- Add configurable warning threshold default 25%.
- Propagate flags to generated plots as visible annotation/watermark.
- Update docs for soil fidelity semantics.

Test plan:
- Unit tests for mode classification and percentage calculation.
- Plot generation tests asserting annotation present when fallback triggered.

Deliberately not done:
- Soil algorithm redesign.

### PR-3A-04: Large Basin Guardrails

Roadmap mapping:
- 3A.4 all bullets

Planned changes:
- Pre-engine checks for `n_subbasins` and `n_hrus`.
- Configurable thresholds with CLI flags:
  - `--max-hrus`
  - `--max-subbasins`
- Behavior:
  - warning + suggested auto-adjust
  - explicit fail-fast when adjustment disabled

Test plan:
- Unit tests for threshold decision logic.
- Integration tests with synthetic metadata exceeding thresholds.

Deliberately not done:
- Full scalable delineation redesign.

### PR-3A-05: Phase 3A Closeout

Roadmap mapping:
- 3A.5 exit criteria

Planned changes:
- Validate and document all exit criteria.
- Add `PHASE_3A_CLOSEOUT.md` with evidence links.

Test plan:
- CI green with routing regression gate active.
- Manual verification checklist captured in closeout.

## Risks (Phase-specific)

1. External data/network dependencies can create CI flakiness.
   - Mitigation: keep CI basin set small; pin inputs; add retries and strict timeout handling.
2. Runtime budget pressure for PR validation.
   - Mitigation: split smoke vs heavier scheduled jobs if needed while preserving required gate coverage.
3. Existing roadmap file-location inconsistency (`docs/ROADMAP.md` vs root `ROADMAP.md`).
   - Mitigation: resolve links in PR-3A-01/housekeeping before adding further docs references.

## Mapping Matrix

- 3A.1 -> PR-3A-01
- 3A.2 -> PR-3A-02
- 3A.3 -> PR-3A-03
- 3A.4 -> PR-3A-04
- 3A.5 -> PR-3A-05

