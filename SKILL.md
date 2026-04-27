---
name: swatplus-builder
description: "Use this skill when building, running, calibrating, validating, or diagnosing SWAT+ hydrological models. Triggers include SWAT+, watershed modeling, streamflow simulation, hydrograph calibration, USGS discharge matching, routing failures, and outlet selection debugging."
---

# SWAT+ Builder - Agent Skill

## When to use this skill

Use this skill when the user needs physically meaningful SWAT+ setup, execution, comparison, calibration support, validation, or failure diagnosis.

Use this skill for:
- Building/assembling SWAT+ projects from basin specs.
- Running end-to-end basin simulations and comparing runs.
- Querying historical run artifacts and diagnosing failures.
- Running curated-basin validation and reporting benchmark status.

Do not use this skill for:
- Generic plotting/statistics unrelated to SWAT+ model structure.
- Pure geospatial preprocessing with no SWAT+ execution/evaluation.
- Policy or water-management recommendations without model evidence.

Boundary rules:
- Prefer explicit typed tool calls over free-form scripts.
- Prefer artifact-backed outputs over ad hoc local files.
- Never hide fallback behaviors (soil/weather/outlet/routing assumptions).

## Tool catalog

The MCP surface is intentionally narrow: exactly 8 tools.

### `build_project`

Signature:
- input: `BuildProjectRequest(basin_spec_path: str, workdir: str | None = None)`
- output: `BuildProjectResponse(status='success', detail: str, manifest_path: str)`

Use when:
- A basin specification must be promoted to a runnable SWAT+ project.

Current implementation status:
- Operational wrapper validates basin spec JSON and writes a reproducible build manifest.

Failure modes:
- Invalid/missing `basin_spec_path`.
- Non-object/invalid basin spec JSON payload.

### `run_basin`

Signature:
- input: `RunBasinRequest(basin_config_path: str)`
- output: `RunBasinResponse(status='success', detail: str, run_summary_path: str)`

Use when:
- A prepared basin configuration should be executed end-to-end.

Current implementation status:
- Operational wrapper executes orchestration from basin config (`usgs_id`, dates, output dir).

Failure modes:
- Missing/invalid `basin_config_path`.
- Config missing required `usgs_id`.
- Orchestration runtime failure.

### `calibrate`

Signature:
- input: `CalibrateRequest(basin_id: str, start: str, end: str, calibration_engine: 'spotpy'|'pyswatplus'='pyswatplus', txtinout_dir: str, observed_csv: str, parameters: list[str], objectives: list[str], algorithm: str='de', n_gen: int=10, pop_size: int=16, seed: int=42, sim_output_file: str='basin_sd_cha_day.txt', outlet_gis_id: int=1, artifacts_root: str='tests/_artifacts/calibration_mcp')`
- output: `CalibrateResponse(status='success', detail: str, calibration_hash: str, best_nse: float | None, outdir: str)`

Use when:
- A full calibration process should be invoked by MCP.

Current implementation status:
- Operational wrapper executes pySWATPlus bridge calibration via `Calibrator`.

Failure modes:
- Unsupported calibration engine (currently only `pyswatplus` on MCP path).
- Missing required calibration paths (`txtinout_dir`, `observed_csv`).
- pySWATPlus runtime/dependency failure or evaluation mismatch.

### `propose_parameters`

Signature:
- input: `ProposeParametersRequest(strategy: 'random'|'grid'='random', count: int[1..100]=1, parameters: list[str]=['CN2','ESCO','SURLAG'])`
- output: `ProposeParametersResponse(proposals: list[dict[str, float]])`

Use when:
- You need deterministic candidate parameter vectors before real runs.

Behavior:
- `grid`: linear interpolation across each parameter range.
- `random`: deterministic pseudo-random within parameter bounds.

Failure modes:
- Empty parameter list after normalization.
- Unknown parameter name in registry.

### `compare_runs`

Signature:
- input: `CompareRunsRequest(run_artifacts: list[str], min_length=2)`
- output: `CompareRunsResponse(summaries: list[{run_artifact, nse, kge, pbias}])`

Use when:
- You need a quick metrics comparison across run artifact directories.

Behavior:
- Reads `<run_artifact>/metrics.json` if present.
- Returns `None` metrics for missing files instead of crashing.

Failure modes:
- Non-JSON/invalid metrics file content.
- Paths that do not resolve to readable directories.

### `query_artifacts`

Signature:
- input: `QueryArtifactsRequest(artifacts_root: str, basin_id: str | None, soil_mode: str | None, nse_min: float | None)`
- output: `QueryArtifactsResponse(count: int, items: list[ArtifactSummary])`

Use when:
- You need searchable artifact history filtered by basin/soil mode/NSE floor.

Behavior:
- Uses local artifact store query semantics.

Failure modes:
- Invalid `artifacts_root` permissions/path.
- Malformed artifact records skipped during scan.

### `diagnose_failure`

Signature:
- input: `DiagnoseFailureRequest(run_artifact: str)`
- output: `DiagnoseFailureResponse(count: int, diagnoses: list[Diagnosis])`

Use when:
- A run shows poor skill, flat hydrograph, volume bias, or timing mismatch.

Behavior:
- Accepts artifact directory or direct alignment CSV (`obs`, `sim`).
- Applies rule-based diagnosis set and returns actionable suggestions.

Failure modes:
- Missing alignment/timeseries source.
- Alignment file missing required `obs`/`sim` columns.
- No overlapping rows after NA filtering.

### `validate`

Signature:
- input: `ValidateRequest(basins_file: str, artifacts_root: str='tests/_artifacts/validation_mcp', runs_root: str='tests/_artifacts/validation_mcp_work', engine_version: str='unknown')`
- output: `ValidateResponse(report_dir: str, basin_count: int, success_count: int, cache_hits: int)`

Use when:
- You need curated-suite regression status over multiple basins.

Behavior:
- Loads basin specs.
- Runs/collects validation results.
- Returns aggregate pass/cached summary and report directory path.

Failure modes:
- Invalid basin spec JSON shape.
- Executor/runtime failures for one or more basins.
- Report write path permission issues.

## Parameter registry

Use physically meaningful SWAT+ parameters with bounded ranges and explicit semantics.

Tier 1 (first-pass calibration focus):
- `CN2` (runoff generation)
- `ALPHA_BF` (baseflow recession)
- `GW_DELAY` (groundwater lag)
- `SURLAG` (surface runoff timing)

Tier 2 (secondary hydrology/routing controls):
- `ESCO`, `EPCO` (ET partitioning)
- `CH_N2`, `CH_K2` (channel routing/seepage)
- `SOL_AWC`, `SOL_K`, `GWQMN` (soil-groundwater controls)

Tier 3 (context-sensitive refinements):
- `REVAPMN`, `GW_REVAP`
- `PLAPS`, `TLAPS`
- `SFTMP`, `SMTMP`

Rules:
- Respect registry bounds and scope.
- Prefer small, interpretable parameter subsets over broad blind sweeps.
- Persist every evaluation as an artifact.

## Diagnostic heuristics

Rule-based guidance currently implemented:
- Peak lag > 1 day -> suspect `SURLAG`.
- Flashy sim / low baseflow vs observed -> suspect `ALPHA_BF`, `GW_DELAY`, `GWQMN`.
- Volume bias > 15% -> suspect `CN2`, `ESCO`, `EPCO`.
- Seasonal/snow timing mismatch -> suspect `SFTMP`, `SMTMP`.
- Near-flat simulated hydrograph with positive observed flow -> suspect outlet/routing structural issue.
- High PBIAS despite moderate NSE -> revisit water balance and recession behavior.
- Recession mismatch -> groundwater/channel persistence controls.

Verification expectations:
- Confirm outlet ID/source file/date window parity before parameter edits.
- Check alignment row count and observed variance before trusting metrics.
- Treat structural-routing failures before calibration tuning.

## Basin taxonomy

Use basin type to prioritize parameter experiments:
- Flashy basins: prioritize `CN2`, `SURLAG`, channel roughness (`CH_N2`).
- Baseflow-dominated basins: prioritize `ALPHA_BF`, `GW_DELAY`, `GWQMN`.
- Mixed-response basins: sequence runoff then groundwater tuning.
- Snow-influenced basins: include `SFTMP`, `SMTMP`, lapse parameters (`TLAPS`, `PLAPS`).

## Evaluation protocol

Required parity controls before comparing runs:
- Same outlet GIS ID.
- Same simulated source file (`basin_sd_cha_day.txt` vs alternatives must be explicit).
- Same date window and observed series.
- Same unit convention.

Primary metrics:
- `NSE`, `KGE`, `PBIAS`.

Additional logging per evaluation:
- `aligned_days`
- observed stats (`obs_mean/std/min/max`)
- simulated stats (`sim_mean/std/min/max`)
- `first_date`, `last_date`, `outlet_gis_id`

Interpretation guardrails:
- Negative NSE indicates poor predictive skill relative to mean-observed baseline.
- Extremely large magnitude objective values are suspect until parity checks confirm correctness.

## Example workflows

### Workflow A: Diagnose a poor run and propose focused next trials
1. `query_artifacts` to locate latest low-NSE run.
2. `diagnose_failure` on that run artifact.
3. `propose_parameters` with a constrained set from diagnosed parameters.
4. `compare_runs` after reruns to confirm directional improvement.

### Workflow B: Curated regression verification
1. `validate` on curated basin suite.
2. `query_artifacts` for failed/low-NSE entries.
3. `diagnose_failure` for each failure class.
4. Re-run targeted basins via project run/calibration surfaces.

### Workflow C: Calibration support loop (current hybrid mode)
1. Use parameter proposals from `propose_parameters`.
2. Execute calibration/run via CLI-backed orchestration.
3. Compare artifacts and diagnose.
4. Iterate while preserving lineage and parity logs.

## Common pitfalls

- Calibrating before structural routing is verified.
- Comparing runs with different outlet IDs or date windows.
- Trusting metrics from mismatched source files.
- Ignoring soil fallback/synthetic modes in interpretation.
- Overfitting to one metric without hydrograph shape checks.
- Comparing runs across mismatched outlet/date/source-file contexts.
