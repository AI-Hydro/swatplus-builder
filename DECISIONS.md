# Decisions

This file is append-only. Supersede old decisions with a new dated entry.

## 2026-05-12 — Canonical Workflow Owns Scientific Claims

Decision:

- `swat workflow run` is the only path allowed to emit final claim-tier,
  blocker, calibration, and evidence-bundle decisions.

Why:

- Ad hoc scripts can help execute benchmark sweeps, but if they define claim
  tiers or final calibration status, the package stops being the scientific
  authority and agents can overclaim from partial artifacts.

Consequences:

- Scripts may aggregate `evidence_summary.json`.
- Scripts must not create independent research-grade verdicts.
- Missing canonical evidence is a pipeline failure, even if a basin metric looks
  good.

## 2026-05-12 — Research-Grade Requires Runtime Contract And Standard Window

Decision:

- `research_grade` and `publication_grade` workflow claims require an accepted
  or executed contract accepted by `user` or `policy`, a multi-year modeling
  window, and sufficient warmup.

Why:

- Short one-year simulations can be useful diagnostics, but they are not enough
  for defensible SWAT+ research claims.

Consequences:

- Missing or draft contracts downgrade high-tier requests.
- Short windows downgrade high-tier requests.
- The workflow must record the downgrade as a blocked claim, not silently
  continue.

## 2026-05-14 — Final Skill Selector Prioritizes KGE After Positive NSE

Decision:

- For `maintain_volume_gate_then_rank_nse_kge`, the locked calibration selector
  prioritizes KGE once NSE is nonnegative. Negative-skill candidates still use
  the previous NSE-first ranking.

Why:

- KGE is the explicit research-grade skill gate. Once a candidate has crossed
  out of negative NSE, choosing a small NSE gain over a material KGE
  improvement can move the accepted locked solution away from the governed
  claim criterion.

Consequences:

- The selector still cannot promote a claim by metric ranking alone; physical,
  routing-flow, sensitivity, calibration-verification, soil-fidelity, and
  hydrograph evidence must pass.
- `01654000` now selects the higher-KGE LAT_TTIME candidate
  (`NSE=0.044`, `KGE=-0.026`, `PBIAS=-24.41`) instead of the prior higher-NSE
  but lower-KGE candidate (`NSE=0.053`, `KGE=-0.082`, `PBIAS=-29.55`).

## 2026-05-14 — Routing Closure Keeps Conservative Reference But Records Scope Ambiguity

Decision:

- Do not switch the research-grade routing-flow gate from selected-terminal
  outflow versus `basin_wb` `wateryld` to routed-to-channel terms by default.
  Instead, record selected-terminal, all-terminal, `wateryld`, and
  routed-to-channel ratios together.

Why:

- SWAT+ documentation and source distinguish generated landscape water yield
  from channel-receiving components (`surq_cha`, `latq_cha`, `satex_chan`) and
  channel `flo_in`/`flo_out`. Current basin evidence shows both directions of
  ambiguity: some failed rows match routed-to-channel terms, while some passing
  multi-terminal rows have selected-terminal closure that differs from
  all-terminal routed flow.

Consequences:

- Routed-to-channel agreement is diagnostic evidence, not a claim promotion
  path.
- Multi-terminal rows now retain selected/all-terminal scope diagnostics so a
  future gate can require terminal inventory or aggregation evidence without
  re-parsing SWAT+ text outputs.

## 2026-05-14 — Negative NSE Exception Requires Skill-Diagnostic Timing Evidence

Decision:

- A locked calibrated run with negative NSE may pass the physical skill gate
  only when KGE is at least `0.40`, PBIAS is within `±30%`, and
  `skill_diagnostics.json` documents a timing or peak-lag limitation.

Why:

- The claim policy already allowed `NSE < 0` only under a documented timing
  limitation. The runtime metric gate enforced that rule, but the locked
  physical gate still emitted unconditional `NEGATIVE_SKILL`, making the
  documented exception impossible to reach.

Consequences:

- Timing documentation is evidence, not an agent assertion. It must come from
  package-written skill diagnostics.
- Metric values alone still cannot promote `research_grade`; routing,
  sensitivity, calibration verification, soil fidelity, fresh-output, outlet,
  and contract gates remain required.
