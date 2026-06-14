"""Typed SWAT+ forward function and surrogate-dataset bridge.

Phase 3C.4 requires a callable forward pass:
    ``f(theta, basin) -> simulated_timeseries``

This module provides:
1) A typed forward API with content-hash cache short-circuit.
2) Extraction of surrogate-training rows from run artifacts.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, Field

from .. import __version__
from ..artifacts import (
    ArtifactMetadata,
    ArtifactMetrics,
    ArtifactProvenance,
    ArtifactQuery,
    ArtifactRecord,
    LocalArtifactStore,
    RunConfig,
    compute_content_hash,
)
from ..errors import SwatBuilderInputError, SwatBuilderPipelineError
from ..output.metadata import try_git_sha
from ..params import get_parameter, validate_value
from .real_engine import (
    RealObjective,
    make_real_objective,
    params_hash,
)


class ParameterVector(BaseModel):
    """Typed parameter vector used by the forward pass.

    Failure modes:
    - Raises ``SwatBuilderInputError`` if a parameter name is unknown.
    - Raises ``SwatBuilderInputError`` if a value violates registry bounds.
    """

    values: dict[str, float] = Field(default_factory=dict)


class BasinSpec(BaseModel):
    """Typed basin/run inputs for the forward pass."""

    basin_id: str
    simulation_start: date
    simulation_end: date
    base_txtinout: Path
    alignment_csv: Path
    outlet_gis_id: int = 1
    binary: Path | None = None
    objective_sim_file: str = "basin_sd_cha_day.txt"
    strict_objective_file: bool = True
    allow_outlet_autodetect: bool = False


class SimulatedTimeseries(BaseModel):
    """Forward-pass response carrying aligned timeseries + metrics."""

    content_hash: str
    cache_hit: bool
    basin_id: str
    objective_sim_file: str
    requested_outlet_gis_id: int
    dates: list[str]
    observed: list[float]
    simulated: list[float]
    metrics: dict[str, float]
    artifact_dir: Path


class ForwardRequest(BaseModel):
    """Input request for :func:`forward_simulate`.

    Example:
        >>> req = ForwardRequest(
        ...     basin=BasinSpec(
        ...         basin_id="usgs_01547700",
        ...         simulation_start=date(2015, 1, 1),
        ...         simulation_end=date(2015, 12, 31),
        ...         base_txtinout=Path("run/TxtInOut"),
        ...         alignment_csv=Path("outputs/alignment.csv"),
        ...     ),
        ...     theta=ParameterVector(values={"CN2": 60.0, "ALPHA_BF": 0.05, "SURLAG": 3.0}),
        ...     artifacts_root=Path("tests/_artifacts/forward"),
        ...     engine_version="swatplus-61.0.6",
        ... )
    """

    basin: BasinSpec
    theta: ParameterVector
    artifacts_root: Path
    engine_version: str = "unknown"
    builder_git_sha: str | None = None
    warm_start: bool = True


class SurrogateDatasetRow(BaseModel):
    """One training row extracted from forward artifacts."""

    content_hash: str
    basin_id: str
    simulation_start: date
    simulation_end: date
    parameters: dict[str, float]
    metrics: dict[str, float]
    n_days: int
    mean_observed: float
    mean_simulated: float
    timeseries_csv: Path
    artifact_dir: Path


class SurrogateDataset(BaseModel):
    """Structured dataset payload for surrogate training."""

    rows: list[SurrogateDatasetRow]
    parameter_names: list[str]


class ForwardVerification(BaseModel):
    """Verification summary for one forward artifact."""

    content_hash: str
    passed: bool
    checks: dict[str, bool]
    details: dict[str, str]


ObjectiveFactory = Callable[..., RealObjective]


def forward_simulate(
    request: ForwardRequest,
    *,
    _objective_factory: ObjectiveFactory = make_real_objective,
) -> SimulatedTimeseries:
    """Run typed forward simulation with content-hash caching.

    Failure modes:
    - ``SwatBuilderInputError`` for invalid parameter names/ranges or missing files.
    - ``SwatBuilderPipelineError`` when objective run succeeds but aligned timeseries is missing.
    """

    basin = request.basin
    theta = _validate_theta(request.theta.values)
    base_txt = basin.base_txtinout.expanduser().resolve()
    alignment_csv = basin.alignment_csv.expanduser().resolve()
    if not base_txt.exists():
        raise SwatBuilderInputError("base_txtinout does not exist", path=str(base_txt))
    if not alignment_csv.exists():
        raise SwatBuilderInputError("alignment_csv does not exist", path=str(alignment_csv))

    git_sha = request.builder_git_sha or try_git_sha(Path(__file__).resolve().parents[3]) or "unknown"
    cfg = RunConfig(
        basin_id=basin.basin_id,
        simulation_start=basin.simulation_start,
        simulation_end=basin.simulation_end,
        parameters={
            n: {"value": float(v), "scope": get_parameter(n).scope.value}
            for n, v in theta.items()
        },
        options={
            "objective_mode": "real_engine_forward",
            "objective_sim_file": basin.objective_sim_file,
            "outlet_gis_id": int(basin.outlet_gis_id),
        },
    )
    content_hash = compute_content_hash(
        cfg,
        engine_version=request.engine_version,
        builder_git_sha=git_sha,
    )
    store = LocalArtifactStore(request.artifacts_root)
    run_dir = store.runs_dir / content_hash
    ts_csv = run_dir / "timeseries.csv"

    if request.warm_start and store.exists(content_hash) and ts_csv.exists():
        rec = store.read(content_hash)
        return _build_response_from_csv(
            content_hash=content_hash,
            cache_hit=True,
            basin_id=basin.basin_id,
            objective_sim_file=basin.objective_sim_file,
            outlet_gis_id=int(basin.outlet_gis_id),
            metrics=_metrics_from_record(rec),
            ts_csv=ts_csv,
            artifact_dir=run_dir,
        )

    obs = pd.read_csv(alignment_csv, index_col=0, parse_dates=True)
    if "obs" not in obs.columns:
        raise SwatBuilderInputError("alignment_csv missing obs column", path=str(alignment_csv))
    obs_series = pd.Series(
        obs["obs"].astype(float),
        index=pd.to_datetime(obs.index).normalize(),
        name="obs",
    ).dropna()
    if obs_series.empty:
        raise SwatBuilderInputError("alignment_csv has no observed rows", path=str(alignment_csv))

    work_root = request.artifacts_root.expanduser().resolve() / "forward_runs"
    objective = _objective_factory(
        base_txtinout=base_txt,
        observed_series=obs_series,
        work_root=work_root,
        outlet_gis_id=int(basin.outlet_gis_id),
        binary=basin.binary,
        threads=1,
        timeout_s=3600.0,
        objective_sim_file=basin.objective_sim_file,
        strict_objective_file=bool(basin.strict_objective_file),
        allow_outlet_autodetect=bool(basin.allow_outlet_autodetect),
    )
    metrics = objective(theta)

    objective_run_txt = work_root / params_hash(theta) / "TxtInOut"
    alignment_out = objective_run_txt / "alignment_calibration.csv"
    if not alignment_out.exists():
        raise SwatBuilderPipelineError(
            "Objective run did not produce alignment_calibration.csv",
            expected=str(alignment_out),
        )

    record = ArtifactRecord(
        content_hash=content_hash,
        config=cfg,
        metadata=ArtifactMetadata(
            run_id=content_hash,
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            engine_version=request.engine_version,
            builder_version=__version__,
            git_sha=git_sha,
            notes=["forward_function:3C.4"],
        ),
        metrics=ArtifactMetrics.model_validate(metrics),
        provenance=ArtifactProvenance(proposal_source="forward_simulate"),
    )
    store.write(record)
    run_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(alignment_out, index_col=0, parse_dates=True)
    df.to_csv(ts_csv)

    return _build_response_from_csv(
        content_hash=content_hash,
        cache_hit=False,
        basin_id=basin.basin_id,
        objective_sim_file=basin.objective_sim_file,
        outlet_gis_id=int(basin.outlet_gis_id),
        metrics={k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))},
        ts_csv=ts_csv,
        artifact_dir=run_dir,
    )


def extract_surrogate_dataset(
    artifacts_root: Path | str,
    *,
    basin_id: str | None = None,
) -> SurrogateDataset:
    """Build surrogate-training rows from forward artifacts.

    Failure modes:
    - ``SwatBuilderInputError`` if artifact root is missing.
    """

    root = Path(artifacts_root).expanduser().resolve()
    if not root.exists():
        raise SwatBuilderInputError("artifacts_root does not exist", path=str(root))

    store = LocalArtifactStore(root)
    q = ArtifactQuery(basin_id=basin_id) if basin_id is not None else ArtifactQuery()
    summaries = store.query(q)
    rows: list[SurrogateDatasetRow] = []
    param_names: set[str] = set()
    for s in summaries:
        run_dir = store.runs_dir / s.content_hash
        ts_csv = run_dir / "timeseries.csv"
        if not ts_csv.exists():
            continue
        rec = store.read(s.content_hash)
        if rec.metrics is None:
            continue
        df = pd.read_csv(ts_csv, index_col=0, parse_dates=True)
        if "obs" not in df.columns or "sim" not in df.columns or df.empty:
            continue
        params = {k: float(v.value) for k, v in rec.config.parameters.items()}
        param_names.update(params.keys())
        rows.append(
            SurrogateDatasetRow(
                content_hash=s.content_hash,
                basin_id=rec.config.basin_id,
                simulation_start=rec.config.simulation_start,
                simulation_end=rec.config.simulation_end,
                parameters=params,
                metrics={
                    k: float(v)
                    for k, v in rec.metrics.model_dump(exclude_none=True).items()
                    if isinstance(v, (int, float))
                },
                n_days=int(len(df)),
                mean_observed=float(df["obs"].astype(float).mean()),
                mean_simulated=float(df["sim"].astype(float).mean()),
                timeseries_csv=ts_csv,
                artifact_dir=run_dir,
            )
        )
    rows.sort(key=lambda r: r.content_hash)
    return SurrogateDataset(rows=rows, parameter_names=sorted(param_names))


def _validate_theta(theta: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for name, raw in theta.items():
        try:
            get_parameter(name)
        except KeyError as exc:
            raise SwatBuilderInputError(f"Unknown calibration parameter: {name}") from exc
        val = float(raw)
        try:
            validate_value(name, val)
        except ValueError as exc:
            raise SwatBuilderInputError(str(exc)) from exc
        out[name] = val
    return out


def _metrics_from_record(record: ArtifactRecord) -> dict[str, float]:
    if record.metrics is None:
        return {}
    return {
        k: float(v)
        for k, v in record.metrics.model_dump(exclude_none=True).items()
        if isinstance(v, (int, float))
    }


def _build_response_from_csv(
    *,
    content_hash: str,
    cache_hit: bool,
    basin_id: str,
    objective_sim_file: str,
    outlet_gis_id: int,
    metrics: dict[str, float],
    ts_csv: Path,
    artifact_dir: Path,
) -> SimulatedTimeseries:
    df = pd.read_csv(ts_csv, index_col=0, parse_dates=True)
    if "obs" not in df.columns or "sim" not in df.columns:
        raise SwatBuilderPipelineError("timeseries.csv missing required columns", path=str(ts_csv))
    df = df[["obs", "sim"]].dropna()
    return SimulatedTimeseries(
        content_hash=content_hash,
        cache_hit=cache_hit,
        basin_id=basin_id,
        objective_sim_file=objective_sim_file,
        requested_outlet_gis_id=outlet_gis_id,
        dates=[str(d.date()) for d in pd.to_datetime(df.index)],
        observed=[float(v) for v in df["obs"]],
        simulated=[float(v) for v in df["sim"]],
        metrics=metrics,
        artifact_dir=artifact_dir,
    )


def verify_forward_artifact(
    artifacts_root: Path | str,
    content_hash: str,
    *,
    expected_objective_sim_file: str | None = None,
    expected_outlet_gis_id: int | None = None,
    allow_outlet_autodetect: bool = False,
    min_days: int = 30,
) -> ForwardVerification:
    """Verify one forward artifact against trace + output consistency checks.

    Checks include:
    - artifact files exist and parse
    - objective trace exists and matches expected source/outlet constraints
    - timeseries has required columns and enough rows
    - recomputed NSE matches stored NSE (within tolerance)
    """

    root = Path(artifacts_root).expanduser().resolve()
    store = LocalArtifactStore(root)
    if not store.exists(content_hash):
        raise SwatBuilderInputError("Artifact not found", content_hash=content_hash, root=str(root))

    run_dir = store.runs_dir / content_hash
    rec = store.read(content_hash)
    ts_csv = run_dir / "timeseries.csv"
    if not ts_csv.exists():
        raise SwatBuilderPipelineError("timeseries.csv not found for artifact", path=str(ts_csv))

    theta = {k: float(v.value) for k, v in rec.config.parameters.items()}
    trace_path = root / "forward_runs" / params_hash(theta) / "objective_trace.json"
    checks: dict[str, bool] = {}
    details: dict[str, str] = {}

    checks["trace_exists"] = trace_path.exists()
    details["trace_path"] = str(trace_path)
    trace: dict[str, object] = {}
    if trace_path.exists():
        import json

        trace = json.loads(trace_path.read_text(encoding="utf-8"))

    if expected_objective_sim_file is None:
        expected_objective_sim_file = str(rec.config.options.get("objective_sim_file", ""))
    actual_source = str(trace.get("actual_sim_file", ""))
    checks["objective_source_match"] = (
        bool(expected_objective_sim_file)
        and bool(actual_source)
        and actual_source == expected_objective_sim_file
    )
    details["expected_objective_sim_file"] = str(expected_objective_sim_file)
    details["actual_objective_sim_file"] = actual_source

    selected_outlet = trace.get("selected_outlet_gis_id")
    requested_outlet = trace.get("requested_outlet_gis_id")
    outlet_auto = bool(trace.get("outlet_autodetected", False))
    if expected_outlet_gis_id is None:
        expected_outlet_gis_id = int(rec.config.options.get("outlet_gis_id", 1))
    checks["outlet_match"] = selected_outlet == expected_outlet_gis_id or requested_outlet == expected_outlet_gis_id
    checks["outlet_autodetect_policy"] = allow_outlet_autodetect or not outlet_auto
    details["expected_outlet_gis_id"] = str(expected_outlet_gis_id)
    details["selected_outlet_gis_id"] = str(selected_outlet)
    details["outlet_autodetected"] = str(outlet_auto)

    df = pd.read_csv(ts_csv, index_col=0, parse_dates=True)
    checks["timeseries_columns"] = "obs" in df.columns and "sim" in df.columns
    checks["min_days"] = len(df) >= int(min_days)
    details["n_days"] = str(len(df))
    if checks["timeseries_columns"] and len(df) > 0:
        x = df[["obs", "sim"]].dropna()
        checks["non_empty_overlap"] = len(x) > 0
        if len(x) > 0:
            den = float(((x["obs"] - float(x["obs"].mean())) ** 2).sum())
            nse = float("nan") if den == 0.0 else 1.0 - float(((x["obs"] - x["sim"]) ** 2).sum()) / den
            stored = None
            if rec.metrics is not None:
                stored_val = rec.metrics.model_dump(exclude_none=True).get("nse")
                if isinstance(stored_val, (int, float)):
                    stored = float(stored_val)
            if stored is None:
                checks["nse_match"] = False
            else:
                checks["nse_match"] = abs(stored - nse) <= 1e-9
                details["nse_stored"] = f"{stored:.12f}"
                details["nse_recomputed"] = f"{nse:.12f}"
    else:
        checks["non_empty_overlap"] = False
        checks["nse_match"] = False

    passed = all(checks.values())
    return ForwardVerification(
        content_hash=content_hash,
        passed=passed,
        checks=checks,
        details=details,
    )
