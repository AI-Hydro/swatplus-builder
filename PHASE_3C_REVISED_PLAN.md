# Phase 3C Plan — Revised (pySWATPlus Integration)

Date: 2026-04-23  
Roadmap authority from this point: `CALIBRATION_PLAN_REVISED.md` (supersedes prior Phase 3C plan)  
Status: Active

## Scope

Execute revised Phase 3C in order:

1. 3C.1 Dependency integration (`pySWATPlus >= 1.3.0` + verified companions)
2. 3C.2 Parameter registry enhancement for pySWATPlus compatibility (`change_type`, conversion helpers)
3. 3C.3 Build→Calibrate bridge (`Calibrator` wrapper + artifact integration)
4. 3C.4 Sensitivity bridge (`swat sensitivity` wrapper over pySWATPlus SALib path)
5. 3C.5 Diagnostic layer rules (SWATdoctR-inspired concepts, typed outputs)
6. 3C.6 Calibration presets (`quick`, `standard`, `thorough`)
7. 3C.7 Exit-criteria proof + closeout

## PR Decomposition (mergeable)

### PR-3C-R1: Dependency + Licensing Guardrails (3C.1)

Planned:
- Update dependency target to `pySWATPlus>=1.3.0`.
- Track verified companion deps (`pymoo`, `SALib`) in optional calibration extra.
- Add runtime availability/version checks with clear failure guidance.
- Add integration-test scaffold (skip when optional deps are absent).
- Record licensing decision context and unresolved legal choice.

Test plan:
- Unit tests for missing/available dependency behavior.
- Opt-in integration test marker for real pySWATPlus runs.

### PR-3C-R2: Registry Compatibility Layer (3C.2)

Planned:
- Extend `Parameter` model with `change_type` and `physical_meaning`.
- Add conversion helpers: `to_pyswatplus_dict`, `to_pyswatplus_bounds_dict`.
- Keep existing typed validation behavior.

Test plan:
- Registry validation + conversion output schema tests.

### PR-3C-R3: Calibrator Bridge (3C.3)

Planned:
- Add `swatplus_builder.calibration.Calibrator` wrapper over pySWATPlus calibration API.
- Connect build outputs (`TxtInOut`) to calibration execution.
- Persist calibration-level and evaluation-level artifacts with content-hash caching.
- CLI extension: `swat calibrate` pySWATPlus-backed modes (GA/DE/NSGA2).

Test plan:
- Mocked pySWATPlus wrapper tests for artifact writes and CLI wiring.
- Opt-in real integration run (small generations/population).

### PR-3C-R4: Sensitivity Bridge (3C.4)

Planned:
- Add sensitivity wrapper and `swat sensitivity` CLI.
- Persist Sobol indices + ranked report artifacts.

Test plan:
- Unit tests with mocked analyzer outputs.

### PR-3C-R5: Diagnostics + Presets + Closeout (3C.5–3C.7)

Planned:
- Implement typed diagnosis rules.
- Add calibration presets and override semantics.
- Produce exit-criteria evidence and `PHASE_3C_CLOSEOUT.md`.

Test plan:
- Rule-engine tests over synthetic symptom cases.
- End-to-end basin calibration artifact checks.

## Risks

1. Licensing conflict risk (`MIT` project vs `GPL-3.0` dependency).
2. pySWATPlus API drift between releases.
3. Runtime cost for real calibration integration tests.

## Current Handling

- Treat pySWATPlus as optional integration dependency (extra).
- Keep import boundary narrow and lazy; fail loudly with guidance when missing.
- Defer any irreversible license change until explicit human approval.
