# Full-vector development integration results

Reviewed 2026-10-03. Trial artifacts retain their 2026-10-02 experiment identity.
Protocol: [FULLVECTOR_TRIAL_PROTOCOL.md](FULLVECTOR_TRIAL_PROTOCOL.md).

The frozen 14-parameter, one-basin, seed-42 trial completed 19 successful engine
runs in 345.569 seconds. The 15-point explicit shared design has affine rank 15;
all 15 measured design observations remained finite and process/volume-admissible.
Each arm received one further search request and a fresh training rerun of its
measured selection. Both reproduced exactly. Each ledger charged 17 of its 18
requests, leaving temporal validation reserved and unscored; total attribution
was 34. The 15 GP reuse events are experimental sharing, not additional solver
runs or a production cache speedup.

| Training result | NSE | KGE | PBIAS (%) |
|---|---:|---:|---:|
| Unedited warm source, separate verified smoke | 0.424611 | 0.689409 | +0.114453 |
| Best shared design / DDS selection | 0.064073 | 0.568995 | +4.391062 |
| GP search selection | 0.415170 | 0.717039 | +5.176658 |

DDS's single search request did not improve the shared incumbent. GP's single
posterior-sampled proposal increased measured KGE by 0.148044 over that shared
incumbent. Against the separately evaluated unedited source with the same input
identity, GP increased KGE by 0.027630 while reducing NSE by 0.009441 and increasing
absolute PBIAS by 5.062205 percentage points. This is a metric tradeoff, not a
uniform hydrologic improvement. The unedited source is descriptive: it was not
encoded as a complete scalar vector or supplied as an optimizer observation.
Explicit scalar overwrite of all 14 controls defines the trial domain; it need
not reproduce the heterogeneous unedited configuration.

Fourteen of the 17 physical design/search evaluations have negative NSE while
passing the declared process/volume constraints. Finite objective observations
and process admissibility are separate from scientific skill and claim gates.
Negative skill remains blocked by claim governance. This trial makes no model
promotion, research-grade claim or temporal-transfer claim.

## Accounting and implementation evidence

The actual GP proposal used 15 finite observations and the declared constrained
GP Thompson method. Proposal time was 1.2021 seconds, including 1.0788 seconds
of model fitting, 0.0066 seconds of candidate generation and 0.0427 seconds of
posterior sampling. Remaining time includes measured orchestration; these
subcomponents do not exhaust total proposal time. No proposal warning was
captured. A dependency initialization FutureWarning printed outside proposal
warning capture; it is not a model-fitting warning. Do not treat warning-free
proposal records as complete capture of every process warning.

Summed callback time was 343.8160 seconds; engine-and-receipt stages summed
309.3940 seconds and evaluation stages 29.0477 seconds. Median invocation time
was 17.9585 seconds. These are costs of this integration trial, not a paired
turnaround-speed comparison. Shared design, fixed DDS-first ordering, only one
adaptive request and an exposed calibrated basin prevent an efficiency claim.

The read-only artifact audit passes 939 checks, re-evaluating all 19 actual
output sets, recomputing process gates, verifying output/static/code/engine
hashes and exact scoring provenance, replaying both ledger chains, reconciling
attribution, checking measured winners and fresh parity. Prelaunch code review
was independent. The reviewer authored the post-run audit script; the primary
agent executed it. A separate completed second-agent post-run review is absent.

Compact artifacts: [fullvector_trial_evidence](fullvector_trial_evidence/).
Audit: [fullvector_trial_audit.json](fullvector_trial_audit.json), reproduced with
`fullvector_trial_audit.py` and the frozen package. Complete inputs/outputs/source
remain under `runs/calibration_research_20261002/`. Original PE1 inputs did not
change. Final focused regressions: 275 passed, one optional-backend skip;
87 isolated GP/design/runner/CLI tests passed. No remote push.

## What remains before calibration performance claims

- Run the predeclared contrasting development cases and repeated seeds under
  meaningful adaptive budgets, preserving failures and identical initial
  information. Include a space-filling-only baseline so random-design quality
  is distinguishable from optimizer benefit.
- Exercise process/volume-infeasible regions; all observations here satisfy
  those constraints, so constraint-learning effectiveness remains untested.
- Define and verify any parameterization intended to include the distributed
  unedited incumbent; do not fill missing values with scalar defaults.
- Select objective weights from the scientific purpose in a separate protocol.
  Raising KGE alone cannot be claimed to improve NSE, bias, extremes or low flows.
- Use temporal evaluation only after all acquisition/settings are frozen.
  Previously exposed PE1 periods are development transfer evidence; new basins
  and genuinely untouched evaluation data are needed for confirmatory claims.
- Preflight storage and preserve verified archives before larger studies; the
  19-run full-vector tree alone occupies about 3.3 GiB. Do not delete outputs
  that are still the authority for re-scoring and gate reconstruction.
- Retain total attributed costs, physical receipts, overhead and fresh checks.
  Ledger stage labels depend on a trusted runner; automatic interrupted
  optimizer resume and cross-process objective-cache exclusion remain unsupported.

DDS remains the production default. The result supports an executable,
auditable comparison infrastructure and a promising individual GP proposal;
it does not establish a superior calibration strategy.
