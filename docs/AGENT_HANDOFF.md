# Agent handoff — SWAT-S1 / swatplus-builder

**Read this first, before touching anything else.** It exists so a new
session (a fresh Claude Code agent, or a human) can pick this project back up
without re-deriving context — especially when the local checkout is behind
`origin/main`.

Last updated: 2026-09-28, at the merge of PR
[#25](https://github.com/AI-Hydro/swatplus-builder/pull/25).

---

## 0. Sync the local repo first — do this before anything else

If you're reading this from a local clone that may be stale, the very first
thing to do is check and fix that, or every diagnosis you make afterwards is
suspect.

```bash
git fetch origin
git status                                   # any local changes? stash or commit first
git log --oneline HEAD..origin/main          # what's on main that you don't have?
git log --oneline origin/main..HEAD          # what do you have that main doesn't? (should usually be empty)
```

- **If `HEAD..origin/main` is non-empty and you have no local work:** fast-forward.
  ```bash
  git checkout main
  git pull --ff-only origin main
  ```
- **If you have local commits not on `origin/main`:** don't discard them.
  Check whether they're superseded (already landed under a different SHA via
  squash-merge — compare content, not SHA) before assuming you need to
  rebase or open a new PR.
- **If you're on a feature branch:** rebase it onto the fresh `main` rather
  than merging, unless the branch is already shared/pushed and rebasing
  would rewrite history someone else is using.

Then re-run `scripts/setup_local_env.sh` (idempotent — see below) to make
sure your venv, reference DBs, and engine binary match what the current code
expects.

---

## 1. What this project is

**swatplus-builder**: a headless, agent-operable pipeline that builds and
calibrates SWAT+ hydrologic models from a single USGS gauge ID, with
evidence-backed, claim-governed results (see `README.md`, `QUICKSTART.md`).
The package — not the calling agent — holds scientific authority: gates,
provenance, and claim tiers decide what may be claimed about a model's
quality.

**The larger research goal (SWAT-S1):** on top of this pipeline, build a
learned decision model — in the style of Laya/Jev (small, fast, System-1-like
specialist models) — that eventually makes SWAT+ modelling decisions
(parameter selection, calibration-phase promotion, fault diagnosis) as well
as or better than a human modeller. This pipeline is the **data-generation
and governance layer** for that model; the model itself does not exist yet.

Repo: <https://github.com/AI-Hydro/swatplus-builder> (MIT license, default
branch `main`).

---

## 2. What has been done (chronological)

1. **Environment setup** — SWAT+ engine 61.0.2.61 built from source
   (gfortran), with upstream's debug FPE trap flags stripped (they crash
   ordinary runs, including upstream's own `refdata/Ames_sub1` fixture — see
   `QUICKSTART.md` §"Building the engine from source"). Reference DBs
   bootstrapped, offline test suite passing on Python 3.10–3.12.

2. **Security/correctness/scientific audit → PR
   [#24](https://github.com/AI-Hydro/swatplus-builder/pull/24)** (merged).
   Full findings in
   `docs/AUDIT_2026-09_PIPELINE_AND_DECISION_READINESS.md`. Delivered:
   - **Tamper-evident audit ledger**: `src/swatplus_builder/audit/ledger.py`
     (`HashChainedLedger`, SHA-256 hash-chained JSONL, `verify_ledger`) and
     `audit/decisions.py` (`RunAuditTrail` — records events/decisions/
     outcomes; `verify_run_audit`; `export_decision_episodes`).
   - New CLI: `swat audit verify <run_dir>`, `swat audit episodes <run_dir>`.
   - R1–R9 fixes: correct outlet-selection provenance (auto mode upgrades by
     flow magnitude, not NSE — R1 was originally misdiagnosed against a wrong
     premise, since corrected), `evaluate_run` error handling, MCP workspace
     sandboxing (`SWATPLUS_BUILDER_MCP_WORKSPACE`), soil mukey int
     coercion, vendored-editor patch documentation, wheel packaging cleanup,
     CI hardening (ruff pinned to 0.16.9, new `offline-test-suite` job across
     3.10–3.12), Python 3.10 compatibility (`datetime.UTC` →
     `timezone.utc` alias, `tomllib` → `tomli` fallback).
   - Dependencies added: `requests>=2.31`, `mcp>=1.2,<2` (pinned below 2.x —
     2.x renamed `FastMCP`, breaking the server).

3. **Research** on Jev/Laya/CUA-S1 and adjacent hydrology-LLM work — informs
   the target model architecture and training-data shape. Key findings:
   - **Laya**: open, Apache-2.0, ModernBERT-large (421M params). Zero-shot
     accuracy ≈0.36, overconfident out-of-distribution, unreliable above
     ~20 answer options. Fine-tunes on ~30k questions in 4–5h on 2×T4.
   - **Jev**: commonly used as a *judge* model, not (primarily) the decision
     model itself.
   - **CUA-S1-FORMS**: a 706K-parameter specialist — evidence that very
     small models can work for narrow, well-typed decision tasks.
   - **HydroAgent** (arXiv 2605.17792): closest prior art. Best NSE
     ≈0.65–0.75 via SFT + GRPO with an NSE reward.
   - Implication for SWAT-S1: favor a **small, typed-choice model** (Laya/
     CUA-S1-FORMS scale, not a general LLM), trained on **outcome-grounded
     counterfactual data** (candidates that were actually evaluated, not
     synthesized after the fact) plus **fault-diagnosis** data.

4. **Decision-data pipeline → PR
   [#25](https://github.com/AI-Hydro/swatplus-builder/pull/25)** (merged
   2026-09-28, squash commit `c8ccafd`). Builds the training-data layer:
   - **Calibration-phase counterfactuals**:
     `src/swatplus_builder/calibration/locked_benchmark.py` records every
     phase's full candidate set (metrics, gate results, phase score) to
     `calibration_reports_locked/phase_decisions.json`
     (schema `swatplus_builder.calibration_phase_decisions/v1`), and
     `workflows/usgs_e2e.py` turns each phase into a ledger decision
     (`calibration_phase:<phase>`, options `eval:<idx>` + `no_promotion`).
     Candidates within a phase share starting state and budget, so they're
     valid counterfactual comparisons — this is the highest-value data for
     training a decision model, since it's not reconstructed after the fact.
   - **Fault injection**: `src/swatplus_builder/decision_data/faults.py` —
     `swat fault list|inject|effect`. 11 cataloged faults (forcing:
     precip ±30%, storm removal, precip lag, temp +3°C; parameter: CN2, ESCO,
     PERCO, ALPHA_BF, CH_N2, SMTMP highs/lows). Each injection writes a
     `fault_manifest.json` with a hidden `latent_fault_family` label and
     before/after SHA-256 hashes. **Validated against the real engine on
     Ames_sub1** — results sometimes contradict naive physical intuition
     (ESCO-low *raised* water yield 1.54×; PERCO-low had **no effect**,
     because this basin has no percolation pathway). `expected_symptoms` in
     the catalogue are documented as hypotheses, never labels — always
     confirm with `swat fault effect <base> <faulted>` before using a fault
     in a dataset, since it exits 1 when nothing hydrologically changed.
   - **State serializer**: `decision_data/state.py::serialize_state`
     (schema `state-v1`) — deterministic, priority-ordered, budgeted to
     ~1,600 chars (~400 tokens), and **refuses hidden-label keys** outright
     (raises `ValueError` on `latent_fault`, `fault_id`, etc.) so label
     leakage into the model's input is structurally impossible, not just a
     convention.
   - **Typed-decision export**: `decision_data/typed.py::compile_typed_decisions`
     (schema `swatplus_builder.typed_decision/v1`) — compiles
     `DecisionEpisode` rows into bounded Choice-question items (state /
     question / options / target). Max 16 options; phase questions always
     keep the chosen candidate, `no_promotion`, the best feasible
     alternatives, and infeasible candidates as hard negatives, in an order
     that doesn't leak the answer. Splits are `train`/`validation`/`test` by
     a SHA-256 hash of the **basin id**, so no basin straddles a split.
   - New CLI: `swat audit typed`, `swat fault list|inject|effect`.
   - Full guide: `docs/DECISION_DATA_PIPELINE.md`. 18 new tests in
     `tests/test_decision_data.py`.

---

## 3. What is NOT done yet (the actual next steps)

In rough priority order for continuing the SWAT-S1 research goal:

1. **DONE (2026-09-28).** A live end-to-end run against a real USGS basin
   (02177000, 2015–2019) completed cleanly with network access from this
   machine (USGS NWIS, GridMET, gNATSGO/Planetary Computer, 3DEP all
   reachable) — `swat audit verify` passed (73 events, 13 decisions),
   `swat audit typed` produced 7 real typed-decision items including 4
   genuine calibration-phase counterfactuals, and no `latent_fault`/
   `fault_id` leakage was found in the exported state text. Fault injection
   itself was **not** exercised in that run (see item 3 below — it needs a
   different flow than a plain `workflow run`). See PROGRESS.md's
   2026-09-28 "Live smoke test" entry for the full numbers.

2. **DONE (2026-09-28, driver written; not yet run at real scale).**
   `scripts/decision_data_batch.py` — a batch driver over a basin list.
   Each basin runs `swat workflow run` as its own subprocess (one basin
   crashing or hanging can't take down the batch); every basin's result is
   retained regardless of outcome (`batch_manifest.jsonl`, one line per
   basin, written incrementally so a killed batch loses at most the basin
   in flight); a basin is only admitted into the combined
   `typed_decisions.jsonl` after its own `swat audit verify` passes; cost
   (wall-clock seconds and engine candidate-evaluation count, from
   `phase_decisions.json`) is metered per basin and summed in
   `batch_summary.json`. See the script's own docstring for the basins.json
   schema and for what it explicitly does **not** do yet: no basin-inclusion
   protocol (the basin list is whatever the caller supplies — still open,
   see the readiness review below), no decision-development/final-
   assessment period separation, no fault injection.
   ```bash
   python scripts/decision_data_batch.py \
       --basins scripts/decision_data_batch_basins.example.json \
       --out-root runs/decision_data_batch/<date> \
       --workers 1   # raise only with enough spare cores; each basin already
                      # parallelizes internally via --sensitivity-workers/--anchor-workers
   ```
   Validated: unit tests (`tests/test_decision_data_batch.py`) cover JSON-
   object extraction, candidate-count metering, and CLI validation; the
   resume/`--skip-existing` path was manually verified end-to-end against a
   completed run (verify → typed-export → cost report, all correct, all
   without re-running the engine). **Not yet run at actual scale** — that's
   the real remaining work: assembling and running it over a real basin
   list once the basin-inclusion protocol below exists.

3. **Combined and hard-negative fault designs.** Current faults are single
   perturbations. The vision document (referenced in `docs/DECISION_DATA_PIPELINE.md`
   as "§8.4") calls for combined faults and harder negative examples —
   not yet implemented.

4. **Calibrated soft targets from repeated uncertainty realizations.** The
   current `--soft-target softmax` option is documented as "a convenience,
   not the research design's calibrated targets" — it spreads probability
   over feasible candidates by phase score, but the actual research design
   wants targets from repeated stochastic realizations, which this pipeline
   doesn't generate yet.

5. **Actually train a decision model.** Nothing here trains a model — this
   is purely the data-generation and governance layer. Once episode volume
   is sufficient, the next phase is picking an architecture (Laya/
   CUA-S1-FORMS scale looks like the right target based on the research
   above), writing the adapter from `typed_decision/v1` to that trainer's
   format, and running fine-tuning.

6. **Compute connections (deferred).** HF, Kaggle, and Anvil GPU access were
   discussed but never wired up in the cloud sandbox — that's presumably
   why you're now working locally. If Anvil access is available, it's the
   natural target for both (2) batch episode generation and (5) fine-tuning.

---

## 4. Key files to read, in order

1. `QUICKSTART.md` — how to install, build the engine, run the pipeline.
2. `docs/AGENT_WORKFLOW.md` — the negotiate → run → evidence contract for
   any agent driving this pipeline (what the agent may/may not claim).
3. `docs/AUDIT_2026-09_PIPELINE_AND_DECISION_READINESS.md` — the full audit
   this handoff summarizes in §2.2 above.
4. `docs/DECISION_DATA_PIPELINE.md` — the full guide to §2.4 above; read
   this in full before generating or using any decision-model training data.
5. `docs/PIPELINE_RESEARCH_GRADE_AUDIT.md` — honest status: 0/11 canonical
   basins currently classify as research-grade under strict gates. This is
   a claim-governance project, not a "calibration solved" claim — don't
   overstate results in anything you write downstream.
6. `CHANGELOG.md` — chronological record of every change; check the
   "Unreleased" section for anything landed after this handoff was written.

---

## 5. Environment / setup

Run `scripts/setup_local_env.sh` (added alongside this document). It is
idempotent — safe to re-run any time to check or repair your local
environment. See its `--help` for flags (`--skip-engine`, `--skip-refdb`,
`--skip-tests`).

Manual equivalent and full detail: `QUICKSTART.md` §§1–3.

Known gotchas:
- Upstream's `swat-model/swatplus` `CMakeLists.txt` adds gfortran debug FPE
  trap flags even to Release builds — an unmodified build aborts with
  `Floating point exception` on ordinary inputs. The setup script strips
  these; if you ever rebuild manually, do the same (see script or
  `QUICKSTART.md`).
- `mcp` must stay `<2` — 2.x renamed `FastMCP` → `MCPServer` and the server
  in this repo targets the 1.x API.
- Python 3.10 needs the `tomli` backport (already in the `dev` extra) since
  stdlib `tomllib` isn't available there.

---

## 6. Cost/session hygiene (if you're an agent reading this)

If you are a Claude Code agent picking this up: **do not set up recurring
scheduled check-ins (hourly polling, `/loop`, etc.) unless the user
explicitly asks for one.** A prior session burned significant spend
(~$200) on hourly self-scheduled "check CI" wakeups after opening PR #25,
each of which re-read the full cached conversation context. Prefer:
- `subscribe_pr_activity` (event-driven, no polling) over self-scheduled
  check-in loops, when watching a PR you opened.
- Ending your turn and letting event-driven wakeups (PR activity,
  `send_later` for a specific future check, not a recurring loop) bring you
  back, rather than scheduling your own recurring reminder.

---

## 7. Reconciliation with the local line (2026-09-28, local takeover)

The cloud session above branched from `9397584` (0.7.13) and never saw 12
local commits made in parallel (0.7.14 release, parallel sensitivity/anchor
workers, sealed objective-trace resume, preprint evidence and review). Local
`main` merged `origin/main` at `5b95517`. Conflicts were additive (both
lines added `run_pipeline` parameters) and were resolved by keeping both.
After the merge: ruff clean; pytest 1177 passed, 7 skipped (opt-in live);
see that commit message for each resolution.

**Former blocker for §3 step 1 (live labelled episodes), now fixed
(2026-09-28): the objective behind the labels.** A parallel local readiness
review (`../Swatplus_decision/research/BUILDER_READINESS.md`, 2026-09-23)
reproduced a fixed-epsilon issue in `output/metrics.py::log_kge`: it added a
constant ε = 0.01 m³/s before the log transform, so the same 0.01 was a
large fraction of a headwater stream's flow and a negligible fraction of a
large river's. A synthetic 7-value probe showed the score swinging from
−0.2551 to +0.91 under a pure m³/s→L/s relabeling of the same data, while
raw KGE stayed at 0.9182. The locked phase objective uses
`0.6·KGE + 0.4·log-KGE` (`calibration/locked_benchmark.py`, `_score_candidate`).
Fixed by adding `output/metrics.py::log_kge_v2` — epsilon set to 1% of each
basin's own mean observed flow (Pushpalatha et al. 2012's convention) rather
than one global constant. `log_kge` itself is untouched for historical-score
reproducibility; `evaluate_run` now records both `log_kge` and `log_kge_v2`;
`_score_candidate` prefers `log_kge_v2` and only falls back to legacy
`log_kge` for metrics recorded before this change. See `log_kge_v2`'s
docstring and `tests/test_metrics.py` for what this does and does **not**
fix — it removes the arbitrary shared constant, but log-transformed metrics
remain inherently unstable on very small, low-flow-dominated samples
(Santos et al. 2018), which no epsilon choice eliminates. Verified: ruff
clean; pytest 1186 passed, 5 skipped (opt-in live), 0 failed.

Live episode generation (§3 step 1) is now unblocked on this specific
concern. Still read that readiness report's P0/P1 table before mass-
generating labels — several items are addressed by PR #25 (fault/effect
validation, leakage-refusing serializer, basin-hash splits), but others
remain open: independent reference basins, separate decision-development
and final-assessment periods, and dead routing actions (CH_N2/CH_K2).

---

## 8. Basin inclusion protocol (2026-09-28)

Tackled the readiness review's other P0 item: "recruit independent basins
under a published inclusion protocol" and "basin-group isolation" between
decision-development and final-assessment work. Full protocol and its
disclosed gaps: `docs/BASIN_INCLUSION_PROTOCOL.md`. Script:
`scripts/basin_inclusion_protocol.py` — queries live USGS NWIS site
metadata per state (via `pygeohydro.NWIS`, already a pinned dependency),
filters on stream type / period-of-record / drainage area, excludes every
USGS ID already used anywhere in this repo's development or testing history
(computed by scanning the repo, not hand-maintained — confirmed it
correctly catches `02177000`, `03339000`, `01547700` with full citations),
and deterministically splits survivors into `development` /
`held_out_final_assessment` basin groups using a salt distinct from the
existing per-episode train/validation/test split.

Validated live against Indiana + Ohio: 195 basins included (103
development, 92 held-out), 270 excluded with reasons recorded (198
insufficient period of record, 56 drainage-area out of bounds, 12 not a
stream site, 3 contaminated by prior use, 1 missing drainage area). Ruff
clean; pytest 1202 passed, 5 skipped, 0 failed (7 new unit tests for the
pure logic: contamination scanning, deterministic split, split-salt
independence from the episode-level split).

Disclosed gaps (read `docs/BASIN_INCLUSION_PROTOCOL.md` §7 before treating
any generated pool as a trusted reference set): no spatial-independence
(nested-basin) check, no climate/ecoregion stratification, the held-out
group's "don't touch it" rule is a process convention, not machine-enforced,
and reference quality beyond the USGS HCDN-2009 flag is not verified.

Next: decide `--states` scope (currently defaults to a 3-state proof run,
`in oh ky`; full CONUS via `--states all` takes longer and hits NWIS's
occasional flakiness more often, though each state retries and failures are
recorded, not silently dropped), generate `basins/reference_pool_v1.json`
for real, then feed its `development` group into
`scripts/decision_data_batch.py --basins <derived from reference pool>`.
That conversion (`reference_pool_v1.json`'s `included` records ->
`decision_data_batch.py`'s basin-spec JSON) is not yet written.
