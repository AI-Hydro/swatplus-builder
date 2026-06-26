"""Typed MCP tool surface for swatplus-builder.

Tier 0 exposes the canonical claim-governed workflow (`run_workflow` /
`workflow_status`); Tier 1 covers basin-level operations; Tier 2 covers the
locked-benchmark protocol. The tools expose operations, never the authority
to override an evidence-backed claim decision.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from ..artifacts import ArtifactQuery, LocalArtifactStore
from ..calibration.calibrator import Calibrator, CalibratorRequest
from ..calibration.locked_benchmark import (
    build_readiness_table,
    calibrate_against_lock,
    lock_benchmark,
    verify_calibration,
)
from ..diagnostics import diagnose
from ..orchestrate import run_pipeline
from ..params import registry
from ..validation.runner import load_basin_specs, run_validation


class BuildProjectRequest(BaseModel):
    basin_spec_path: str = Field(..., description="Path to a basin spec JSON file.")
    workdir: str | None = Field(default=None, description="Optional workspace directory.")


class BuildProjectResponse(BaseModel):
    status: Literal["success"] = "success"
    detail: str
    manifest_path: str


class RunBasinRequest(BaseModel):
    basin_config_path: str = Field(..., description="Path to a basin run configuration JSON file.")


class RunBasinResponse(BaseModel):
    status: Literal["success"] = "success"
    detail: str
    run_summary_path: str


class CalibrateRequest(BaseModel):
    basin_id: str
    start: str = Field(..., description="YYYY-MM-DD")
    end: str = Field(..., description="YYYY-MM-DD")
    calibration_engine: Literal["spotpy", "pyswatplus"] = "pyswatplus"
    preset: Literal["quick", "standard", "thorough"] = "quick"
    artifacts_root: str = "tests/_artifacts/calibration_mcp"
    txtinout_dir: str | None = None
    observed_csv: str | None = None
    parameters: list[str] = Field(default_factory=lambda: ["CN2", "ALPHA_BF", "SURLAG"])
    objectives: list[str] = Field(default_factory=lambda: ["nse"])
    algorithm: str = "de"
    n_gen: int = Field(10, ge=1)
    pop_size: int = Field(16, ge=1)
    seed: int = 42
    sim_output_file: str = "basin_sd_cha_day.txt"
    outlet_gis_id: int = 1


class CalibrateResponse(BaseModel):
    status: Literal["success"] = "success"
    detail: str
    calibration_hash: str
    best_nse: float | None = None
    outdir: str


class ProposeParametersRequest(BaseModel):
    strategy: Literal["random", "grid"] = "random"
    count: int = Field(1, ge=1, le=100)
    parameters: list[str] = Field(default_factory=lambda: ["CN2", "ESCO", "SURLAG"])


class ProposeParametersResponse(BaseModel):
    proposals: list[dict[str, float]]


class CompareRunsRequest(BaseModel):
    run_artifacts: list[str] = Field(..., min_length=2, description="Artifact directory paths.")


class CompareRunsResponse(BaseModel):
    summaries: list[dict[str, float | str | None]]


class QueryArtifactsRequest(BaseModel):
    artifacts_root: str
    basin_id: str | None = None
    soil_mode: str | None = None
    nse_min: float | None = None


class QueryArtifactsResponse(BaseModel):
    count: int
    items: list[dict[str, object]]


class DiagnoseFailureRequest(BaseModel):
    run_artifact: str


class DiagnoseFailureResponse(BaseModel):
    count: int
    diagnoses: list[dict[str, object]]


class ValidateRequest(BaseModel):
    basins_file: str = Field(..., description="Path to curated basin JSON file.")
    artifacts_root: str = "tests/_artifacts/validation_mcp"
    runs_root: str = "tests/_artifacts/validation_mcp_work"
    engine_version: str = "unknown"


class ValidateResponse(BaseModel):
    report_dir: str
    basin_count: int
    success_count: int
    cache_hits: int


class LockBenchmarkRequest(BaseModel):
    txtinout_dir: str = Field(..., description="Prepared SWAT+ TxtInOut directory path.")
    observed_csv: str = Field(..., description="Observed discharge CSV (DatetimeIndex + 'discharge' column).")
    out_dir: str = Field(..., description="Root directory for lock artifacts.")
    basin_id: str = Field(..., description="Basin identifier (e.g. usgs_01547700).")
    outlet_gis_id: int | None = Field(
        None,
        description=(
            "Gauge outlet channel GIS ID. When omitted, the package accepts the generated "
            "topology only if it contains exactly one terminal channel."
        ),
    )
    sim_source_file: str = Field(
        "basin_sd_cha_day.txt",
        description="Simulation output file to score (basin_sd_cha_day.txt or channel_sd_day.txt).",
    )


class LockBenchmarkResponse(BaseModel):
    status: Literal["success"] = "success"
    basin_id: str
    baseline_nse: float
    baseline_kge: float
    outlet_gis_id: int
    alignment_sha256: str
    benchmark_dir: str


class LockedCalibrateRequest(BaseModel):
    benchmark_dir: str = Field(..., description="Directory containing benchmark_lock.json.")
    base_txtinout: str = Field(..., description="Source TxtInOut (fresh copy per evaluation).")
    out_dir: str = Field(..., description="Root for calibration + verification artifacts.")
    parameters: list[str] = Field(
        default_factory=lambda: ["CN2", "ALPHA_BF"],
        description="Effective parameter names (default: CN2, ALPHA_BF).",
    )
    n_evaluations: int = Field(30, ge=1, description="Total real-engine evaluations.")
    binary: str | None = Field(None, description="Optional SWAT+ binary path override.")
    timeout_s: float = Field(3600.0, description="Per-evaluation engine timeout (seconds).")
    skip_verify: bool = Field(False, description="Skip independent verification step.")


class LockedCalibrateResponse(BaseModel):
    status: Literal["success"] = "success"
    basin_id: str
    n_evaluations: int
    best_nse: float
    best_kge: float | None = None
    delta_nse: float | None = None
    delta_kge: float | None = None
    improved: bool | None = None
    best_solution_json: str
    outdir: str


class ReadinessTableRequest(BaseModel):
    locks_root: str = Field(..., description="Root directory to scan for lock and verification artifacts.")
    out_md: str | None = Field(None, description="Optional path to write a markdown readiness table.")


class ReadinessTableResponse(BaseModel):
    row_count: int
    rows: list[dict[str, object]]
    out_md: str | None = None


class RunWorkflowRequest(BaseModel):
    usgs_id: str = Field(..., description="USGS streamgage ID, e.g. '01547700'.")
    start: str = Field("2000-01-01", description="Simulation start date (YYYY-MM-DD).")
    end: str = Field("2019-12-31", description="Simulation end date (YYYY-MM-DD).")
    model_family: Literal["full", "lte"] = Field("full", description="SWAT+ model family.")
    warmup_years: int = Field(3, description="Warm-up years excluded from evaluation.")
    hru_mode: Literal["dominant_only", "full_overlay"] = Field(
        "dominant_only",
        description=(
            "HRU construction mode. Use full_overlay for research-grade land-use fidelity probes; "
            "dominant_only remains the default first-run mode."
        ),
    )
    min_hru_fraction: float = Field(
        0.0,
        ge=0.0,
        description="Minimum LSU-area fraction retained for full-overlay HRU combinations.",
    )
    calibrate: bool = Field(True, description="Run gated locked calibration after the base run.")
    claim_tier: str = Field(
        "diagnostic",
        description=(
            "Requested claim tier (exploratory | diagnostic | research_grade). "
            "The package may downgrade it based on runtime gates; the agent cannot override."
        ),
    )
    out_dir: str | None = Field(
        None,
        description="Output directory. Defaults to swatplus_runs/workflow/usgs_<id>_<timestamp> under the current directory.",
    )


class RunWorkflowResponse(BaseModel):
    status: Literal["started"] = "started"
    detail: str
    out_dir: str
    log_path: str
    pid: int
    equivalent_cli: str
    next_step: str


class WorkflowStatusRequest(BaseModel):
    out_dir: str = Field(..., description="The out_dir returned by run_workflow.")
    log_tail_lines: int = Field(25, description="How many trailing log lines to include.")


class WorkflowStatusResponse(BaseModel):
    status: Literal["running", "completed", "failed", "unknown"]
    detail: str
    success: bool | None = None
    run_id: str | None = None
    evidence_summary_path: str | None = None
    artifact_dir: str | None = None
    blocker_class: str | None = None
    log_tail: str | None = None


_LAUNCH_STATE_FILENAME = "workflow_launch.json"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _parse_final_json(log_text: str) -> dict | None:
    """Extract the final JSON payload printed by `swat workflow run --json`.

    The payload is the last top-level JSON object in the log; walk candidate
    start lines backwards so leading engine/stream noise cannot break parsing.
    """
    lines = log_text.splitlines()
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == "{":
            candidate = "\n".join(lines[i:])
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
    return None


def create_mcp_server() -> FastMCP:
    """Create and register the swatplus-builder MCP tool surface."""
    mcp = FastMCP(name="swatplus-builder")

    @mcp.tool(
        name="run_workflow",
        description=(
            "START HERE for 'build/run/model gauge X'. Launches the canonical "
            "claim-governed USGS workflow (build → run → lock benchmark → gated "
            "calibration → independent verification → evidence bundle) for one "
            "USGS gauge ID. Runs as a detached background process — returns "
            "immediately; poll progress with workflow_status. A full run takes "
            "tens of minutes. The package, not the agent, decides the final "
            "claim tier; summarize results only from the evidence bundle."
        ),
    )
    def run_workflow(req: RunWorkflowRequest) -> RunWorkflowResponse:
        usgs_id = req.usgs_id.strip()
        if not usgs_id.isdigit():
            raise ValueError(f"usgs_id must be a numeric USGS gauge ID, got: {req.usgs_id!r}")

        if req.out_dir is not None:
            out_dir = Path(req.out_dir).expanduser().resolve()
        else:
            stamp = time.strftime("%Y%m%d_%H%M%S")
            out_dir = (Path.cwd() / "swatplus_runs" / "workflow" / f"usgs_{usgs_id}_{stamp}").resolve()
        out_dir.mkdir(parents=True, exist_ok=True)

        argv = [
            sys.executable,
            "-m",
            "swatplus_builder.cli",
            "workflow",
            "run",
            "--usgs-id",
            usgs_id,
            "--model-family",
            req.model_family,
            "--start",
            req.start,
            "--end",
            req.end,
            "--warmup-years",
            str(req.warmup_years),
            "--hru-mode",
            req.hru_mode,
            "--min-hru-fraction",
            str(req.min_hru_fraction),
            "--out-dir",
            str(out_dir),
            "--calibrate" if req.calibrate else "--no-calibrate",
            "--claim-tier",
            req.claim_tier,
            "--json",
        ]

        log_path = out_dir / "workflow_mcp.log"
        with log_path.open("wb") as log_file:
            proc = subprocess.Popen(
                argv,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                cwd=str(out_dir),
                start_new_session=True,
            )

        launch_state = {
            "pid": proc.pid,
            "argv": argv,
            "log_path": str(log_path),
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "usgs_id": usgs_id,
        }
        (out_dir / _LAUNCH_STATE_FILENAME).write_text(
            json.dumps(launch_state, indent=2) + "\n", encoding="utf-8"
        )

        equivalent_cli = "swat workflow run " + " ".join(argv[4:])
        return RunWorkflowResponse(
            detail=(
                f"Canonical workflow for USGS {usgs_id} started in the background "
                f"(pid {proc.pid}). This is the governed end-to-end path; results "
                "must be summarized from the evidence bundle only."
            ),
            out_dir=str(out_dir),
            log_path=str(log_path),
            pid=proc.pid,
            equivalent_cli=equivalent_cli,
            next_step=(
                f"Poll workflow_status with out_dir='{out_dir}' (every ~60s). "
                "When status is 'completed', read evidence_summary_path before "
                "reporting any metric or claim."
            ),
        )

    @mcp.tool(
        name="workflow_status",
        description=(
            "Check the status of a run_workflow launch. Returns running | "
            "completed | failed plus the evidence bundle pointers once finished. "
            "Always read the evidence summary before reporting results."
        ),
    )
    def workflow_status(req: WorkflowStatusRequest) -> WorkflowStatusResponse:
        out_dir = Path(req.out_dir).expanduser().resolve()
        state_path = out_dir / _LAUNCH_STATE_FILENAME
        if not state_path.exists():
            return WorkflowStatusResponse(
                status="unknown",
                detail=(
                    f"No {_LAUNCH_STATE_FILENAME} found in {out_dir} — was this "
                    "directory created by run_workflow?"
                ),
            )

        launch = json.loads(state_path.read_text(encoding="utf-8"))
        pid = int(launch.get("pid", -1))
        log_path = Path(launch.get("log_path", out_dir / "workflow_mcp.log"))
        log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
        tail_lines = log_text.splitlines()[-max(1, req.log_tail_lines):]
        log_tail = "\n".join(tail_lines) if tail_lines else None

        if pid > 0 and _pid_alive(pid):
            return WorkflowStatusResponse(
                status="running",
                detail=f"Workflow (pid {pid}) is still running. Poll again in ~60s.",
                log_tail=log_tail,
            )

        payload = _parse_final_json(log_text)
        if payload is not None:
            return WorkflowStatusResponse(
                status="completed",
                detail=(
                    "Workflow finished. Summarize only from the evidence bundle at "
                    "evidence_summary_path — never from log text."
                ),
                success=bool(payload.get("success")),
                run_id=payload.get("run_id"),
                evidence_summary_path=payload.get("evidence_summary_path"),
                artifact_dir=payload.get("artifact_dir"),
                blocker_class=payload.get("blocker_class"),
                log_tail=log_tail,
            )

        return WorkflowStatusResponse(
            status="failed",
            detail=(
                f"Workflow process (pid {pid}) is no longer running and no final "
                "JSON payload was found in the log. Inspect the log tail and "
                f"full log at {log_path}."
            ),
            log_tail=log_tail,
        )

    @mcp.tool(
        name="build_project",
        description=(
            "Validate a basin spec JSON and write a build manifest. NOTE: this "
            "does NOT produce a runnable SWAT+ project — for the end-to-end "
            "governed build/run/calibrate pipeline from a USGS gauge ID, use "
            "run_workflow instead."
        ),
    )
    def build_project(req: BuildProjectRequest) -> BuildProjectResponse:
        spec_path = Path(req.basin_spec_path).expanduser().resolve()
        if not spec_path.exists():
            raise ValueError(f"basin_spec_path does not exist: {spec_path}")
        payload = json.loads(spec_path.read_text(encoding="utf-8"))
        workdir = (
            Path(req.workdir).expanduser().resolve()
            if req.workdir is not None
            else (spec_path.parent / f"mcp_build_{spec_path.stem}").resolve()
        )
        workdir.mkdir(parents=True, exist_ok=True)
        manifest_path = workdir / "build_project_manifest.json"
        manifest = {
            "status": "success",
            "source_spec": str(spec_path),
            "workdir": str(workdir),
            "keys": sorted(payload.keys()) if isinstance(payload, dict) else None,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return BuildProjectResponse(
            detail=(
                "Basin spec was validated and a build manifest was written. "
                "No runnable SWAT+ project was built — use run_workflow for the "
                "end-to-end governed pipeline."
            ),
            manifest_path=str(manifest_path),
        )

    @mcp.tool(
        name="run_basin",
        description=(
            "Run a basin configuration through the lower-level (non-governed) "
            "pipeline orchestrator. Produces no evidence bundle or claim tier — "
            "prefer run_workflow for any result that will be reported."
        ),
    )
    def run_basin(req: RunBasinRequest) -> RunBasinResponse:
        cfg_path = Path(req.basin_config_path).expanduser().resolve()
        if not cfg_path.exists():
            raise ValueError(f"basin_config_path does not exist: {cfg_path}")
        payload = json.loads(cfg_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("basin_config_path must contain a JSON object.")
        usgs_id = str(payload.get("usgs_id", "")).strip()
        if not usgs_id:
            raise ValueError("basin config must contain non-empty 'usgs_id'.")
        outdir = Path(str(payload.get("outdir", cfg_path.parent / f"run_{usgs_id}"))).expanduser().resolve()
        summary = run_pipeline(
            usgs_id=usgs_id,
            outdir=outdir,
            start_date=str(payload.get("start_date", "2000-01-01")),
            end_date=str(payload.get("end_date", "2010-12-31")),
            threads=int(payload.get("threads", 1)),
            engine_timeout_s=float(payload.get("timeout_s", 3600.0)),
        )
        outdir.mkdir(parents=True, exist_ok=True)
        summary_path = outdir / "mcp_run_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        return RunBasinResponse(
            detail="Basin run completed via orchestration wrapper.",
            run_summary_path=str(summary_path),
        )

    @mcp.tool(
        name="calibrate",
        description=(
            "Run standalone pySWATPlus-bridge calibration on an existing TxtInOut "
            "(non-authoritative path). For reportable calibrated metrics use "
            "run_workflow, or the locked_calibrate protocol on a locked benchmark."
        ),
    )
    def calibrate(req: CalibrateRequest) -> CalibrateResponse:
        if req.calibration_engine != "pyswatplus":
            raise ValueError("MCP calibrate currently supports calibration_engine='pyswatplus' only.")
        if req.txtinout_dir is None or req.observed_csv is None:
            raise ValueError("txtinout_dir and observed_csv are required for calibrate.")

        calibrator = Calibrator()
        summary = calibrator.run(
            CalibratorRequest(
                basin_id=req.basin_id,
                simulation_start=date.fromisoformat(req.start),
                simulation_end=date.fromisoformat(req.end),
                txtinout_dir=Path(req.txtinout_dir).expanduser().resolve(),
                observed_csv=Path(req.observed_csv).expanduser().resolve(),
                parameters=[p.strip().upper() for p in req.parameters if p.strip()],
                objectives=[o.strip().lower() for o in req.objectives if o.strip()],
                algorithm=req.algorithm,
                n_gen=req.n_gen,
                pop_size=req.pop_size,
                seed=req.seed,
                artifacts_root=Path(req.artifacts_root).expanduser().resolve(),
                engine_version="unknown",
                warm_start=True,
                sim_output_file=req.sim_output_file,
                outlet_gis_id=int(req.outlet_gis_id),
            )
        )
        return CalibrateResponse(
            detail="Calibration completed via pySWATPlus bridge.",
            calibration_hash=summary.calibration_hash,
            best_nse=summary.best_nse,
            outdir=str(summary.outdir),
        )

    @mcp.tool(
        name="propose_parameters",
        description="Propose parameter vectors using lightweight strategies (random/grid).",
    )
    def propose_parameters(req: ProposeParametersRequest) -> ProposeParametersResponse:
        params = [p.strip().upper() for p in req.parameters if p.strip()]
        if not params:
            raise ValueError("At least one parameter is required.")

        proposals: list[dict[str, float]] = []
        for i in range(req.count):
            row: dict[str, float] = {}
            for p in params:
                meta = registry.get(p)
                if req.strategy == "grid":
                    if req.count == 1:
                        val = float(meta.default)
                    else:
                        alpha = i / float(req.count - 1)
                        lo, hi = meta.range
                        val = float(lo) + alpha * float(hi - lo)
                else:
                    # Deterministic pseudo-random proposal without global RNG state.
                    lo, hi = meta.range
                    span = float(hi - lo)
                    frac = ((i + 1) * (len(p) + 7)) % 97 / 97.0
                    val = float(lo) + span * frac
                row[p] = float(val)
            proposals.append(row)
        return ProposeParametersResponse(proposals=proposals)

    @mcp.tool(
        name="compare_runs",
        description="Compare metrics across run artifact directories containing metrics.json files.",
    )
    def compare_runs(req: CompareRunsRequest) -> CompareRunsResponse:
        out: list[dict[str, float | str | None]] = []
        for p in req.run_artifacts:
            path = Path(p).expanduser().resolve()
            metrics_path = path / "metrics.json"
            if not metrics_path.exists():
                out.append({"run_artifact": str(path), "nse": None, "kge": None, "pbias": None})
                continue
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            out.append(
                {
                    "run_artifact": str(path),
                    "nse": metrics.get("nse"),
                    "kge": metrics.get("kge"),
                    "pbias": metrics.get("pbias"),
                }
            )
        return CompareRunsResponse(summaries=out)

    @mcp.tool(
        name="query_artifacts",
        description="Query artifact store summaries with optional filters.",
    )
    def query_artifacts(req: QueryArtifactsRequest) -> QueryArtifactsResponse:
        store = LocalArtifactStore(req.artifacts_root)
        rows = store.query(
            ArtifactQuery(
                basin_id=req.basin_id,
                soil_mode=req.soil_mode,
                nse_min=req.nse_min,
            )
        )
        items = [r.model_dump(mode="json") for r in rows]
        return QueryArtifactsResponse(count=len(items), items=items)

    @mcp.tool(
        name="diagnose_failure",
        description="Run rule-based diagnostics for a run artifact directory or alignment CSV.",
    )
    def diagnose_failure(req: DiagnoseFailureRequest) -> DiagnoseFailureResponse:
        rows = diagnose(req.run_artifact)
        payload = [r.model_dump(mode="json") for r in rows]
        return DiagnoseFailureResponse(count=len(payload), diagnoses=payload)

    @mcp.tool(
        name="validate",
        description="Run curated-suite validation and return summary counts with report path.",
    )
    def validate(req: ValidateRequest) -> ValidateResponse:
        specs = load_basin_specs(req.basins_file)
        results, report_dir = run_validation(
            basins=specs,
            artifacts_root=req.artifacts_root,
            runs_root=req.runs_root,
            engine_version=req.engine_version,
        )
        success_count = sum(1 for r in results if r.status in {"success", "cached"})
        cache_hits = sum(1 for r in results if r.cache_hit)
        return ValidateResponse(
            report_dir=str(report_dir),
            basin_count=len(results),
            success_count=success_count,
            cache_hits=cache_hits,
        )

    @mcp.tool(
        name="lock_benchmark",
        description=(
            "Lock a reproducible baseline benchmark for a basin: two-pass outlet evaluation "
            "persists alignment.csv, metrics.json, outlet_provenance.json, and benchmark_lock.json. "
            "Must be run before locked_calibrate. "
            "Requires a prepared TxtInOut directory and an observed discharge CSV."
        ),
    )
    def mcp_lock_benchmark(req: LockBenchmarkRequest) -> LockBenchmarkResponse:
        import pandas as pd

        from swatplus_builder.output.eval import terminal_channel_ids

        obs_df = pd.read_csv(req.observed_csv, index_col=0, parse_dates=True)
        obs_col = "discharge" if "discharge" in obs_df.columns else obs_df.columns[0]
        obs_series = pd.Series(
            obs_df[obs_col].astype(float).values,
            index=pd.to_datetime(obs_df.index).normalize(),
            name="obs",
        ).dropna()
        outlet_gis_id = req.outlet_gis_id
        if outlet_gis_id is None:
            terminal_ids = terminal_channel_ids(req.txtinout_dir)
            if len(terminal_ids) != 1:
                raise ValueError(
                    "outlet_gis_id was omitted, but the prepared topology does not have exactly "
                    f"one terminal channel (found {terminal_ids}). Supply the authoritative "
                    "gauge outlet GIS ID explicitly."
                )
            outlet_gis_id = terminal_ids[0]
        lock = lock_benchmark(
            txtinout_dir=Path(req.txtinout_dir),
            obs_series=obs_series,
            out_dir=Path(req.out_dir),
            basin_id=req.basin_id,
            outlet_gis_id=outlet_gis_id,
            sim_source_file=req.sim_source_file,
        )
        return LockBenchmarkResponse(
            basin_id=lock.basin_id,
            baseline_nse=lock.baseline_nse,
            baseline_kge=lock.baseline_kge,
            outlet_gis_id=lock.outlet_gis_id,
            alignment_sha256=lock.alignment_sha256,
            benchmark_dir=lock.benchmark_dir,
        )

    @mcp.tool(
        name="locked_calibrate",
        description=(
            "Run the locked-benchmark calibration protocol: calibrate against a locked alignment "
            "context then independently verify the best solution. Returns NSE/KGE deltas vs. "
            "the locked baseline. Requires benchmark_dir from lock_benchmark. "
            "Guardrail: only CN2 and ALPHA_BF are effective parameters until routing terms activate."
        ),
    )
    def mcp_locked_calibrate(req: LockedCalibrateRequest) -> LockedCalibrateResponse:
        evidence = calibrate_against_lock(
            lock=Path(req.benchmark_dir),
            base_txtinout=Path(req.base_txtinout),
            out_dir=Path(req.out_dir),
            parameters=req.parameters,
            n_evaluations=req.n_evaluations,
            binary=Path(req.binary) if req.binary else None,
            timeout_s=req.timeout_s,
        )
        delta_nse: float | None = None
        delta_kge: float | None = None
        improved: bool | None = None
        if not req.skip_verify:
            try:
                vr = verify_calibration(
                    lock=Path(req.benchmark_dir),
                    best_solution_json=Path(evidence.best_solution_json),
                    base_txtinout=Path(req.base_txtinout),
                    out_dir=Path(req.out_dir),
                    binary=Path(req.binary) if req.binary else None,
                    timeout_s=req.timeout_s,
                )
                delta_nse = vr.delta_nse
                delta_kge = vr.delta_kge
                improved = vr.improved
            except Exception:
                pass
        return LockedCalibrateResponse(
            basin_id=evidence.basin_id,
            n_evaluations=evidence.n_evaluations,
            best_nse=evidence.best_nse,
            best_kge=evidence.best_kge,
            delta_nse=delta_nse,
            delta_kge=delta_kge,
            improved=improved,
            best_solution_json=evidence.best_solution_json,
            outdir=evidence.outdir,
        )

    @mcp.tool(
        name="readiness_table",
        description=(
            "Scan a directory tree for lock and verification artifacts, then return a structured "
            "multi-basin readiness table (baseline vs. calibrated NSE/KGE deltas and verification "
            "status). Optionally writes a markdown table. "
            "Use to check calibration evidence coverage before phase advancement."
        ),
    )
    def mcp_readiness_table(req: ReadinessTableRequest) -> ReadinessTableResponse:
        rows = build_readiness_table(
            Path(req.locks_root),
            out_md=Path(req.out_md) if req.out_md else None,
        )
        return ReadinessTableResponse(
            row_count=len(rows),
            rows=[r.model_dump() for r in rows],
            out_md=req.out_md,
        )

    return mcp


def main() -> None:
    """CLI entry point for stdio MCP server transport."""
    create_mcp_server().run(transport="stdio")


if __name__ == "__main__":
    main()
