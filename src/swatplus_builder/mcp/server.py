"""Phase 3D MCP server with a narrow typed 8-tool surface."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from ..artifacts import ArtifactQuery, LocalArtifactStore
from ..calibration.calibrator import Calibrator, CalibratorRequest
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


def create_mcp_server() -> FastMCP:
    """Create and register the Phase 3D MCP tool surface."""
    mcp = FastMCP(name="swatplus-builder")

    @mcp.tool(
        name="build_project",
        description=(
            "Build a SWAT+ project from a basin spec. "
            "Current status: placeholder while project build toolchain is promoted to MCP."
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
            detail="Basin spec was validated and build manifest was written.",
            manifest_path=str(manifest_path),
        )

    @mcp.tool(
        name="run_basin",
        description=(
            "Run a basin configuration end-to-end. "
            "Current status: placeholder while run orchestrator is promoted to MCP."
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
            "Run calibration on a basin. "
            "Current status: placeholder while MCP calibration execution wrapper is finalized."
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

    return mcp


def main() -> None:
    """CLI entry point for stdio MCP server transport."""
    create_mcp_server().run(transport="stdio")


if __name__ == "__main__":
    main()
