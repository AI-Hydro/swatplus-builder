# Calibration improvement milestone: results and limits

Date: 2026-10-02. Research, foundation implementation and the bounded live
integration pilot are complete. DDS remains the production reference.

## What changed

Semantic cache fingerprints, atomic publication and in-process single-flight
protect reuse. Invocation telemetry separates cache hits and stage costs.
An opt-in hard search-request budget includes anchors and seed evaluations;
secondary seed attempts are now journaled. Candidates with nonfinite required
metrics cannot become winners through score fallback values. Output evaluation
shares one parsed table without changing outlet policy or diagnostic evidence.

New experimental APIs provide a frozen training-bound objective policy and a
constrained GP ask/tell optimizer. Only observed admissible candidates can win.
Optional dependencies are checked before expensive callbacks. These APIs do
not replace historical objectives or authorize promotion from predictions.

## Validation

- Targeted existing/new regressions: **246 passed, one optional GP test skipped**
  in the system environment. The isolated GP environment passes all **38**
  focused backend/pilot tests, including a real constrained GP proposal.
- Cache smoke test: two fresh training-only runs reproduce exactly; one replay
  avoids the engine call; historical staged inputs remain unchanged.
- Parse-once comparison: exact frames/metrics/diagnostics with two source reads
  reduced to one. Paired elapsed values were 5.085–5.845 seconds without shared
  parsing and 3.114–3.320 seconds with it, on one retained output.
- Live DDS/GP pilot: eleven successful engine runs, fourteen attributed calls,
  187.886 seconds total. Independent audit passes **193/193 checks**, including
  source/input/output hashes, receipt-bound metrics, dates and fresh reproduction.

## What the optimizer pilot found

Previously exposed basin `12054000`; already-calibrated starting model; only
PET_CO/PERCO opened; six attributed search observations per arm; one seed;
simulation 2007–2015 and scoring 2010–2015. This is a narrow warm-started
development experiment, not a full cold-start calibration benchmark.

| Candidate | Training KGE | Training NSE | Absolute PBIAS, % | Fresh training reproduction |
|---|---:|---:|---:|---|
| Shared incumbent | 0.689409 | 0.424611 | 0.114453 | observed shared run |
| DDS selection | 0.689623 | 0.424599 | 0.240394 | passed |
| GP selection | 0.689479 | 0.424544 | 0.179032 | passed |

The pilot demonstrates integration and exact rerun agreement. It provides
**no evidence of GP superiority or meaningful hydrologic improvement**.
Both small KGE gains trade against slightly worse NSE and volume bias. Every
candidate passed the declared volume/process policy, so the run does not test
learning an infeasible region. Some candidates still have negative NSE and
would fail final skill claim gates; process feasibility is not model adequacy.

The three normalized initial points are `(1,1)`, `(0.25,0.25)` and
`(0.75,0.75)`, a rank-one centered design. A GP can fit these observations, but
they do not establish separate parameter effects or interactions. This design
would not initialize a default two-dimensional linear-tail RBF. Future designs
must check spanning rank where required. The frozen pilot's generic method
label says `initial_latin_design`; actual supplied points are explicitly
recorded and deterministic. Future code labels supplied designs correctly;
historical artifacts are preserved.

Across the pilot, engine plus receipt work consumed 168.634 seconds and
evaluation 15.971 seconds. Remaining elapsed includes staging and orchestration.
Earlier smoke calls were much slower; environment/host load and warm state
differ, so their ratio cannot measure a refactor speedup. GP covariance jitter
warnings occurred during the run; source/runtime logs should capture those
warnings and isolated fitting/acquisition costs in the next experiment.

## Next research step

[NEXT_EXPERIMENT.md](NEXT_EXPERIMENT.md) specifies fair full-dimensional budgets
and predeclared seeds. Screen results cannot be imported as full parameter
vectors by filling missing edits with scalar defaults: that changes inherited
spatial values. Required process observations must also be available. A
nominal 30-call cold-start comparison may be infeasible after screening.

Before claiming calibration acceleration, test multiple basins/seeds with
matched scientific policies, explicit initialization costs and untouched
validation, alongside DDS and a rank-sufficient RBF challenger. Separate engine
evaluation savings from hardware elapsed-time savings. Whole-workflow budget
enforcement, cross-process locking, optimizer resume and transformed-policy
engine adapters remain unfinished; no public speedup claim follows yet.

Evidence: [implementation](IMPLEMENTATION.md), [independent scientific review](IMPLEMENTATION_REVIEW.md),
[artifact audit](PILOT_ARTIFACT_REVIEW.md), [audit JSON](pilot_artifact_audit.json).
Full local engine outputs and frozen code remain under
`runs/calibration_research_20261002/`.
