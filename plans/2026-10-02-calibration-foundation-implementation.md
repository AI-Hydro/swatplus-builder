# Calibration foundation implementation — 2026-10-02

Authorization: user requested the research team continue implementation autonomously.
Scope: the foundation recommended by the preceding research, with an optional
surrogate prototype and bounded live evaluator smoke test. No optimizer default
switch, process-gate relaxation, public push or performance superiority claim.

Team ownership:

- Runtime engineer: semantic cache identity, in-process single-flight, atomic
  publication, optional per-call telemetry and focused tests.
- Hydrology researcher: opt-in training-bound objective policy, transformed NSE
  metrics, explicit finite/zero/constraint handling and tests.
- Optimization researcher: constrained GP ask/tell with lazy optional imports,
  shared initial design, finite exact observations and proposal limits.
- Research lead: hard search-request cap, secondary-seed journaling, caller
  telemetry integration, independent review and live evaluator smoke test.

Validation: existing DDS/locked/evaluator/metric regressions, targeted new tests,
real GP proposal in an isolated optional-backend environment, then two fresh
training-only runs and a cache replay on one exposed development basin.

Independent review adds: reject partial nonfinite skill before ranking, reject
invalid explicit phase budgets, identify secondary attempts separately, and
preflight GP imports before any expensive callback. The search cap is a request
cap, not a whole-workflow solver cap; screening/verification remain separately
charged. Interfaces remain experimental until full engine-policy adapters and
fair multi-basin optimizer experiments are implemented and verified.
