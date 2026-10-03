# Next calibration experiment: predeclared design

Planning date: 2026-10-02. This is an offline protocol proposal drafted before the narrow live integration pilot results were available; the historical labeling note below was added afterward. No settings below were selected from the pilot's outcomes. No efficiency, convergence or superiority claim is made. The pilot remains development evidence, not an unseen-basin evaluation.

## Scientific target and experiment order

First establish whether the opt-in GP reduces expensive evaluations at a fixed, scientifically audited objective in the approximately 14-dimensional governed domain. Compare its **observed admissible best** with bounded DDS and a scrambled space-filling baseline before investing in asynchronous scheduling or transfer learning. Keep the currently proposed raw-KGE objective, finite NSE/KGE/PBIAS checks, explicit calibration-process pass and absolute PBIAS <=30 for the first optimizer-only comparison. Replacing the low-flow metric or process policy is a separate experiment requiring a newly versioned objective; it cannot be counted as an optimizer improvement.

Use one engine worker, the same frozen model and input files per basin, simulation 2007–2015 and training scores 2010–2015. Decide the final held-out verification schedule before acquisition starts. A fresh rerun of the selected candidate over the training simulation and a withheld-period/full-period check are distinct costs and must be reserved explicitly. Predictions cannot authorize promotion. If a basin's forcing does not cover the fixed dates, select a different basin or preregister a different exact common calendar for every method on that basin.

Pilot evidence may repair implementation errors before the next source freeze. It may not be used to select GP settings, favorable basins, favorable seeds or quality thresholds for this experiment.

## A critical limit on sharing existing screen data

The inspected `screen_parameters_against_lock` starts from **no edits**, represented by `{}`, and tests one parameter bound at a time. Its comments explicitly warn that spatially distributed built-model values need not equal scalar registry defaults. Thus a screen record `{PERCO: 1.0}` does not necessarily describe the same simulator state as a 14-parameter vector containing `PERCO=1.0` and thirteen registry defaults. Filling missing entries with defaults would silently change the model and invalidate surrogate training labels.

Reuse requires an exact full-vector representation and proof that the vector recreates the screened model, not just matching dates and source hashes. If other parameters are heterogeneous, use screening for eligibility/group selection only. Acquire a separate explicit common full-vector design for the optimizer. Alternatively, define and validate an optimization parameterization that preserves inheritance/relative adjustment; this changes the domain and needs its own protocol. Do not encode missing edits as zero, or project changing full vectors into a subset while pretending the held-fixed coordinates did not change.

The inspected screening objective also does not enable `include_physical_gate=True`. Its existing metric records therefore do not by themselves supply the explicit candidate process-pass observation required by this proposed policy. Reuse would require retained outputs permitting an auditable gate reconstruction, or a newly specified screen producing complete observations; do not fill the missing gate from an unrelated run or infer it from discharge skill.

Even compatible one-at-a-time points identify marginal responses around one baseline, not interactions. Parameter projection is safe only when excluded coordinates and their full input-write semantics are identical across all used observations. If phase groups overlap and carried-forward parameters change, fit the full vector, refit a model on a genuinely common conditional slice, or decline reuse. Recomputing a phase score from raw metrics is valid only when the scoring window, objective metric version and gate policy match.

## Exact budget feasibility

Use two ledgers: (a) attributed attempted evaluator calls, with all shared acquisition charged to every arm, and (b) physical attempts and confirmed subprocess invocations, recorded separately. A failure before launching a solver is still an attributed attempt and elapsed cost. Cache lookup is not a fresh solver run. Final reserved calls cannot be borrowed by search.

For a total cap `B`, mandatory screening `S`, a distinct compatible initial design `D`, and final reserve `V`, adaptive acquisition gets exactly:

`A = B - S - D - V`.

`D` counts only newly needed design calls; compatible screen observations may reduce it, but rank/representation checks decide compatibility. Reject `A < 0` before launching the workflow. If `A = 0`, report a design-only arm, not an optimizer comparison. Numerical failures reduce usable training rows while still consuming the cap; no free repair calls.

**Current-policy screen arithmetic:** inspected code makes one no-edit baseline request and one request for each endpoint different from the registry scalar default. Therefore `S_requested = 1 + sum(endpoint_requested_i)`, at most `1 + 2m` for `m` screened parameters. The PE1 audit reports 16 screen parameter rows with 30 requested endpoints in the usual case, giving **31 nominal screen requests**. Fourteen *retained* controls do not imply only fourteen screened controls. Historical trace-file counts are not certified physical run counts; recompute the current endpoint list and log each actual attempt before using 31 operationally. The screen API's endpoint shortcut is itself an existing policy, not evidence that the actual heterogeneous baseline equals that endpoint.

The following arithmetic assumes `S=31`, no reusable full-vector screen points, and `V=2` (one fresh training rerun and one held-out/full-period evaluation):

| Total attributed cap | Common 8-point design, adaptive calls | Common 15-point design, adaptive calls |
|---:|---:|---:|
| 30 | infeasible: requires 41 before adaptive search | infeasible: requires 48 before adaptive search |
| 60 | 19 | 12 |
| 120 | 79 | 72 |

An 8-point GP design at 14 dimensions can be fit with regularization, but supplies scant interaction information. The default cubic RBF/linear-tail model needs at least 15 suitably spanning finite observations at 14 dimensions; mere row count is insufficient. A 15-point shared design allows DDS/GP/RBF acquisition to be compared from identical measured initial information. A second comparison may allow algorithm-specific initial designs, but it evaluates the full algorithm, including initialization cost, and cannot attribute differences solely to acquisition.

For an already screened, certified warm-start context (`S=0`), 30 calls leave 20 adaptive calls with an 8-point design or 13 with a 15-point design under the same two-call final reserve. Label this **warm-start acquisition**, not an end-to-end 30-call cold calibration claim. Omission of screening changes the estimand.

Do not force a held-out evaluation when no training-admissible candidate exists merely to spend the reserve. Mark it not reached and record unspent calls. Report success rates and actual consumed cost alongside the nominal cap.

## Source-certified initial method settings

The source currently implements a GP challenger rather than the complete published SCBO algorithm. Freeze the exact source files and dependency versions before the next run; the settings below identify what the present code actually does and do not establish published optimality.

- **Common design:** 15 explicit full-vector points for the DDS/GP/RBF comparison, generated before measurements with a seeded space-filling design. Check distinctness and rank after normalization. Do not use two joint quartile points alone at 14 dimensions: that collinear design cannot support a linear-tail RBF. Any measured initial incumbent is part of the declared design and charged once.
- **DDS:** `r=0.2`, existing coordinate perturbation schedule and bound reflection, one serial request at a time, explicit best admissible initial candidate when available, `budget_is_total=True`. The exact callback cap includes a required seed call if no initial candidate is available. Use the same utility/admissibility functions as GP; do not revert to legacy composite phase utilities in one arm.
- **GP:** CPU double precision; normalized governed bounds; utility maximized; one `SingleTaskGP` for utility and each declared constraint; `ScaleKernel(MaternKernel(nu=2.5))` with a shared lengthscale, `Standardize(m=1)`, fixed per-observation variance `1e-6` before outcome transformation; `fit_gpytorch_mll`; `ConstrainedMaxPosteriorSampling(replacement=False)` selecting one actual next point. Numeric targets include only finite successful measurements with complete constraints. Invalid runs have status and cost, not a made-up extreme utility.
- **GP proposal geometry:** initial trust-region length 0.8; expand after three consecutive observed admissible utility improvements up to 1.6; shrink after `max(4,d)` failures; reset to 0.8 below `0.5**7`. Pool size 256; reserve approximately 10% global candidates; reject candidates within normalized distance `1e-10` of prior measured vectors. Trust-region update before feasibility differs from SCBO's least-violation success update; describe this as the implemented challenger, not canonical SCBO. Failed-only or fewer-than-two-finite histories explicitly use labeled random exploration. Dependency absence must abort before engine acquisition in the GP arm, rather than silently becoming a random arm.
- **Constraints:** volume residual `abs(PBIAS)/30 - 1`; process flag encoded as signed categorical proxy −1 for an explicitly passing observed gate and +1 for a failing gate. This is not a continuous conservation residual or a calibrated admissibility probability. An unknown flag invalidates the observation. Every final candidate is judged against its actual measured policy, irrespective of predicted feasibility.
- **RBF-DYCORS:** optional next comparator, not yet implemented by this work. Pin a tested pySOT release/commit, cubic RBF with linear tail, normalized inputs, serial proposals and a spanning 15-point finite design. Fix its candidate counts, merit weights, radius update and restart policy from the pinned implementation before evaluation; no outcome-dependent defaults. Existing pySOT bound constraints do not automatically implement Builder's process constraints. Predeclare separate surrogate constraint models or a feasibility-first adapter before accepting this arm.

These GP settings are modest engineering choices selected before live results. They have not been optimized for 14-dimensional hydrology. The shared-lengthscale prior trades flexibility for lower variance; anisotropic sensitivity, interactions, discontinuous failure boundaries and multimodal calibration surfaces can make it inadequate. At 256 candidates in 14 dimensions, candidate-pool coverage is sparse. Five failures at two dimensions and fourteen failures at fourteen dimensions imply different shrink behavior; a 19-call adaptive budget may permit little adaptation. Return empty results honestly when no admissible measured candidate emerges.

## Repeated seeds, basin allocation and staged expenditure

Predeclare seeds **42, 55, 68, 81 and 94**, matching the established deterministic seed family without choosing them from the pilot. Pair methods by basin and initial information, not by a claim that equal random seeds imply equivalent stochastic paths. Generate/store design vectors before any objective call. To avoid timing-order confounding, preregister balanced arm order across seed/basin blocks rather than running every DDS arm first.

Start with three development basins chosen by input/runtime and hydrological regime **before seeing challenger scores**: one ordinary admissible case, one near-miss, and one known process/numerical difficulty. Existing exposed PE1 cases remain development evidence. Use cap 60 and five seeds for the two implemented arms; add cap 120 only under a predeclared continuation rule based on engineering feasibility and available compute, not which method appears to be winning. The 30-call cold arm is not feasible under the illustrative current screen cost.

Cost illustration for this 3-basin, 5-seed, 2-arm, cap-60 study: attributed cap is `3 × 5 × 2 × 60 = 1,800` attempted calls. If a deterministic certified 31-call screen is physically shared once per basin, and each paired seed shares its 15-point initial design, maximum physical attempts are `3 × [31 + 5 × (2×60 − 2×31 − 15)] = 738`. This assumes no free retries and that final checks are included in each cap; shorter no-winner arms reduce actual consumption. The attributed workload remains 1,800 for end-to-end cost comparisons even when the experimental infrastructure physically shares setup. A fixed historical screen whose earlier cost cannot be certified cannot be used to assert this exact physical saving.

At an independently profiled median `t` seconds per invocation, reserve approximately `738t` solver-wrapper seconds plus measured optimizer/IO overhead; report a range using per-basin runtime rather than applying a fast small-basin runtime to every case. Do not infer batch wall time by adding overlapping basin times or claim hardware scaling from this arithmetic. Confirmatory evaluation on new basins requires a separately frozen sample and power/precision analysis after development; five seeds and three basins are an engineering pilot, not a general superiority result.

## Overhead and quality reporting

For each arm, separately retain initialization time; each GP fit and posterior-selection duration; objective callback duration; staging, parameter writing, engine/receipt, parsing, metrics and gate times; verification duration; and total monotonic wall time. Existing real-objective telemetry captures several engine-side stages, while the GP wrapper currently does not split fitting from sampling. Add observational timers in a new source version before the next benchmark, preserving proposals; do not reconstruct GP overhead by subtracting overlapping times. Also report summed CPU/resource time when available and peak memory for each method.

GP overhead may be negligible relative to multi-minute engines, or consequential on small projects. Include it in all elapsed-time conclusions. A reduction in engine calls with higher GP overhead is still an evaluation-saving result, but may not improve user turnaround.

Report best admissible training KGE against attributed attempts, physical attempts and wall time; invalid/timeout fractions; no-admissible-candidate frequency; selected parameter boundary use; fresh-training parity; and once-revealed withheld performance. Keep first training-admissible time separate from final independently checked performance. Summarize paired basin/seed differences and censor failures rather than averaging only successful runs. No withheld score is fed back to ongoing optimization or settings.

## Primary references and evidence scope

Checked 2026-10-02:

- [TuRBO primary manuscript](https://arxiv.org/html/1910.01739): local-GP/trust-region rationale; its 14-dimensional control example has a 10,000-evaluation budget, so it does not certify our tiny-budget design.
- [SCBO proceedings](https://proceedings.mlr.press/v130/eriksson21a.html) and [official BoTorch v0.17.0 implementation tutorial](https://botorch.org/docs/v0.17.0/tutorials/scalable_constrained_bo): separate objective/constraint surrogates and constrained posterior sampling. The current Builder challenger intentionally implements a smaller, different region-update scheme.
- [Official pySOT RBF source](https://github.com/dme65/pySOT/blob/master/pySOT/surrogate/rbf.py) and [strategy documentation](https://github.com/dme65/pySOT/blob/master/docs/options.rst): cubic/linear-tail fitting requirements and DYCORS mechanics. These are implementation references, not direct hydrological speedup evidence.
- [BOA, Environmental Modelling & Software 2024](https://doi.org/10.1016/j.envsoft.2024.106191): direct precedent for Bayesian optimization of SWAT+, including a 184-parameter example. Generic GP calibration of SWAT+ is therefore not a new contribution.

All exact budgets above are declared protocol arithmetic, not observations of completed future runs.


## Historical pilot labeling caveat and future correction

After the draft protocol was written, the completed integration pilot revealed a metadata defect: the three supplied incumbent/quartile points were labeled `initial_latin_design` by the GP proposal wrapper. The points were deterministic shared inputs, not a Latin hypercube. Their coordinates and budget attribution, rather than that incorrect method label, identify the experiment. The frozen pilot source and results remain unchanged. Future source now distinguishes `initial_shared_design` for caller-supplied points from `initial_latin_design` for generated stratified designs, with a focused regression check. This metadata correction changes no metric, threshold, candidate location or setting selected from the pilot outcomes.
