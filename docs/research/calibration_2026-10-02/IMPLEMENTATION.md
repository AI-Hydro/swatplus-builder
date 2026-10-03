# Calibration foundation implementation and live check

Date: 2026-10-02. Status: foundation implemented; experimental challenger remains opt-in.
The research-only recommendations in the earlier notes are historical; this
file records the subsequent user-authorized implementation and new evidence.

## Implemented

- `real_engine.py`: semantic identity binds scored observations, staged inputs,
  engine/thread settings and metric/evaluator/parser/gate/parameter code. Atomic
  trace publication and in-process per-path single-flight avoid concurrent
  duplicate work. Per-call telemetry is wired into locked search, screen,
  validation and verification callers.
- `locked_benchmark.py`: optional hard **search objective-request** cap includes
  anchors and seed points. It excludes screening and final verification; it is
  not a whole-workflow solver cap. Invalid required metrics are retained as
  failure evidence but cannot be selected through score fallbacks. Secondary
  seeds have an append-only journal with search-attempt and seed/phase identity.
- `objective_policy.py` and transformed metric helpers: explicit, frozen,
  training-bound weights/epsilon and finite constraint observations. Historical
  metric formulas remain replayable; no new default objective is adopted.
- `surrogate_optimizer.py`: serial constrained GP ask/tell, bounded shared
  design, typed finite observations/failures, measured admissible winner,
  explicit dependency preflight and optional labeled random fallback.
- Optional `surrogate` extra pins BoTorch 0.17.0 and GPyTorch 1.15.2. This extra
  needs Python >=3.11 although the base Builder supports Python 3.10. It stays
  outside default/all installs. PyTorch is CPU-capable and comparatively large.

## Validation completed

System environment: **162 passed, 1 skipped** in the targeted existing and new
DDS, locked, real-engine, cache, objective, metric and surrogate tests. The
skipped test is the optional real GP proposal. In a separate temporary GP
environment, **all 16 surrogate tests pass**, including that actual proposal.
The test environment uses Python 3.13, BoTorch 0.17.0, GPyTorch 1.15.2 and
PyTorch 2.14.1; compatibility with other resolved stacks is not established by
these checks. Production dependencies were not installed or replaced.

Live evaluator smoke test: one exposed PE1 development model (`12054000`),
using copied already-calibrated inputs. Simulates 2007–2015 and scores
2010–2015 only. Two fresh executions and one compact-cache replay pass metric
equality checks; source staged-input digest stays unchanged. Fresh NSE is
0.4246114371, KGE 0.6894085439, PBIAS 0.1144527145%. This is **not** a new
calibration result, improvement experiment, full-period verification or promotion.

| Call | Total seconds | Engine plus receipt | Evaluation |
|---|---:|---:|---:|
| First fresh | 140.969 | 125.493 | 13.759 |
| Compact replay | 0.002216 | no engine wrapper call | cached |
| Forced fresh | 116.297 | 88.147 | 27.357 |

Timing variation is substantial and two calls cannot establish a speedup.
Telemetry counts `run_swat` wrapper calls rather than proving process launches,
and engine timing includes receipt generation. Cache replay timing illustrates
this exact repeated point only; it does not predict whole-search savings.

Local evidence: `runs/calibration_research_20261002/evaluator_smoke_12054000/`.
The manifest binds engine, input and observation hashes; invocation records
retain stage durations and status. Reproduction script:
`scripts/research/calibration_evaluator_smoke.py`. Historical PE1 evidence and
source model remain unchanged. No remote push or public performance claim.

## Remaining work

Parse-once evaluation and the narrow DDS/GP pilot are now complete; see
`RESULTS.md` and `PILOT_ARTIFACT_REVIEW.md`. Source was frozen before execution.
The pilot uses a versioned raw-KGE objective and observed volume/process
admissibility. Shared acquisition is counted physically once and charged to
each arm; both selected candidates reproduce in fresh training-only runs.
It is not the proposed full-dimensional cold-start 60/120-call benchmark.

Cross-process cache locking, exact process-launch census, durable optimizer
checkpoint/resume, full engine adapters for transformed objective policies,
whole-workflow budget enforcement, cross-purpose raw simulation reuse,
full-dimensional RBF comparisons and multi-basin efficiency experiments remain
unfinished. The experimental APIs must not authorize production claims on
surrogate predictions or relax existing final verification gates.

## Parse-once result

The evaluator now uses a call-local parsed table for outlet selection and
terminal diagnostics. Seven targeted tests preserve exact frame, metrics,
diagnostics and alignment bytes across five outlet-policy cases, fallback
sources and modified outputs. Together with the relevant reader, gate and
budget/policy checks, 109 tests pass. Each new evaluation still reads current
output; there is no cross-call dataframe cache.

A paired test on retained `12054000` output, scoring training dates only,
gave uncached timings 5.845/5.085 seconds and shared-table timings 3.320/3.114
seconds. Source reads fell from two to one and frames/metrics/diagnostics were
exactly equal. This is a narrow evaluator measurement; neither the earlier
live 14–27-second stage timings nor this warmed-file comparison establish a
whole-workflow or optimizer speedup. See `parse_benchmark.json` and
`scripts/research/calibration_parse_benchmark.py`.
