# Phase 3E Plan — Packaging & Distribution

Date: 2026-04-24  
Roadmap reference:
- `ROADMAP.md` -> Phase 3E (3E.1 through 3E.4)  
Status: Active (kickoff)

## Scope

Deliver Phase 3E in mergeable slices:

1. Containerization baseline (Dockerfile + runtime verification).
2. CLI polish and consistency hardening.
3. Documentation + example upgrades for install/run/calibrate/diagnose workflows.
4. Release/readiness closeout evidence.

Non-goals in this phase:

- No roadmap reordering or new feature surface beyond packaging/distribution.
- No Phase 3F physical-fidelity expansion.
- No architectural refactor of calibrated routing/agent-loop internals.

## PR Decomposition (mergeable in isolation)

### PR-3E-01: Container Baseline

Roadmap mapping:
- 3E.1 all bullets (initial baseline)

Planned changes:
- Add project Dockerfile with:
  - Python runtime + package install,
  - SWAT+ engine bootstrap hooks,
  - required runtime env defaults.
- Add smoke command in container context to verify `swat --help` and `swat version`.
- Add container usage docs section in README.

Test plan:
- Build image locally.
- Run container smoke commands.
- Verify mounted workspace execution path for `swat validate` dry/smoke mode.

Deliberately not done:
- Multi-arch publishing automation (handled in PR-3E-04 release prep).

### PR-3E-02: CLI Polish + Contract Hardening

Roadmap mapping:
- 3E.2 all bullets

Planned changes:
- Ensure top-level CLI help and subcommand docs are consistent.
- Normalize option naming and failure messages where inconsistent.
- Verify subcommand surface includes latest roadmap commands (`run`, `validate`, `calibrate`, `inspect`, `diagnose`, `sensitivity`, `mcp`).
- Add/refresh CLI integration tests for user-visible behavior.

Test plan:
- Targeted CLI pytest suite.
- Snapshot/contains assertions for command help text and key error paths.

Deliberately not done:
- New command families beyond roadmap scope.

### PR-3E-03: Documentation + Examples Distribution Readiness

Roadmap mapping:
- 3E.3 all bullets

Planned changes:
- Update README quickstart for current stabilized pipeline.
- Add explicit install matrix (`core`, `mcp`, `swatplus`, `all`).
- Add concise example commands for:
  - validation,
  - calibration presets,
  - diagnostics,
  - MCP launch.
- Align docs with root canonical roadmap/progress/decisions references.

Test plan:
- Link/path checks for referenced files and commands.
- Run minimal documented command set in local smoke mode.

Deliberately not done:
- Large narrative tutorial expansion (defer to backlog if needed).

### PR-3E-04: Phase 3E Release-Readiness & Closeout

Roadmap mapping:
- 3E.4 all bullets

Planned changes:
- Add `PHASE_3E_CLOSEOUT.md` mapping each 3E exit criterion to evidence.
- Capture reproducible verification commands and outputs.
- Add release checklist note (versioning, changelog, publish steps).

Test plan:
- Re-run core verification bundle from closeout doc.
- Confirm docs and CLI examples match actual command behavior.

Deliberately not done:
- Production publish unless explicitly requested by user.

## Risks (Phase-specific)

1. Container drift from local runtime behavior.
- Mitigation: pin versions where practical and include container smoke tests.

2. CLI churn that breaks scripts/agents.
- Mitigation: preserve command compatibility and enforce with integration tests.

3. Documentation lag behind implementation.
- Mitigation: docs updates required in each PR, not deferred to end.

4. Scope creep into Phase 3F.
- Mitigation: defer physical-fidelity enhancements to `BACKLOG.md` unless roadmap mandates.

## Mapping Matrix

- 3E.1 -> PR-3E-01
- 3E.2 -> PR-3E-02
- 3E.3 -> PR-3E-03
- 3E.4 -> PR-3E-04
