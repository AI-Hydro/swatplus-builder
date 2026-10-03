# Policy/budget integration, 2026-10-02

The opt-in objective adapter now binds actual training dates and observations
to receipt-sealed engine outputs. A persistent POSIX request ledger charges
cache reuse, failures and unfinished reservations, while protecting fresh
training and temporal-validation requests. These are evaluator-request counts;
engine-wrapper attempts remain distinct from confirmed successful receipts.
Default scoring and DDS remain unchanged.

A frozen-source check on the exposed, already-calibrated 12054000 model passed:
one training engine run, one workdir-cache replay and one forced-fresh training
rerun. All three requests were charged; two successful receipts were retained.
Raw KGE and policy utility were identical at 0.6894085438800555; NSE/PBIAS also
reproduced. The fourth request remains reserved for validation and was unused.
No temporal-validation scores were computed and historical inputs did not
change. This is an integration check, not evidence of calibration improvement.

Root read-only audit passes 318 source, output-receipt, calendar, run-identity
and accounting checks. Independent review additionally passes 311 direct checks,
reconstructs the ledger without changing its bytes, and recomputes both scores
from actual receipt-sealed outputs on 2,191 training days. Compact evidence is in `policy_budget_evidence/`;
raw runs and the 290-Python-file frozen source are under
`runs/calibration_research_20261002/`. Subsequent source adds fail-fast policy
calendar/budget-stage configuration checks; the frozen run remains unchanged.

Preparation also succeeds for 12054000, 01592500 and 03042280: each has 15 explicit
joint points in 14 dimensions, full affine rank 15, and all bridge writes succeed
in temporary copied inputs. Retained active/weak screening controls eligibility
only; its scalar endpoint records are not reused as full-vector measurements.
Omitted registry-default endpoints for EPCO/LAT_TTIME are identified explicitly.
Historical calibrated sources and baseline benchmark identities are separately
sealed; this is warm development preparation, not a fresh end-to-end workflow.
03042280 retains its unresolved nonfinite water-balance history.

The bounded full-vector trial allocates 18 requests per arm: 15 shared design,
one search, one fresh training and one reserved temporal check. One search
request tests integration; it cannot support a convergence or superiority claim.
A reusable paired runner and live CLI now pass independent review; the frozen
12054000 integration trial completes 19 runs under FULLVECTOR_TRIAL_PROTOCOL.md.
See FULLVECTOR_RESULTS.md for metrics, 939 audit checks and interpretation.
The larger repeated-seed/multi-basin benchmark remains unexecuted.

Remaining limitations: ledger locking requires working POSIX flock/fsync;
planned screening/design counts are preflight metadata rather than protected
quotas; the trusted runner must enforce stage authority and fresh-run semantics.
No automatic optimizer replay from interrupted charged ledgers is permitted.
Categorical process-pass residuals are proxies, not continuous conservation
residuals. Full-rank input coverage does not certify physical validity or GP
accuracy. Previously exposed temporal periods cannot become untouched
confirmatory data by relabeling them.
