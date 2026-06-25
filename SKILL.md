---
name: swatplus-builder
description: "Use this skill when building, running, calibrating, validating, or diagnosing SWAT+ hydrological models. Triggers include SWAT+, watershed modeling, streamflow simulation, hydrograph calibration, USGS discharge matching, routing failures, and outlet selection debugging."
---

# SWAT+ Builder — Agent Skill

This skill teaches an AI agent how to operate swatplus-builder. The governing
principle: **the agent operates; the package governs.** The agent builds, runs,
calibrates, diagnoses, and iterates — but the package decides every claim tier
from runtime gates and evidence, and the agent may never override that.

## When to use this skill

Use this skill when the user needs physically meaningful SWAT+ setup, execution,
comparison, calibration support, validation, or failure diagnosis.

Use this skill for:
- Building/assembling SWAT+ projects from basin specs.
- Running end-to-end basin simulations and comparing runs.
- Querying historical run artifacts and diagnosing failures.
- Running curated-basin validation and reporting benchmark status.
- Locking a benchmark and running the verified locked-calibration protocol.

Do not use this skill for:
- Generic plotting/statistics unrelated to SWAT+ model structure.
- Pure geospatial preprocessing with no SWAT+ execution/evaluation.
- Policy or water-management recommendations without model evidence.

Boundary rules:
- **MCP tools** are the governed front door for the canonical pipeline: use
  `run_workflow` + `workflow_status` for any reportable end-to-end run.
  Structured returns enforce "read the evidence bundle" — the governance
  thesis depends on not scraping terminal text.
- **CLI commands** are the substrate for granular steps, iteration,
  debugging, and reproducible scripts. Both surfaces call the same governed
  code; the package decides the claim tier either way.
- Prefer artifact-backed outputs over ad hoc local files.
- Never hide fallback behaviors (soil/weather/outlet/routing assumptions).
- **Summarize only from the evidence bundle** — never scrape a metric from
  terminal text. Reporting a metric without disclosing a failed gate is
  overclaiming, which is precisely what this system exists to prevent.

## Prerequisites

A real build needs two things not shipped with the Python package:
- the **SWAT+ engine binary** (`SWATPLUS_EXE` or `swatplus` on `PATH`);
- the **SWAT+ reference databases** (`datasets` / `soils` / `wgn` SQLite).

### SWAT+ engine binary

**Required: SWAT+ v2023 — validated rev 60.5.7 – 61.0.2.61** (current builds
use rev 61.0.2.61).

The topology converter and routing pipeline target the `rte_cha=1` /
`chandeg.con` connect-block layout introduced in rev 60.5.7 and unchanged
through rev 61.0.2.61. Earlier revisions produce different output layouts and
may break parsing. Each run records the engine revision it parsed from the
binary banner into its evidence bundle.

**Where to get it:**
- Official download page: https://swat.tamu.edu/software/plus/
- SWAT+ GitBook docs: https://swatplus.gitbook.io/docs
- Source / releases: https://github.com/swat-model

**After downloading — recommended (no PATH or env-var needed):**
```bash
swat setup engine --path /path/to/downloaded/swatplus_exe
```
Installs to `~/.swatplus_builder/bin/` and is found automatically on every
subsequent run. Run `swat setup engine` (no args) to see current status.

**Alternative (manual):**
```bash
chmod +x swatplus_exe
export SWATPLUS_EXE=/path/to/swatplus_exe   # or place as 'swatplus' on PATH
```

**Agent guidance:** if `swat health --json` shows `"swatplus_exe": false`,
run `swat setup engine` (no args) for download instructions, then
`swat setup engine --path <binary>` to install.

### Reference databases

```bash
bash scripts/bootstrap_reference_dbs.sh   # downloads to ~/.swatplus-builder/reference_dbs
```

Bootstrap both, then confirm with `swat health --json` (reports engine path,
version, and reference-DB availability). A `degraded` result almost always
means a missing engine or missing reference DBs.

## Execution surfaces

swatplus-builder exposes **two surfaces that call the same governed code**.
The package decides the claim tier either way — the surface only changes
the interaction style and what's ergonomic for the agent.

| Surface | When to use |
|---------|-------------|
| **MCP tools** | Canonical end-to-end governed run; structured background launch + poll; hosted/chat agents that cannot shell out arbitrarily; any result that will be reported — structured returns enforce "read the evidence bundle". |
| **`swat` CLI** | Granular step-by-step work; iteration and debugging; shell-native agents (Claude Code, Cursor); reproducible scripts and CI; anything that needs to be copy-pasted into a runbook or paper appendix. |

The MCP `run_workflow` tool literally assembles a `swat workflow run ...`
argv list and execs it — it always returns the `equivalent_cli` field so
the agent can record the exact reproducible command.

## MCP tool catalog

The MCP surface is intentionally narrow: exactly **13 typed tools** in three
tiers. The tools expose operations (build, run, calibrate, verify, query) but
not the authority to override an evidence-backed decision. What is not a tool
is not an action the agent can take.

### Tier 0 — Canonical governed workflow (2 tools) — START HERE

When the user says "build/run/model gauge X" and the MCP server is
available, use `run_workflow`. It backgrounds the run, lets you poll
`workflow_status`, and hands you the evidence bundle path — making
"summarize only from the bundle" the natural path, not an extra rule.
Prefer the CLI equivalent (`swat workflow run ...`) for shell-native
agents, reproducible scripts, or when debugging a failure interactively.

#### `run_workflow`
- input: `RunWorkflowRequest(usgs_id: str, start='2000-01-01', end='2019-12-31',
  model_family='full'|'lte', warmup_years=3, calibrate=True,
  claim_tier='diagnostic', out_dir: str | None = None)`
- output: `RunWorkflowResponse(status='started', detail, out_dir, log_path, pid,
  equivalent_cli, next_step)`
- Behavior: launches the canonical workflow (build → run → lock benchmark →
  gated calibration → independent verification → evidence bundle) as a
  **detached background process** and returns immediately. A full run takes
  tens of minutes.
- After launch: poll `workflow_status(out_dir=...)` roughly every 60 s. Do not
  re-launch while a run is in progress.
- The response includes `equivalent_cli` — record it for reproducibility.

#### `workflow_status`
- input: `WorkflowStatusRequest(out_dir: str, log_tail_lines=25)`
- output: `WorkflowStatusResponse(status='running'|'completed'|'failed'|'unknown',
  detail, success?, run_id?, evidence_summary_path?, artifact_dir?,
  blocker_class?, log_tail?)`
- On `completed`: read `evidence_summary_path` and summarize **only** from the
  evidence bundle — allowed claims, blocked claims, and the effective tier.
- On `failed`: inspect `log_tail`, then `diagnose_failure` with run artifacts.

### Tier 1 — Basin workflow (8 tools)

#### `build_project`
- input: `BuildProjectRequest(basin_spec_path: str, workdir: str | None = None)`
- output: `BuildProjectResponse(status, detail, manifest_path)`
- Validates a basin spec JSON and writes a build manifest. **Does NOT build a
  runnable SWAT+ project** — use `run_workflow` for the end-to-end pipeline.
- Failure modes: invalid/missing `basin_spec_path`; non-object basin spec JSON.

#### `run_basin`
- input: `RunBasinRequest(basin_config_path: str)`
- output: `RunBasinResponse(status, detail, run_summary_path)`
- Lower-level (non-governed) pipeline orchestrator — produces no evidence
  bundle or claim tier. Prefer `run_workflow` for any reportable result.
- Failure modes: missing/invalid `basin_config_path`; config missing `usgs_id`;
  orchestration runtime failure.

#### `calibrate`
- input: `CalibrateRequest(basin_id, start, end, calibration_engine='pyswatplus',
  txtinout_dir, observed_csv, parameters, objectives, algorithm='de', n_gen=10,
  pop_size=16, seed=42, sim_output_file='basin_sd_cha_day.txt', outlet_gis_id=1, ...)`
- output: `CalibrateResponse(status, detail, calibration_hash, best_nse, outdir)`
- Use when a full calibration process should be invoked by MCP.
- Note: this is the **non-authoritative bridge** path. For reportable metrics,
  use the locked-benchmark protocol (`lock_benchmark` → `locked_calibrate`).

#### `propose_parameters`
- input: `ProposeParametersRequest(strategy='random'|'grid', count[1..100]=1,
  parameters=['CN2','ESCO','SURLAG'])`
- output: `ProposeParametersResponse(proposals: list[dict[str, float]])`
- Behavior: `grid` = linear interpolation across each range; `random` =
  deterministic pseudo-random within bounds.

#### `compare_runs`
- input: `CompareRunsRequest(run_artifacts: list[str], min_length=2)`
- output: `CompareRunsResponse(summaries: list[{run_artifact, nse, kge, pbias}])`
- Behavior: reads `<run_artifact>/metrics.json`; returns `None` metrics for
  missing files instead of crashing.

#### `query_artifacts`
- input: `QueryArtifactsRequest(artifacts_root, basin_id?, soil_mode?, nse_min?)`
- output: `QueryArtifactsResponse(count, items: list[ArtifactSummary])`
- Use when you need searchable artifact history filtered by basin/soil mode/NSE.

#### `diagnose_failure`
- input: `DiagnoseFailureRequest(run_artifact: str)`
- output: `DiagnoseFailureResponse(count, diagnoses: list[Diagnosis])`
- Behavior: accepts an artifact directory or a direct alignment CSV (`obs`,
  `sim`); applies rule-based diagnosis and returns actionable suggestions.

#### `validate`
- input: `ValidateRequest(basins_file, artifacts_root, runs_root, engine_version)`
- output: `ValidateResponse(report_dir, basin_count, success_count, cache_hits)`
- Use when you need curated-suite regression status over multiple basins.

### Tier 2 — Benchmark / readiness (3 tools)

These three tools implement the **only scientifically defensible route to
reported calibration metrics**.

#### `lock_benchmark`
- input: `LockBenchmarkRequest(txtinout_dir, observed_csv, out_dir, basin_id,
  outlet_gis_id=1, sim_source_file='basin_sd_cha_day.txt')`
- output: `LockBenchmarkResponse(basin_id, baseline_nse, baseline_kge,
  outlet_gis_id, alignment_sha256, benchmark_dir)`
- Seals a baseline with hashes — the start of the locked protocol.

#### `locked_calibrate`
- input: `LockedCalibrateRequest(benchmark_dir, base_txtinout, out_dir,
  parameters=['CN2','ALPHA_BF'], n_evaluations=30, timeout_s=3600, skip_verify=False)`
- output: `LockedCalibrateResponse(basin_id, n_evaluations, best_nse, best_kge,
  delta_nse, delta_kge, improved, best_solution_json, outdir)`
- Real-engine DDS against a lock; calls verification automatically unless
  `skip_verify` is set.

#### `readiness_table`
- input: `ReadinessTableRequest(locks_root, out_md?)`
- output: `ReadinessTableResponse(row_count, rows, out_md?)`
- Summarizes lock/calibration/verification across basins.

## Locked-benchmark protocol rules

The `lock_benchmark → locked_calibrate → verify` chain is the authoritative
path. These rules are **enforced by the toolchain**, not advisory:

- Standalone `locked_calibrate` defaults to the historical `CN2,ALPHA_BF`
  scope unless a caller supplies `parameters`.
- The governed end-to-end workflow uses the locked benchmark plus a
  basin-specific sensitivity screen over calibration-eligible full-mode
  parameters. Retained controls are then passed into staged diagnostic phases:
  volume/process partition, baseflow/subsurface, peaks/timing, and final
  NSE/KGE finetuning.
- No silent scope expansion: candidate parameters must be declared, screened,
  recorded in artifacts, and independently verified before claim use.
- Calibrated metrics are always **delta-reported against the locked baseline**,
  never as standalone absolute numbers without their baseline.
- **verify_calibration is mandatory** (`verify_calibration`): the best solution is re-run
  independently (a fresh engine run, not the optimizer-loop metric) to confirm
  reproducibility before any metric is reported.
- `evaluate_run` is the single authoritative metric source for all reporting.
- The agent cannot grant a tier, edit a gate result, or report a candidate
  (optimizer-loop) metric as a verified one. Those are not exposed as actions.

## CLI commands

Every MCP tool has a CLI equivalent. Shell-native agents and reproducible
scripts should use these directly. Key commands:

```bash
# Setup (one-time)
swat setup engine --path /path/to/swatplus_exe  # install binary to ~/.swatplus_builder/bin/
swat setup engine                               # print download instructions + current status
swat health --json                              # engine + reference-DB readiness

# Canonical governed pipeline (primary recommendation for shell-native agents)
swat workflow run --usgs-id <id> \
  --start 2000-01-01 --end 2019-12-31 \
  --model-family full --warmup-years 3 \
  --calibrate --claim-tier diagnostic \
  --out-dir runs/usgs_<id> --json

# Other pipeline steps
swat workflow negotiate --task ...             # produce/accept a workflow_contract.json
swat lock-benchmark --txtinout ... --observed-csv ... --basin-id ...
swat locked-calibrate --benchmark-dir ... --base-txtinout ... --parameters CN2,ALPHA_BF
swat readiness-table --locks-root artifacts/locks/ --json
swat inspect <run_path>                        # persisted run metadata
swat validate --basins basins/curated_v1.json
swat mcp                                       # launch the stdio MCP server
```

Solver execution guardrail: all SWAT+ binary invocations must go through
`run_solver_subprocess` — never call the binary directly with
`subprocess.Popen`/`run`. This keeps timeout, threading, and output-capture
behavior consistent and auditable across every run.

## Parameter registry

Use physically meaningful SWAT+ parameters with bounded ranges and explicit
semantics. Respect registry bounds; prefer small interpretable subsets over
broad blind sweeps; persist every evaluation as an artifact.

Tier 1 (first-pass calibration focus):
- `CN2` (runoff generation), `ALPHA_BF` (baseflow recession),
  `GW_DELAY` (groundwater lag), `SURLAG` (surface runoff timing).

Tier 2 (secondary hydrology/routing controls):
- `ESCO`, `EPCO` (ET partitioning); `CH_N2`, `CH_K2` (channel routing/seepage);
  `SOL_AWC`, `SOL_K`, `GWQMN` (soil–groundwater controls).

Tier 3 (context-sensitive refinements):
- `REVAPMN`, `GW_REVAP`; `PLAPS`, `TLAPS`; `SFTMP`, `SMTMP`.

## Diagnostic heuristics

Rule-based guidance currently implemented:
- Peak lag > 1 day → suspect `SURLAG`.
- Flashy sim / low baseflow vs observed → suspect `ALPHA_BF`, `GW_DELAY`, `GWQMN`.
- Volume bias > 15% → suspect `CN2`, `ESCO`, `EPCO`.
- Seasonal/snow timing mismatch → suspect `SFTMP`, `SMTMP`.
- Near-flat simulated hydrograph with positive observed flow → suspect
  outlet/routing structural issue (fix structure before tuning).
- High PBIAS despite moderate NSE → revisit water balance and recession.
- Recession mismatch → groundwater/channel persistence controls.

Verification expectations:
- Confirm outlet ID / source file / date window parity before parameter edits.
- Check alignment row count and observed variance before trusting metrics.
- Treat structural-routing failures before calibration tuning.

## Basin taxonomy

Use basin type to prioritize parameter experiments:
- Flashy basins: prioritize `CN2`, `SURLAG`, channel roughness (`CH_N2`).
- Baseflow-dominated basins: prioritize `ALPHA_BF`, `GW_DELAY`, `GWQMN`.
- Mixed-response basins: sequence runoff then groundwater tuning.
- Snow-influenced basins: include `SFTMP`, `SMTMP`, lapse parameters
  (`TLAPS`, `PLAPS`).

## Evaluation protocol

Required parity controls before comparing runs:
- Same outlet GIS ID.
- Same simulated source file (`basin_sd_cha_day.txt` vs alternatives must be
  explicit).
- Same date window and observed series.
- Same unit convention.

Primary metrics: `NSE`, `KGE`, `PBIAS`.

Additional logging per evaluation: `aligned_days`; observed stats
(`obs_mean/std/min/max`); simulated stats (`sim_mean/std/min/max`);
`first_date`, `last_date`, `outlet_gis_id`.

Interpretation guardrails:
- Negative NSE indicates poor predictive skill relative to the mean-observed
  baseline.
- Extremely large magnitude objective values are suspect until parity checks
  confirm correctness.

## Example workflows

### Workflow 0 — Canonical: "model gauge X" end to end (DEFAULT)
1. `run_workflow(usgs_id="01547700")` — launches the governed pipeline in the
   background and returns `out_dir` + `equivalent_cli` immediately.
2. `workflow_status(out_dir=...)` every ~60 s until `completed` or `failed`.
3. On `completed`: read `evidence_summary_path`; report allowed claims, blocked
   claims, and effective tier — never a bare metric.
4. On `failed`: inspect `log_tail`, then `diagnose_failure` on the artifacts.

### Workflow A — Diagnose a poor run and propose focused next trials
1. `query_artifacts` to locate the latest low-NSE run.
2. `diagnose_failure` on that run artifact.
3. `propose_parameters` with a constrained set from the diagnosed parameters.
4. `compare_runs` after reruns to confirm directional improvement.

### Workflow B — Authoritative locked calibration
1. `lock_benchmark` to seal the baseline (records baseline NSE/KGE + alignment hash).
2. For the standalone command, call `locked_calibrate` with declared parameters
   such as `CN2, ALPHA_BF`; for the governed workflow, use the basin-screened
   full-mode parameter set retained by the package.
3. Report **delta** NSE/KGE vs the locked baseline, verified — never the
   optimizer-loop metric.
4. `readiness_table` to summarize across basins.

### Workflow C — Curated regression verification
1. `validate` on the curated basin suite.
2. `query_artifacts` for failed/low-NSE entries.
3. `diagnose_failure` for each failure class.
4. Re-run targeted basins via the run/calibration surfaces.

## Common pitfalls

- Calibrating before structural routing is verified.
- Comparing runs with different outlet IDs, date windows, or source files.
- Trusting metrics from mismatched source files.
- Reporting an optimizer-loop (candidate) metric as if it were verified.
- Ignoring soil fallback/synthetic modes in interpretation.
- Overfitting to one metric without hydrograph-shape checks.
- Summarizing from terminal text instead of `evidence_summary.json`.
