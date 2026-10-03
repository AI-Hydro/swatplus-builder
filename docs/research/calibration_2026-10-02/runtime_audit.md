# Calibration runtime and integrity audit

Date: 2026-10-02. Source checkout: `48f57fe1e65959d226cba3eafc6a001468276275`. PE1 retained runs identify source `0e40463bc4213cfbbddead52522162a294a06abd`. Read-only inspection; no engine launched, historical evidence edited, or production default changed.

## Main finding

DDS is only part of the cost. The current governed path first performs a basin-specific screen, then deterministic anchors and four short DDS phases, then withheld evaluation and independent locked verification. Screening accounts for 300 of 558 retained screen/search trace files (53.8% of trace cardinality, **not** 53.8% of runtime). A method that reduces DDS iterations alone can leave most evaluations untouched. Establish exact invocation/timing accounting before making speed claims.

## Measured PE1 costs

Recomputed from `runs/pe1/batch_summary.csv`, each basin's `events.jsonl`, sensitivity/search `objective_runs/*_objective_trace.json`, and search `history.csv`. Calibration interval is first-to-last `stage=calibration` event. These intervals include screening, search, final evaluation/verification and related diagnostics; they do not isolate DDS or solver execution.

| Basin | Whole workflow, min | Calibration interval, min | Screen trace files | Search trace files | History events |
|---|---:|---:|---:|---:|---:|
| 06718550 | 68.43 | 60.27 | 31 | 23 | 24 |
| 05580000 | 119.65 | 106.40 | 31 | 30 | 31 |
| 09217900 | 29.27 | 20.43 | 31 | 28 | 30 |
| 08057200 | 1.47 | not reached | 0 | 0 | 0 |
| 14216000 | 48.52 | 34.38 | 31 | 30 | 32 |
| 04282650 | 150.24 | 131.27 | 31 | 29 | 30 |
| 12054000 | 22.56 | 15.43 | 31 | 28 | 30 |
| 04159900 | 16.87 | 2.20 | 0 | 0 | 0 |
| 06715000 | 24.45 | 15.95 | 21 | 9 | 9 |
| 14354200 | 62.13 | 49.53 | 31 | 27 | 30 |
| 01592500 | 121.94 | 108.23 | 31 | 28 | 29 |
| 03042280 | 118.55 | 107.08 | 31 | 26 | 29 |

Summed workflow wall time is 47,044.209 s (13.07 basin-hours); summed calibration intervals are 39,071 s (10.85 basin-hours), or 83.05% of summed workflow time. The intervals overlap between basins; these are **not** total batch elapsed times. Median calibration interval over 11 attempted calibrations is 2,972 s (49.53 min), including the 2.20-minute blocked attempt with no traces. Individual duration differences also reflect basin size, forcing/build cost, failure paths and concurrent load.

### Reconciling 593 recorded candidates with 558 traces

The batch column `engine_candidate_evaluations` is a **proxy**, as its implementation explicitly states: [`scripts/decision_data_batch.py:156`](../../../scripts/decision_data_batch.py). It sums phase-decision `candidate_count` and assumes exactly two sensitivity evaluations for every parameter row; it excludes independent verification and other final runs and does not count actual solver process launches.

The exact retained-artifact arithmetic is:

- Batch estimate: **320 assumed sensitivity bound evaluations + 273 primary phase candidate events = 593**.
- Retained trace files: **300 screen traces + 258 search traces = 558**.
- Difference: **(320−300) + (273−258) = 20 + 15 = 35**.
- Every screened basin has 16 parameter rows, giving the estimator 32. Nine have 31 trace files: one no-edit baseline plus 30 bound runs. EPCO and LAT_TTIME each have only one bound because their registry default coincides with a bound (`locked_benchmark.py:1320`). For 06715000, only 21 screen traces remain; its sensitivity report records engine exit 38 for seven parameters, with missing/partial bound results. Neither trace cardinality nor the estimator counts those failures exactly.
- Primary history contains 274 events, including one blocked phase event; phase candidate totals are 273. Across evaluated history rows, 15 parameter vectors repeat within a basin, exactly matching the 273−258 difference. Compact traces use the parameter hash as filename and can be reused or overwritten; they are not a complete invocation log.

Do not label 593, 558 or 273 as exact fresh solver counts. Candidate directories are normally deleted, traces lack per-stage durations, and final engine receipts record sealing time but not elapsed runtime. Some failed solver attempts leave no trace. Actual cache-hit counts and exact solver costs cannot be recovered reliably from these records.

## Current implementation and existing optimizations

1. **Early governed screen and dimensionality reduction.** `diagnostic_calibrator.py:122–175` constructs a training-only six-year screening window, calls `screen_parameters_against_lock`, and retains active/weak/limited controls. `locked_benchmark.py:1289–1380` evaluates the no-edit baseline and lower/upper bounds, with a `ThreadPoolExecutor` for independent bound tasks. Bound skipping depends on registry defaults, although the actual baseline is the spatially distributed built model; changing this shortcut requires scientific validation.
2. **Warm starts and staged objectives.** `locked_benchmark.py:1527` writes a non-authoritative sensitivity-based plan; `:767–825` evaluates up to eight deterministic anchors with bounded threads, then records them in deterministic order. Four phases (`:1702–1757`) are volume, subsurface, peaks/timing and joint finetuning. Search preserves volume/process constraints; physical/skill claim authority remains final verification.
3. **Sequential DDS.** `locked_benchmark.py:1827–1920` generates a proposal around the current best and immediately evaluates it before the next proposal. Naively dispatching that loop concurrently changes the algorithm. Main seed is 42; secondary seeds are deterministic (`:42–47`).
4. **Fresh input-only staging.** `real_engine.py:142–172, :261–267` copies static inputs into isolated candidate directories, edits parameters, launches SWAT+, and excludes recognized generated outputs from copying. Temporary candidate trees are deleted (`:230–235`). No mutable-input hardlinking is used.
5. **Exact-parameter compact trace resume.** `locked_benchmark.py:485–518` enables `reuse_compact_traces=True` for search. `real_engine.py:126–137` returns compatible trace metrics before creating a candidate workdir; `:700–740` verifies signature, parameter identity, requested/actual source and trace payload hash. Replay can reconstruct the deterministic primary search without fresh evaluations for unchanged points. There is no explicit solver-state checkpoint; saved metrics are reused.
6. **Separate withheld and fresh verification runs.** `locked_benchmark.py:1053–1088` runs best parameters across the withheld period. `diagnostic_calibrator.py:234` then calls independent locked verification; do not remove that independent run merely to save time. Search windows are shorter than the full benchmark, but retained warmup can still span years.
7. **One engine thread per objective by default.** `real_engine.py:31` defaults `threads=1`; solver maps this to OMP_NUM_THREADS (`run/swatplus.py:864–875`). PE1 final receipts also record one thread. Candidate worker count and basin batch concurrency therefore compete for the same machine resources.

### Prior runtime experiments already reject two simplistic solutions

The dated progress log (`PROGRESS.md:10373–10393`) records a controlled July 11 experiment, whose scratch directories were removed afterward:

| Change | Recorded elapsed | Baseline | Interpretation |
|---|---:|---:|---|
| Four-worker batch DDS | 584.70 s | serial 583.94 s | No speedup on that machine; code removed |
| Candidate-only minimal print profile | 189.94 s | existing profile 106.02 s | Slower; rejected |
| Exclude stale outputs from staging | 106.02 s | copy-all 110.29 s | 3.9% reduction; metrics identical |

These are recorded historical measurements, not independently rerun measurements here. Roughly 249 MB of stale output was avoided per candidate. Input-only staging is already present, so recommending it as a new speedup would double-count existing work. Rebenchmark parallelism only on a documented hardware/thread/basin configuration.

## Integrity and accounting gaps that acceleration should fix first

### A. Cache identity does not include all semantic dependencies

`real_engine.py:311–358` hashes engine, builder version, `real_engine.py`, parameter bridge and routing fixes. Context (`locked_benchmark.py:2646–2681`) binds benchmark artifacts, static configuration, purpose, outlet and scoring windows. This is a good start, but objective metric/evaluator code (`output/metrics.py`, `output/eval.py`), water-balance gate code and parameter registry semantics are not separately sealed. A change confined to these files without a version increment can reuse old metrics/process-gate decisions. `_load_reusable_objective_trace` requires a gate dictionary when requested but does not recompute that gate under the current implementation. The recent finite-output correction is a concrete reason to version the gate identity, not merely the numerical optimizer.

Recommendation: define a versioned objective context with normalized observation/date digest, static inputs, engine digest, parameter bridge/registry identity, metric formula/version, evaluator/outlet policy and gate formula/version. Separate raw simulation-result identity from scoring/gate identity. A payload hash detects alteration but does not establish semantic freshness or adversarial authenticity. Reject cache hits on semantic identity changes.

### B. Sensitivity/search cache separation leaves potential reuse unexploited

Sensitivity uses a separate root, `purpose="sensitivity_screen"`, and no `include_physical_gate`; search uses `purpose="calibration_training"`, withheld-period slicing, and `include_physical_gate=True`. Current signatures purposely prevent cross-purpose reuse. Simply copying screen metric JSON into search would omit process gates and may change observed-date authority.

A lower-risk future design retains immutable raw discharge series and required water-balance outputs under simulation identity, allowing training-window scoring/process gates to be derived separately. Reuse only when normalized model edits, simulation calendar/warmup, engine and inputs match exactly. Keep final verification force-fresh. Audit actual overlap first: different dictionaries can produce different physical inputs, and warm-start anchors frequently combine several screened changes. A retained-file comparison finds 32 parameter hashes shared between a basin's screen and search roots (2 no-edit vectors and 30 scalar bound vectors): 12.4% of search trace cardinality, or 5.7% of combined screen/search trace cardinality. This identifies a modest reuse target; it does not establish identical simulation identity or runtime savings. No speedup percentage is established yet.

### C. Concurrent identical points can duplicate work and race on trace writes

With `keep_workdirs=False`, run directories are individually unique, but trace filenames are shared parameter hashes (`real_engine.py:126–142, :225–228`). There is no single-flight lock around miss→run→publish, and compact copy publication is not atomic. Parallel workers/request retries can both launch the same point; interrupted publication can leave an invalid trace (loader then misses). `keep_workdirs=True` uses a shared hashed workdir and can remove a directory while a concurrent caller uses it (`:146–153`); do not parallelize that mode without locks.

Recommendation: in-process per-identity single-flight plus atomic trace publication; cross-process locking if the cache is shared. Record each request, cache hit and actual solver invocation separately. Deduplicate anchors before submission without changing their deterministic order/history semantics. This is an inferred race from source; no retained artifact proves a race occurred in PE1.

### D. Declared evaluation budget is not a hard solver budget

`locked_benchmark.py:791–834` evaluates all anchors, then reserves at least one DDS iteration even when anchors consume the phase budget. If no eligible initial best exists, `_dds_search` adds a seed evaluation (`:1880–1893`) before the loop of `budget` iterations (`:1895`). The current default requests 30 evaluations (`locked_benchmark.py:392`); equal integer division allocates seven to each of four phases, nominally 28. That allocated primary protocol yielded 29–32 history events in several PE1 basins. These events can hit cache, so excess events do not necessarily imply excess solver launches.

Recommendation: explicitly distinguish proposal budget, unique fresh-solver budget, cached evaluations and per-phase minimums. Maintain backward-compatible DDS behavior by default; expose a new versioned hard-budget mode for algorithm comparisons, reserving full verification separately. Test budgets smaller than anchor count, no feasible anchors and skipped phases.

### E. Multi-seed refinement is neither a fixed-budget split nor fully logged

`locked_benchmark.py:988–1039` runs secondary seeds serially **after** the full primary search. Each seed receives additional budget; the comment saying divide primary budget is misleading. Secondary search calls `evaluate=objective` directly rather than `_evaluate_and_record`. It writes compact traces, but no secondary evaluation history/progress rows. The phase-decision comment (`:1694–1696`) saying their evaluations are in history is incorrect for this implementation.

Recommendation: add explicit seed/stage identity to history, enforce a stated total fresh-solver budget, and independently verify the final selected point. Parallel independent seeds may be suitable on larger hardware, but their total cost is larger than one DDS search. A stochastic ensemble is not automatically a faster calibrator.

### F. Accelerating the existing objective can optimize an unstable criterion

`locked_benchmark.py:2124–2193` prefers `log_kge_v2` in joint and baseflow scores. The current paper's correction artifact demonstrates that its basin-relative epsilon does not remove log-KGE's unit-dependent mean-ratio problem. `output/metrics.py:163–203` itself notes the unresolved mean-of-log issue. Version/correct the low-flow objective before using new searches to generate research labels. Missing/non-finite log-KGE contributes a neutral zero bonus (`locked_benchmark.py:2155–2157`), although NSE/KGE/PBIAS are checked in the primary wrapper (`:2308`). Decide explicitly whether a configured objective requires its low-flow term; avoid silent ranking changes when that term cannot be evaluated.

### G. Output parsing repeats work

`output/eval.py:150` reads selected-outlet discharge; when a requested outlet is non-terminal, `:167–203` computes best terminal NSE even for strict policy, though strict policy cannot select that alternative. With diagnostics, `:257–263` calls terminal-scope diagnostics, whose `:296` rereads the full daily table, then recomputes selected/all-terminal metrics (`:322–337`). Each objective also writes alignment CSV to a temporary directory deleted immediately (`real_engine.py:179, :234`). A parse-once pathway and optionally suppressing disposable alignment CSV can reduce Python/I/O work while preserving authoritative source/outlet diagnostics. Its contribution to elapsed time is **unmeasured**. Do not remove terminal closure/process diagnostics or receipt hashing on assumption that they are expensive.

## Recommended implementation order

1. **Read-only telemetry and objective contract first.** Add a per-request/invocation record with cache status, seed/phase, identity, and monotonic durations for stage/copy/edit, solver, receipts/hash, parsing/scoring, process gates and cleanup. Record CPU/RAM, worker budget, engine threads and basin concurrency. Ensure crash/cancel rows and source hashes are retained. Correct/version low-flow objective before comparing search performance.
2. **Fix cache semantics/accounting under existing DDS.** Semantic dependency fingerprint, finite/configured-objective checks, atomic single-flight publication, exact invocation counts, and secondary-seed trace/history coverage. Regression acceptance: unchanged primary DDS points/results on stable fixtures, cache invalidates when metric/gate code changes, simultaneous identical requests launch once, final verification stays fresh.
3. **Reduce evaluator overhead without changing science.** Parse once, skip best-outlet scans under strict policy unless explicitly requested for diagnostics, retain all required terminal/process evidence, and avoid disposable alignment file writes when no consumer needs them. Compare full metric/diagnostic output equality and measured stage costs on one small and one large locked basin.
4. **Opt-in shared simulation cache and budget policy.** Retain compact discharge/process output bundles to reuse exactly identical screen/search simulations; rederive scoring using a locked observation digest. Add explicit hard fresh-solver budget and controlled adaptive screen/anchor budget as new protocol versions. Current basin-specific core-sensitivity governance must still be satisfied; no skipping mandated probes without defining and validating a revised evidence contract.
5. **Compare alternative candidate strategies through a common evaluator.** Give staged DDS, an adaptive surrogate strategy and another robust optimizer identical total fresh-engine/time budgets, the same training-only observations, parameter constraints, process gates, seed replicates and fresh verification. Screening cost belongs inside each method's total budget. Stop structural/forcing/outlet failures by explicit diagnostics rather than exhausting another optimizer.
6. **Then test hardware concurrency and optional fidelity reduction.** Tune a global token budget across basins, candidate workers and engine threads; do not stack them blindly. Shorter calibration windows or warmup periods are method changes requiring hydrologic state/transfer validation, not generic execution optimizations. Surrogates must propose real candidates; final physical/process and withheld evidence must come from SWAT+.

The strongest defensible immediate improvement is better accounting and safe reuse, followed by reducing **new engine evaluations**, rather than assuming DDS's Python loop is the runtime bottleneck. No speedup, convergence improvement or new basin promotion is claimed by this audit.
