# Independent completed-pilot artifact review

Date: 2026-10-02. Read-only review of `runs/calibration_research_20261002/optimizer_pilot_12054000_v1`, importing the exact frozen package in `pilot_source_snapshot_v1`. No engine launched or pilot/history artifact modified during this audit.

Result: **193 checks pass; no artifact-integrity blocker found.** Reproduction script: [pilot_artifact_audit.py](pilot_artifact_audit.py); full machine-readable findings: [pilot_artifact_audit.json](pilot_artifact_audit.json).

Verified frozen source bytes, loaded-source manifest, pilot-script seal, original static inputs, copied static inputs, original observation alignment and benchmark lock; eleven actual successful engine receipts, receipt-bound raw outputs and static inputs; thread setting, engine binary and unique telemetry IDs; complete request attribution; parameter bounds; original output-derived NSE/KGE/PBIAS, selected candidate and fresh rerun equality; process-gate reconstruction and no scoring beyond 2015. The scorer's cache signature was independently rederived from frozen code, engine, static inputs and scored observation identity for each call.

Both arms had six attributed search observations and one fresh selected-candidate rerun. Three shared initial calls were physically executed once and charged to both arms. Eleven physical attempted callbacks correspond to eleven distinct successful engine receipts here; fourteen attributed callbacks preserve each arm's costs. The general telemetry counter remains an engine-wrapper-call measure, including potential failures before subprocess creation.

| Arm | Selected PET_CO | Selected PERCO | Training NSE | Training KGE | Training PBIAS, % | Fresh reproduction |
|---|---:|---:|---:|---:|---:|---|
| DDS | 1.182866230191236 | 1.0 | 0.4245988687750184 | 0.6896228598371872 | 0.24039394050013826 | passed |
| GP | 1.191316128525054 | 0.9974208631432864 | 0.4245438708552426 | 0.6894794869653638 | 0.17903224038994023 | passed |

Each winner was an actual measured, volume-valid/process-valid search point. Both fresh reruns reproduce NSE/KGE/PBIAS to the declared tolerance and remain admissible. These are training-only integration checks, not full-period locked verification or withheld validation; no research-grade promotion follows.

## Timing interpretation

Total serial pilot elapsed was 187.886 s. Sum of evaluator callback intervals was 186.506 s; sum of invocation telemetry totals was 185.539 s. The approximately 0.967 s callback/telemetry difference includes objective construction/fingerprinting and call scaffolding. About 1.380 s outside callback intervals includes GP proposal/model work and orchestration/checkpointing; it is not an isolated GP fitting benchmark.

Across eleven invocation records: engine plus receipt generation 168.634 s; evaluation 15.971 s; input staging 0.715 s; preparation 0.193 s; process-gate checking 0.008 s. Individual callbacks ranged from 15.910 to 20.237 s. Stage sums exclude some bookkeeping, signature construction and trace writing, and engine timing includes hashing/receipt generation. Treating it as pure solver runtime would misattribute costs.

The new evaluator parses each actual output source once per evaluation with a call-local cache; it does not persist parsed data across calls. Existing terminal diagnostics, raw metrics, outlet policies and alignment output remain intact. Unit tests establish equality against the uncached evaluator path for strict, automatic, best-terminal and virtual-sum policies. Candidate fallback sources can retain multiple parsed tables during a single evaluation, increasing temporary memory relative to a single table; no host memory telemetry was retained to quantify this.

## Limits and follow-up

There is no supported GP speed or quality superiority result. This exposed development basin is warm-started, only two controls vary, the seed and budgets are tiny, shared initialization is deterministic, and the arms run in fixed serial order. DDS's slightly higher KGE here is equally insufficient for a general advantage claim. The binary process-pass proxy is categorical, not a continuous conservation residual or failure-probability model. Several interim candidates fail skill policy while remaining calibration-process-valid by the declared protocol; audit logs preserve that distinction.

Before a larger experiment, retain a common cold-start initialization, independent seeds, explicit total costs including screening/final validation, continuous physically meaningful constraint residuals where justified, actual subprocess-start accounting, per-arm model overhead and measured hardware/load. No follow-up optimization default should change based solely on this pilot.
