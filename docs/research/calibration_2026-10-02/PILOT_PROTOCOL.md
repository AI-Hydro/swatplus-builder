# Narrow live optimizer integration pilot

Predeclared before executing optimizer candidates, 2026-10-02.

Purpose: establish that exact engine observations, bounded DDS search and the
optional constrained GP can operate under matched search-request accounting.
No method superiority, general convergence or publication-ready efficiency
claim can follow from this one-basin, one-seed, two-parameter experiment.

Development case: PE1 `12054000`, using its already-calibrated retained input
model. This basin and its outcomes are exposed development evidence. It is a
warm-started experiment, not the proposed cold-start workflow benchmark.

Scientific settings:

- Copy input model into a new isolated pilot directory; freeze source before
  launch and record input, engine, observation and source digests.
- Engine threads: one; no concurrent candidate engines. Timeout: 300 seconds
  per attempt, recorded as a failed attempt if exceeded.
- Simulate 2007–2015; score observed 2010–2015 only. No scoring or selection on
  dates after 2015 and no changes to historical model/evidence directories.
- Open only `PET_CO` and `PERCO` within governed full-mode registry bounds.
  Keep all other inputs from the retained calibrated model.
- Utility: raw KGE, maximized; require finite NSE/KGE/PBIAS, absolute PBIAS <=30,
  and an explicitly observed passing candidate calibration process gate. No
  log-KGE utility or new gate relaxation. Missing gate is unavailable, not pass.
  GP receives the observed process flag as a signed categorical proxy
  (−1 for passing, +1 for failing), not a continuous conservation residual.
  Exact observed admissibility always governs selection.
- Three shared initial candidates: the retained incumbent's two parameter
  values and the joint 25%/75% positions within governed bounds. Seed 42 controls
  subsequent proposals; this design is deterministic, not Latin hypercube.
  Each arm is attributed all three acquisition calls;
  the physical project total counts this shared acquisition once.
- DDS: three additional objective requests, including any required seed; GP:
  three additional proposals after importing the initial observations. Both
  arms therefore have six attributed search requests. Preserve actual attempts,
  statuses, cached calls (if any) and engine-wrapper calls separately.
- Rerun each arm's final measured admissible winner force-fresh once. No winner
  means no fabricated final candidate. Maximum physical request count is 11;
  maximum attributed cost is seven per arm including final checking.

Evaluation:

- Report every request and failure, selected measured parameters/utility,
  final fresh metric agreement and process status, and measured stage times.
- GP dependencies preflight before any expensive callback. Predictions never
  substitute for an engine observation or establish a promoted claim.
- Fixed serial arm order is a timing limitation. Model fit, filesystem state
  and host load affect elapsed cost; do not declare a winner from this timing.
- Final checking here is a training-only integration check, not canonical
  full-period verification or withheld transfer. No promotion is authorized.

After the pilot, revise only engineering problems using this development
evidence. Freeze objective, basins, initialization, budgets, seeds and quality
tolerances separately before the multi-basin confirmatory experiment.
