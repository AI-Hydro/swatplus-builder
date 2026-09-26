# Decision-model data pipeline

This is how swatplus-builder turns governed workflow runs into training data for a
learned decision model, such as a SWAT-S1 Laya/Jev-style specialist. Every step
writes a verifiable artifact, and the canonical record is always the
model-agnostic `DecisionEpisode`. Trainer-specific formats are compiled from it
and can be regenerated at any time.

```
base TxtInOut ──swat fault inject──▶ run_dir/TxtInOut + fault_manifest.json   (optional)
run_dir ──swat workflow run──▶ events.jsonl + decisions.jsonl (+ phase_decisions.json)
run_dir ──swat audit verify──▶ hash chains checked against sealed heads
run_dir(s) ──swat audit episodes──▶ DecisionEpisode JSONL           (canonical)
run_dir(s) ──swat audit typed──▶ typed-decision JSONL (state/question/options/target)
```

## 1. Decisions that are recorded

| Decision point | Options | Chosen by | Outcome attached |
|---|---|---|---|
| `claim_tier_contract` | the 5 claim tiers | `_allowed_claim_tier` | none; the final tier is recorded as its own decision |
| `calibration_precheck` | run / block calibration | `_calibration_precheck` | calibration status, verified metrics and their deltas, phase statuses |
| `calibration_phase:<phase>` | every candidate the phase evaluated (`eval:<idx>`) + `no_promotion` | phase promotion rule (best feasible phase score) | **every candidate's** metrics, gate results and phase score, i.e. what each alternative would have yielded |
| `effective_claim_tier` | the 5 claim tiers | `_effective_claim_tier` | counts of allowed and blocked claims |

Calibration phases write `calibration_reports_locked/phase_decisions.json`
(schema `swatplus_builder.calibration_phase_decisions/v1`). That file holds, for
each phase:
- the parameters it opened;
- its incoming state;
- its status (`promoted`, `no_feasible_candidate`, `blocked_preceding_process_gate`, `skipped_no_eligible_parameters` or `not_reached`);
- its full candidate set.

The ledger decision pins this file and `history.csv` by SHA-256. The file
covers the primary phased search (`scope: primary_phased_search`). Multi-seed
DDS refinement, when enabled, runs afterwards and can change the final
parameters; its evaluations appear only in `history.csv`.

Phase candidates compete under the **same starting state and budget**. That
makes them valid counterfactual comparisons in the sense of the vision document
(§8.5), and ranking data can be taken from them.

## 2. Fault injection (known causes)

`swat fault list` shows the catalogue. `swat fault inject <base> <run_dir> --fault <id>`:
- copies the base `TxtInOut`, without any engine outputs;
- applies one fault;
- writes `fault_manifest.json` containing the spec, the hidden `latent_fault_family`, and before/after SHA-256 for every input file.

**Forcing faults** edit the observed station files: scale precipitation, remove
the largest storms, delay precipitation, shift temperature. `-99` missing values
are never touched. A variable driven by the weather generator (an empty station
file) is refused with a clear error.

**Parameter faults** go through the validated full-mode parameter bridge, so a
fault can only write what calibration can write.

A failed injection leaves nothing behind. An injection that changes no file is
refused.

`swat workflow run --out-dir <run_dir>` then runs the governed workflow on the
faulted model. The prepared `TxtInOut` in the run directory is picked up, and
the manifest is bound into `events.jsonl` by its hash.

### Verify every injected episode

A changed file is not a changed hydrology. On SWAT+'s `Ames_sub1` reference
watershed (engine 61.0.2.61, 1975–1990):

| Fault | Annual-average response (ratio to base) |
|---|---|
| `precip_minus_30pct` | precip 0.700, water yield 0.28 |
| `storms_removed_p95` | precip 0.86, water yield 0.34 |
| `cn2_high` (CN2 = 92) | water yield 6.9, surface runoff 7.0 |
| `esco_low` (ESCO = 0.05) | water yield **1.54** (opposite to the naive expectation) |
| `perco_low` (PERCO = 0.02) | **no change**: this basin has no percolation |

So `expected_symptoms` in the catalogue are hypotheses, never labels. Run both
the base and the faulted model, then check with `swat fault effect <base>
<faulted>`, which exits 1 when nothing moved. Exclude ineffective faults from
datasets.

## 3. Episodes and typed decisions

`swat audit episodes` exports one row per decision:
- state before the decision;
- candidate actions;
- chosen action and outcome vector;
- `split_group` (the basin);
- `source` (`natural` or `injected_fault`);
- for faulted runs, a separate `latent_fault` field;
- the ledger record hashes the row was built from.

`swat audit typed` compiles episodes into typed-decision items (Choice questions).

- **State text.** `serialize_state` (version `state-v1`) flattens the state
  deterministically, prioritises diagnostic keys, and trims to `--max-chars`
  (default 1,600 characters, about 400 tokens). Any trimmed keys are listed in
  `meta.state_dropped_keys`. It **refuses** hidden-label keys such as
  `latent_fault`.
- **Bounded options.** At most `--max-options` (default 16). For calibration
  phases the list always keeps:
  - the chosen candidate;
  - `no_promotion`;
  - the best feasible alternatives;
  - infeasible candidates as hard negatives.

  Options are presented in a stable order that does not reveal the answer.
- **Targets.** Hard one-hot by default. `--soft-target softmax` spreads
  calibration-phase targets over feasible candidates by phase score. This is a
  convenience: the calibrated soft targets of the research design need repeated
  uncertainty realizations, which this pipeline does not yet generate.
- **Diagnosis items.** For fault-injected runs, the `effective_claim_tier`
  state also yields a `dominant_failure` question. Its target is the injected
  family.
- **Splits.** `train`/`validation`/`test` come from a hash of the basin id, so
  every episode of a basin lands in one split. That keeps evaluation on unseen
  basins.

The item fields (`state`, `question.type/text/options`,
`target.probabilities`) follow the typed-decision primitives rather than one
trainer's exact file format. Map them onto the keys your Laya fine-tuning
notebook expects with a thin adapter, and keep the episodes as the source of
truth.

## 4. Known limits

- A decision recorded today is taken by a package rule (`decided_by:
  package_rule`). Imitating those rules is only a baseline. The research value
  lies in the outcome-grounded phase candidates and the fault diagnosis items.
- Fault injection covers single faults. Combined and hard-negative fault
  designs (vision document §8.4) are the next step.
- Nothing here runs at scale by itself. Generating thousands of episodes needs
  external compute (for example batch jobs on Anvil), with each run directory
  verified by `swat audit verify` before its episodes are admitted.
