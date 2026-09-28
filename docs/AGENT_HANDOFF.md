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

1. **A live end-to-end run against a real USGS basin with fault injection.**
   Everything so far has been validated on the offline `Ames_sub1` fixture.
   The PR #25 test plan explicitly left this unchecked because the sandbox
   it was built in had no network access to USGS NWIS, 3DEP, GridMET, or
   Planetary Computer. **On your local machine this restriction likely
   doesn't apply** — this should be one of the first things you try:
   ```bash
   swat fault inject <base_txtinout> runs/fault_test --fault precip_minus_30pct
   swat workflow run --usgs-id 02177000 --model-family full \
       --start 2000-01-01 --end 2019-12-31 --warmup-years 3 \
       --calibrate --claim-tier diagnostic --out-dir runs/fault_test --json
   swat audit verify runs/fault_test
   swat audit episodes runs/fault_test > episodes.jsonl
   swat audit typed episodes.jsonl > typed.jsonl
   ```
   If this works cleanly end-to-end, it validates the whole pipeline for
   real basins, not just the synthetic fixture.

2. **Generate episodes at scale.** Nothing runs at scale by itself yet —
   that needs a batch driver (e.g. Slurm/Anvil array jobs, or a simple
   parallel loop) over a basin list, each run verified with
   `swat audit verify` before its episodes are admitted to a training set.
   This was explicitly deferred (see `docs/DECISION_DATA_PIPELINE.md` §4,
   "Known limits").

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
