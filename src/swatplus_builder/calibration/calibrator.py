"""Build->Calibrate bridge for revised Phase 3C (pySWATPlus-backed)."""

from __future__ import annotations

import csv
import json
import os
import shutil
import sys
import traceback
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from .. import __version__
from ..artifacts import (
    ArtifactMetadata,
    ArtifactMetrics,
    ArtifactProvenance,
    ArtifactRecord,
    LocalArtifactStore,
    RunConfig,
    compute_content_hash,
)
from ..errors import SwatBuilderExternalError, SwatBuilderInputError, SwatBuilderPipelineError
from ..output.metadata import try_git_sha
from ..params import get_parameter
from .pyswatplus_runtime import ensure_pyswatplus_runtime


class EvaluationRecord(BaseModel):
    """One objective evaluation emitted by the calibration backend."""

    generation: int = Field(..., ge=0)
    individual: int = Field(..., ge=0)
    parameters: dict[str, float] = Field(default_factory=dict)
    metrics: dict[str, float] = Field(default_factory=dict)


class BackendRequest(BaseModel):
    """Request payload sent to backend adapter."""

    txtinout_dir: Path
    algorithm: str
    n_gen: int = Field(..., ge=1)
    pop_size: int = Field(..., ge=1)
    objectives: list[str]
    parameter_bounds: list[dict[str, object]]
    parameter_initial: list[dict[str, object]]
    observed_csv: Path
    calsim_dir: Path
    sim_output_file: str = "basin_sd_cha_day.txt"
    sim_column: str = "flo_out"
    obs_column: str = "discharge"
    seed: int = 42
    outlet_gis_id: int = 1
    binary: Path | None = None


class BackendResult(BaseModel):
    """Normalized backend output from pySWATPlus execution."""

    evaluations: list[EvaluationRecord]
    parity_log_csv: Path | None = None


class CalibrationSummary(BaseModel):
    """Calibration-level result summary returned by `Calibrator.run`."""

    calibration_hash: str
    cache_hit: bool
    n_evaluations: int
    best_nse: float | None = None
    outdir: Path
    history_csv: Path
    summary_md: Path
    best_solution_json: Path
    pareto_csv: Path | None = None


class CalibratorRequest(BaseModel):
    """Input contract for pySWATPlus-backed calibration."""

    basin_id: str
    simulation_start: date
    simulation_end: date
    txtinout_dir: Path
    observed_csv: Path | None = None
    parameters: list[str]
    objectives: list[str] = Field(min_length=1, description="Metric objectives (e.g. ['nse', 'kge']). At least one required.")
    algorithm: str = "nsga2"
    n_gen: int = Field(30, ge=1)
    pop_size: int = Field(32, ge=1)
    seed: int = 42
    artifacts_root: Path
    engine_version: str = "unknown"
    builder_git_sha: str | None = None
    warm_start: bool = True
    sim_output_file: str = "basin_sd_cha_day.txt"
    outlet_gis_id: int = 1
    binary: Path | None = None


class CalibrationBackend(Protocol):
    """Backend protocol used by `Calibrator`."""

    def run(self, request: BackendRequest) -> BackendResult:
        """Execute calibration and return normalized evaluation history."""


class PySwatPlusBackend:
    """Best-effort adapter around `pySWATPlus.Calibration`.

    This adapter keeps imports lazy and surfaces clear typed errors when API
    shape is incompatible with expected integration.
    """

    def run(self, request: BackendRequest) -> BackendResult:
        ensure_pyswatplus_runtime()
        try:
            import pySWATPlus as mod  # noqa: N813  (upstream package name is camelCase)

            calibration_cls = getattr(mod, "Calibration", None)
            if calibration_cls is None:
                raise SwatBuilderExternalError("pySWATPlus Calibration class not found")
        except Exception as exc:
            raise SwatBuilderExternalError(
                "Failed to initialize pySWATPlus calibration backend",
                error=str(exc),
            ) from exc

        calsim_dir = request.calsim_dir.expanduser().resolve()
        if calsim_dir.exists():
            for child in calsim_dir.iterdir():
                if child.is_dir():
                    import shutil

                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
        calsim_dir.mkdir(parents=True, exist_ok=True)

        txtinout_dir = request.txtinout_dir.expanduser().resolve()
        txtinout_for_backend = _prepare_txtinout_for_pyswatplus(
            base_txtinout=txtinout_dir,
            calsim_dir=calsim_dir,
            binary_override=request.binary,
        )

        _apply_platform_compatibility_patches(mod)

        objective = request.objectives[0].lower()
        indicator = _to_indicator(objective)
        extract_data = {
            request.sim_output_file: {
                "has_units": True,
                "apply_filter": {"gis_id": [int(request.outlet_gis_id)]},
            }
        }
        normalized_obs_csv = _normalize_observed_csv(request.observed_csv, request.obs_column, calsim_dir.parent)
        observe_data = {
            request.sim_output_file: {
                "obs_file": str(normalized_obs_csv),
                "date_format": "%Y-%m-%d",
            }
        }
        # pySWATPlus currently binds one indicator per monitored file, so the
        # first supported objective is used as the primary indicator.  Future
        # upgrades of the pySWATPlus API should pass the full list for true
        # multi-objective Pareto optimisation (NSGA2).
        objective_config = {
            request.sim_output_file: {
                "sim_col": request.sim_column,
                "obs_col": request.obs_column,
                "indicator": indicator,
            }
        }
        parameters = [_to_pyswatplus_bound(p) for p in request.parameter_bounds]

        try:
            calibration = calibration_cls(
                parameters=parameters,
                calsim_dir=calsim_dir,
                txtinout_dir=txtinout_for_backend,
                extract_data=extract_data,
                observe_data=observe_data,
                objective_config=objective_config,
                algorithm=_to_algorithm(request.algorithm),
                n_gen=request.n_gen,
                pop_size=request.pop_size,
                max_workers=1,
            )
            _ = calibration.parameter_optimization()
        except Exception as exc:
            _write_bridge_failure_artifact(
                calsim_dir=calsim_dir,
                exc=exc,
                staged_txtinout=txtinout_for_backend,
                request=request,
                failure_stage="parameter_optimization",
            )
            raise SwatBuilderExternalError(
                "pySWATPlus calibration execution failed",
                error=str(exc),
                diagnostic_artifact=str(calsim_dir / "bridge_failure_diagnostic.json"),
            ) from exc

        hist_path = calsim_dir / "optimization_history.json"
        if not hist_path.exists():
            raise SwatBuilderExternalError(
                "pySWATPlus did not produce optimization_history.json",
                path=str(hist_path),
            )
        raw_hist = json.loads(hist_path.read_text(encoding="utf-8"))
        evaluations = _history_to_evaluations(raw_hist, param_names=[p["name"] for p in parameters], objective=objective)
        if not evaluations:
            raise SwatBuilderExternalError("pySWATPlus produced empty evaluation history")
        parity_log_csv = _apply_metric_parity(
            evaluations=evaluations,
            calsim_dir=calsim_dir,
            sim_output_file=request.sim_output_file,
            normalized_obs_csv=normalized_obs_csv,
            obs_column=request.obs_column,
            outlet_gis_id=int(request.outlet_gis_id),
            pop_size=int(request.pop_size),
            staged_txtinout=txtinout_for_backend,
            base_txtinout=txtinout_dir,
            binary=request.binary,
        )
        return BackendResult(evaluations=evaluations, parity_log_csv=parity_log_csv)


@dataclass
class Calibrator:
    """pySWATPlus-backed calibration orchestrator with artifact persistence."""

    backend: CalibrationBackend | None = None

    def run(self, request: CalibratorRequest) -> CalibrationSummary:
        txt = request.txtinout_dir.expanduser().resolve()
        if not txt.exists():
            raise SwatBuilderInputError("txtinout_dir does not exist", path=str(txt))
        obs = request.observed_csv.expanduser().resolve() if request.observed_csv else None
        if obs is not None and not obs.exists():
            raise SwatBuilderInputError("observed_csv does not exist", path=str(obs))
        if obs is None:
            raise SwatBuilderInputError("observed_csv is required for pySWATPlus calibration.")
        if not request.parameters:
            raise SwatBuilderInputError("At least one parameter is required.")
        if not request.objectives:
            raise SwatBuilderInputError("At least one objective is required.")

        git_sha = request.builder_git_sha or try_git_sha(Path(__file__).resolve().parents[3]) or "unknown"
        calibration_hash = _calibration_hash(request, git_sha=git_sha)
        calib_dir = (
            request.artifacts_root.expanduser().resolve() / "runs" / "calibrations" / calibration_hash
        )
        history_csv = calib_dir / "history.csv"
        summary_md = calib_dir / "summary.md"
        best_solution_json = calib_dir / "best_solution.json"
        pareto_csv = calib_dir / "pareto.csv"

        if request.warm_start and history_csv.exists() and best_solution_json.exists():
            best_nse = _read_best_nse(best_solution_json)
            return CalibrationSummary(
                calibration_hash=calibration_hash,
                cache_hit=True,
                n_evaluations=_history_len(history_csv),
                best_nse=best_nse,
                outdir=calib_dir,
                history_csv=history_csv,
                summary_md=summary_md,
                best_solution_json=best_solution_json,
                pareto_csv=pareto_csv if pareto_csv.exists() else None,
            )

        param_initial: list[dict[str, object]] = []
        param_bounds: list[dict[str, object]] = []
        for name in request.parameters:
            p = get_parameter(name)
            param_initial.append(p.to_pyswatplus_dict(float(p.default)))
            param_bounds.append(p.to_pyswatplus_bounds_dict())

        backend = self.backend or PySwatPlusBackend()
        result = backend.run(
            BackendRequest(
                txtinout_dir=txt,
                algorithm=request.algorithm,
                n_gen=request.n_gen,
                pop_size=request.pop_size,
                objectives=request.objectives,
                parameter_bounds=param_bounds,
                parameter_initial=param_initial,
                observed_csv=obs,
                calsim_dir=calib_dir / "pyswatplus_run",
                sim_output_file=request.sim_output_file,
                seed=request.seed,
                outlet_gis_id=int(request.outlet_gis_id),
                binary=(
                    request.binary.expanduser().resolve()
                    if request.binary is not None
                    else None
                ),
            )
        )
        if not result.evaluations:
            raise SwatBuilderPipelineError("Calibration backend returned zero evaluations.")

        calib_dir.mkdir(parents=True, exist_ok=True)
        _write_history(history_csv, result.evaluations)
        best = _best_eval(result.evaluations)
        best_solution_json.write_text(
            json.dumps(
                {
                    "generation": best.generation,
                    "individual": best.individual,
                    "metrics": best.metrics,
                    "parameters": best.parameters,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        _write_summary(summary_md, request, calibration_hash, result.evaluations)
        if len(request.objectives) > 1:
            _write_pareto(pareto_csv, request.objectives, result.evaluations)

        # Persist each evaluation as standard run artifact for global caching.
        store = LocalArtifactStore(request.artifacts_root)
        for ev in result.evaluations:
            cfg = RunConfig(
                basin_id=request.basin_id,
                simulation_start=request.simulation_start,
                simulation_end=request.simulation_end,
                parameters={
                    k: {"value": float(v), "scope": get_parameter(k).scope.value}
                    for k, v in ev.parameters.items()
                },
                options={
                    "source": "pyswatplus_calibration",
                    "calibration_hash": calibration_hash,
                    "generation": ev.generation,
                    "individual": ev.individual,
                    "algorithm": request.algorithm,
                },
            )
            run_hash = compute_content_hash(
                cfg, engine_version=request.engine_version, builder_git_sha=git_sha
            )
            if request.warm_start and store.exists(run_hash):
                continue
            store.write(
                ArtifactRecord(
                    content_hash=run_hash,
                    config=cfg,
                    metadata=ArtifactMetadata(
                        run_id=run_hash,
                        timestamp_utc=datetime.now(timezone.utc).isoformat(),
                        engine_version=request.engine_version,
                        builder_version=__version__,
                        git_sha=git_sha,
                        notes=["pyswatplus_calibration_eval", f"calibration_hash:{calibration_hash}"],
                    ),
                    metrics=ArtifactMetrics.model_validate(ev.metrics),
                    provenance=ArtifactProvenance(
                        parent_run=None, proposal_source="pyswatplus_calibration"
                    ),
                )
            )

        return CalibrationSummary(
            calibration_hash=calibration_hash,
            cache_hit=False,
            n_evaluations=len(result.evaluations),
            best_nse=float(best.metrics["nse"]) if isinstance(best.metrics.get("nse"), (int, float)) else None,
            outdir=calib_dir,
            history_csv=history_csv,
            summary_md=summary_md,
            best_solution_json=best_solution_json,
            pareto_csv=pareto_csv if pareto_csv.exists() else None,
        )


def _calibration_hash(request: CalibratorRequest, *, git_sha: str) -> str:
    payload = {
        "basin_id": request.basin_id,
        "simulation_start": request.simulation_start.isoformat(),
        "simulation_end": request.simulation_end.isoformat(),
        "txtinout_dir": str(request.txtinout_dir.expanduser().resolve()),
        "observed_csv": None
        if request.observed_csv is None
        else str(request.observed_csv.expanduser().resolve()),
        "parameters": sorted(request.parameters),
        "objectives": sorted(request.objectives),
        "algorithm": request.algorithm.lower(),
        "n_gen": int(request.n_gen),
        "pop_size": int(request.pop_size),
        "seed": int(request.seed),
        "engine_version": request.engine_version,
        "sim_output_file": request.sim_output_file,
        "outlet_gis_id": int(request.outlet_gis_id),
        "builder_git_sha": git_sha,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(raw).hexdigest()


def _write_history(path: Path, evaluations: list[EvaluationRecord]) -> None:
    metric_names = sorted({k for e in evaluations for k in e.metrics})
    param_names = sorted({k for e in evaluations for k in e.parameters})
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["generation", "individual"]
            + [f"param_{p}" for p in param_names]
            + [f"metric_{m}" for m in metric_names],
        )
        writer.writeheader()
        for e in evaluations:
            row: dict[str, object] = {"generation": e.generation, "individual": e.individual}
            for p in param_names:
                row[f"param_{p}"] = e.parameters.get(p)
            for m in metric_names:
                row[f"metric_{m}"] = e.metrics.get(m)
            writer.writerow(row)


def _best_eval(evaluations: list[EvaluationRecord]) -> EvaluationRecord:
    def score(e: EvaluationRecord) -> float:
        v = e.metrics.get("nse")
        return float(v) if isinstance(v, (int, float)) else float("-inf")

    return max(evaluations, key=score)


def _write_summary(
    path: Path,
    request: CalibratorRequest,
    calibration_hash: str,
    evaluations: list[EvaluationRecord],
) -> None:
    best = _best_eval(evaluations)
    lines = [
        "# Calibration Summary",
        "",
        f"- Calibration hash: `{calibration_hash}`",
        f"- Basin: `{request.basin_id}`",
        f"- Algorithm: `{request.algorithm}`",
        f"- Evaluations: `{len(evaluations)}`",
        f"- Best NSE: `{best.metrics.get('nse')}`",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_pareto(path: Path, objectives: list[str], evaluations: list[EvaluationRecord]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["generation", "individual"] + [f"metric_{m}" for m in objectives],
        )
        writer.writeheader()
        for e in evaluations:
            row = {"generation": e.generation, "individual": e.individual}
            for m in objectives:
                row[f"metric_{m}"] = e.metrics.get(m)
            writer.writerow(row)


def _to_pyswatplus_bound(p: dict[str, object]) -> dict[str, object]:
    name = str(p["name"]).lower()
    lo = float(p.get("min", p.get("lower_bound")))
    hi = float(p.get("max", p.get("upper_bound")))
    out: dict[str, object] = {
        "name": name,
        "change_type": str(p.get("change_type", "absval")),
        "lower_bound": lo,
        "upper_bound": hi,
    }
    return out


def _to_indicator(obj: str) -> str:
    m = {
        "nse": "NSE",
        "kge": "KGE",
        "mse": "MSE",
        "rmse": "RMSE",
        "mare": "MARE",
    }
    if obj not in m:
        raise SwatBuilderInputError(
            f"Unsupported objective for pySWATPlus bridge: {obj}",
            supported=sorted(m.keys()),
        )
    return m[obj]


def _to_algorithm(name: str) -> str:
    key = name.strip().lower()
    mapping = {"ga": "GA", "de": "DE", "nsga2": "NSGA2"}
    if key not in mapping:
        raise SwatBuilderInputError(
            f"Unsupported pySWATPlus algorithm: {name}",
            supported=sorted(mapping.keys()),
        )
    return mapping[key]


def _normalize_observed_csv(obs_path: Path, obs_col: str, out_dir: Path) -> Path:
    import pandas as pd

    df = pd.read_csv(obs_path, index_col=0, parse_dates=True)
    if obs_col in df.columns:
        s = df[obs_col].astype(float)
        idx = pd.to_datetime(df.index)
    elif "obs" in df.columns:
        s = df["obs"].astype(float)
        idx = pd.to_datetime(df.index)
    elif "date" in df.columns and obs_col in df.columns:
        idx = pd.to_datetime(df["date"])
        s = df[obs_col].astype(float)
    elif "date" in df.columns and "obs" in df.columns:
        idx = pd.to_datetime(df["date"])
        s = df["obs"].astype(float)
    else:
        raise SwatBuilderInputError(
            "Observed CSV must contain either obs column or requested obs_column",
            path=str(obs_path),
            obs_column=obs_col,
        )
    out = pd.DataFrame({"date": idx.strftime("%Y-%m-%d"), obs_col: s.values})
    target = out_dir / "observed_for_pyswatplus.csv"
    out.to_csv(target, index=False)
    return target


def _history_to_evaluations(
    hist: dict[str, object],
    *,
    param_names: list[str],
    objective: str,
) -> list[EvaluationRecord]:
    out: list[EvaluationRecord] = []
    for gen_key, payload in hist.items():
        if not isinstance(payload, dict):
            continue
        pop = payload.get("pop")
        obj = payload.get("obj")
        if not isinstance(pop, list) or not isinstance(obj, list):
            continue
        gen = int(gen_key) - 1 if str(gen_key).isdigit() else 0
        for i, vec in enumerate(pop):
            if not isinstance(vec, list):
                continue
            params = {
                param_names[j].upper(): float(vec[j])
                for j in range(min(len(param_names), len(vec)))
            }
            mval = None
            if i < len(obj):
                if isinstance(obj[i], list) and len(obj[i]) > 0:
                    mval = float(obj[i][0])
                elif isinstance(obj[i], (int, float)):
                    mval = float(obj[i])
            metrics = {objective: float(mval)} if isinstance(mval, (int, float)) else {}
            out.append(
                EvaluationRecord(
                    generation=gen,
                    individual=i,
                    parameters=params,
                    metrics=metrics,
                )
            )
    return out


def _apply_metric_parity(
    *,
    evaluations: list[EvaluationRecord],
    calsim_dir: Path,
    sim_output_file: str,
    normalized_obs_csv: Path,
    obs_column: str,
    outlet_gis_id: int,
    pop_size: int,
    staged_txtinout: Path | None = None,
    base_txtinout: Path | None = None,
    binary: Path | None = None,
) -> Path:
    import pandas as pd

    from ..output.eval import evaluate_run

    obs_df = pd.read_csv(normalized_obs_csv)
    if "date" not in obs_df.columns or obs_column not in obs_df.columns:
        raise SwatBuilderInputError(
            "Normalized observed CSV is missing required columns for parity evaluation.",
            path=str(normalized_obs_csv),
            required=["date", obs_column],
        )
    obs_series = pd.Series(
        obs_df[obs_column].astype(float).values,
        index=pd.to_datetime(obs_df["date"], errors="coerce").dt.normalize(),
        name="obs",
    ).dropna()
    if obs_series.empty:
        raise SwatBuilderInputError(
            "Normalized observed CSV has no valid rows for parity evaluation.",
            path=str(normalized_obs_csv),
        )

    parity_rows: list[dict[str, object]] = []
    previous_output_hash: str | None = None
    for ev in evaluations:
        raw_nse = ev.metrics.get("nse")
        sim_idx = int(ev.generation) * int(pop_size) + int(ev.individual) + 1
        sim_dir = calsim_dir / f"sim_{sim_idx}"
        sim_file = sim_dir / sim_output_file
        if not sim_file.exists():
            raise SwatBuilderPipelineError(
                "Expected simulation output file missing during metric parity evaluation.",
                sim_index=sim_idx,
                path=str(sim_file),
            )

        changed_files: list[str] = []
        if staged_txtinout is not None and staged_txtinout.exists():
            changed_files = _detect_changed_input_files(
                baseline_txtinout=staged_txtinout,
                sim_txtinout=sim_dir,
            )
            significant_changes = [f for f in changed_files if Path(f).name.lower() not in {"file.cio"}]
            if not significant_changes:
                raise SwatBuilderPipelineError(
                    "Calibration proposal did not modify any SWAT+ input file.",
                    sim_index=sim_idx,
                    generation=int(ev.generation),
                    individual=int(ev.individual),
                    parameters=ev.parameters,
                    staged_txtinout=str(staged_txtinout),
                    sim_dir=str(sim_dir),
                )

        align_df, metrics, _diagnostics = evaluate_run(
            sim_file,
            obs_series,
            outlet_gis_id=int(outlet_gis_id),
            return_diagnostics=True,
        )
        nse = float(metrics["nse"]) if isinstance(metrics.get("nse"), (int, float)) else float("nan")
        kge = float(metrics["kge"]) if isinstance(metrics.get("kge"), (int, float)) else float("nan")
        ev.metrics = {"nse": nse, "kge": kge}
        output_hash = _hash_file(sim_file)
        output_changed = previous_output_hash != output_hash if previous_output_hash is not None else True
        previous_output_hash = output_hash

        first_date = str(align_df.index.min().date()) if len(align_df.index) else ""
        last_date = str(align_df.index.max().date()) if len(align_df.index) else ""
        parity_rows.append(
            {
                "generation": int(ev.generation),
                "individual": int(ev.individual),
                "sim_index": sim_idx,
                "sim_output_file": sim_output_file,
                "outlet_gis_id": int(outlet_gis_id),
                "unit_convention": "flow_m3s",
                "aligned_days": int(len(align_df)),
                "obs_mean": float(align_df["obs"].mean()),
                "obs_std": float(align_df["obs"].std(ddof=0)),
                "obs_min": float(align_df["obs"].min()),
                "obs_max": float(align_df["obs"].max()),
                "sim_mean": float(align_df["sim"].mean()),
                "sim_std": float(align_df["sim"].std(ddof=0)),
                "sim_min": float(align_df["sim"].min()),
                "sim_max": float(align_df["sim"].max()),
                "first_date": first_date,
                "last_date": last_date,
                "bridge_reported_nse": nse,
                "bridge_reported_kge": kge,
                "pyswatplus_raw_objective_nse": float(raw_nse)
                if isinstance(raw_nse, (int, float))
                else None,
                "input_changed_files_count": int(len(changed_files)),
                "input_changed_files_sample": ";".join(changed_files[:12]),
                "sim_output_sha256": output_hash,
                "sim_output_mtime_utc": datetime.fromtimestamp(
                    sim_file.stat().st_mtime,
                    tz=timezone.utc,
                ).isoformat(),
                "sim_output_changed_vs_previous_eval": bool(output_changed),
            }
        )
        if os.getenv("SWATPLUS_BUILDER_KEEP_CAL_SIM_DIRS", "0") != "1":
            shutil.rmtree(sim_dir, ignore_errors=True)

    if _needs_authoritative_rerun(evaluations=evaluations, parity_rows=parity_rows):
        if base_txtinout is not None:
            parity_rows = _rerun_metric_parity_with_direct_objective(
                evaluations=evaluations,
                obs_series=obs_series,
                base_txtinout=base_txtinout,
                calsim_dir=calsim_dir,
                sim_output_file=sim_output_file,
                outlet_gis_id=int(outlet_gis_id),
                binary=binary,
            )

    parity_log_csv = calsim_dir.parent / "metric_parity_log.csv"
    pd.DataFrame(parity_rows).to_csv(parity_log_csv, index=False)
    return parity_log_csv


def _needs_authoritative_rerun(
    *,
    evaluations: list[EvaluationRecord],
    parity_rows: list[dict[str, object]],
) -> bool:
    if not evaluations or not parity_rows:
        return False
    unique_param_vectors = {
        json.dumps({k: float(v) for k, v in sorted(ev.parameters.items())}, sort_keys=True)
        for ev in evaluations
    }
    unique_nse = {
        round(float(ev.metrics.get("nse")), 12)
        for ev in evaluations
        if isinstance(ev.metrics.get("nse"), (int, float))
    }
    unique_output_hash = {
        str(row.get("sim_output_sha256", ""))
        for row in parity_rows
        if isinstance(row.get("sim_output_sha256"), str)
    }
    return len(unique_param_vectors) > 1 and len(unique_nse) <= 1 and len(unique_output_hash) <= 1


def _rerun_metric_parity_with_direct_objective(
    *,
    evaluations: list[EvaluationRecord],
    obs_series: object,
    base_txtinout: Path,
    calsim_dir: Path,
    sim_output_file: str,
    outlet_gis_id: int,
    binary: Path | None,
) -> list[dict[str, object]]:
    import pandas as pd

    from .real_engine import make_real_objective, params_hash

    rerun_root = calsim_dir.parent / "objective_reruns"
    objective = make_real_objective(
        base_txtinout=base_txtinout,
        observed_series=obs_series,
        work_root=rerun_root,
        outlet_gis_id=int(outlet_gis_id),
        binary=binary,
        objective_sim_file=sim_output_file,
        strict_objective_file=False,
        allow_outlet_autodetect=False,
    )

    parity_rows: list[dict[str, object]] = []
    previous_output_hash: str | None = None
    for ev in evaluations:
        raw_nse = ev.metrics.get("nse")
        metrics = objective({k: float(v) for k, v in ev.parameters.items()})
        nse = float(metrics["nse"]) if isinstance(metrics.get("nse"), (int, float)) else float("nan")
        kge = float(metrics["kge"]) if isinstance(metrics.get("kge"), (int, float)) else float("nan")
        ev.metrics = {"nse": nse, "kge": kge}

        run_hash = params_hash({k: float(v) for k, v in ev.parameters.items()})
        run_txt = rerun_root / run_hash / "TxtInOut"
        align_file = run_txt / "alignment_calibration.csv"
        sim_file = run_txt / sim_output_file
        if not align_file.exists() or not sim_file.exists():
            raise SwatBuilderPipelineError(
                "Authoritative rerun did not produce required alignment or simulation output files.",
                run_hash=run_hash,
                alignment_file=str(align_file),
                sim_file=str(sim_file),
            )
        align_df = pd.read_csv(align_file, index_col=0, parse_dates=True)
        changed_files = _detect_changed_input_files(
            baseline_txtinout=base_txtinout,
            sim_txtinout=run_txt,
        )
        output_hash = _hash_file(sim_file)
        output_changed = previous_output_hash != output_hash if previous_output_hash is not None else True
        previous_output_hash = output_hash
        first_date = str(align_df.index.min().date()) if len(align_df.index) else ""
        last_date = str(align_df.index.max().date()) if len(align_df.index) else ""
        parity_rows.append(
            {
                "generation": int(ev.generation),
                "individual": int(ev.individual),
                "sim_index": int(ev.generation) * 10_000 + int(ev.individual) + 1,
                "sim_output_file": sim_output_file,
                "outlet_gis_id": int(outlet_gis_id),
                "unit_convention": "flow_m3s",
                "metric_source": "evaluate_run_real_objective_rerun",
                "aligned_days": int(len(align_df)),
                "obs_mean": float(align_df["obs"].mean()),
                "obs_std": float(align_df["obs"].std(ddof=0)),
                "obs_min": float(align_df["obs"].min()),
                "obs_max": float(align_df["obs"].max()),
                "sim_mean": float(align_df["sim"].mean()),
                "sim_std": float(align_df["sim"].std(ddof=0)),
                "sim_min": float(align_df["sim"].min()),
                "sim_max": float(align_df["sim"].max()),
                "first_date": first_date,
                "last_date": last_date,
                "bridge_reported_nse": nse,
                "bridge_reported_kge": kge,
                "pyswatplus_raw_objective_nse": float(raw_nse)
                if isinstance(raw_nse, (int, float))
                else None,
                "input_changed_files_count": int(len(changed_files)),
                "input_changed_files_sample": ";".join(changed_files[:12]),
                "sim_output_sha256": output_hash,
                "sim_output_mtime_utc": datetime.fromtimestamp(
                    sim_file.stat().st_mtime,
                    tz=timezone.utc,
                ).isoformat(),
                "sim_output_changed_vs_previous_eval": bool(output_changed),
            }
        )
    return parity_rows


def _prepare_txtinout_for_pyswatplus(
    *,
    base_txtinout: Path,
    calsim_dir: Path,
    binary_override: Path | None = None,
) -> Path:
    if not base_txtinout.exists():
        raise SwatBuilderInputError("txtinout_dir does not exist", path=str(base_txtinout))
    staged = calsim_dir.parent / "_txtinout_staged"
    if staged.exists():
        shutil.rmtree(staged, ignore_errors=True)
    shutil.copytree(base_txtinout, staged)

    existing_exec = _list_executable_files(staged)
    if len(existing_exec) == 1:
        return staged
    if len(existing_exec) > 1:
        raise SwatBuilderExternalError(
            "TxtInOut contains multiple executable files; pySWATPlus requires exactly one.",
            txtinout=str(staged),
            executables=[str(p.name) for p in existing_exec],
        )

    from ..run.swatplus import locate_binary

    binary = binary_override if binary_override is not None else locate_binary()
    binary = Path(binary).expanduser().resolve()
    target = staged / Path(binary).name
    shutil.copy2(binary, target)
    os.chmod(target, os.stat(target).st_mode | 0o111)  # noqa: S103  (engine binary needs the exec bit)
    _copy_runtime_companions(binary=Path(binary), target_dir=staged)
    _prepare_txtinout_for_objective(staged)
    return staged


def _list_executable_files(folder: Path) -> list[Path]:
    return [p for p in folder.iterdir() if p.is_file() and os.access(p, os.X_OK)]


def _copy_runtime_companions(*, binary: Path, target_dir: Path) -> None:
    src_dir = binary.parent
    allowed_suffix = {".dylib", ".so", ".dll", ".sqlite"}
    for p in src_dir.iterdir():
        if not p.is_file():
            continue
        if p.resolve() == binary.resolve():
            continue
        if p.suffix.lower() in allowed_suffix or p.name.startswith("swatplus_"):
            shutil.copy2(p, target_dir / p.name)


def _prepare_txtinout_for_objective(txtinout: Path) -> None:
    _set_print_prt_for_daily_channel_outputs(txtinout / "print.prt")
    for name in (
        "channel_day.txt",
        "channel_sd_day.txt",
        "basin_cha_day.txt",
        "basin_sd_cha_day.txt",
        "channel_mon.txt",
        "channel_sd_mon.txt",
        "basin_cha_mon.txt",
        "basin_sd_cha_mon.txt",
        "channel_yr.txt",
        "channel_sd_yr.txt",
        "basin_cha_yr.txt",
        "basin_sd_cha_yr.txt",
        "alignment_calibration.csv",
    ):
        (txtinout / name).unlink(missing_ok=True)


def _detect_changed_input_files(*, baseline_txtinout: Path, sim_txtinout: Path) -> list[str]:
    baseline_files = _collect_tracked_input_hashes(baseline_txtinout)
    sim_files = _collect_tracked_input_hashes(sim_txtinout)
    changed: list[str] = []
    for rel in sorted(set(baseline_files) | set(sim_files)):
        base_hash = baseline_files.get(rel)
        sim_hash = sim_files.get(rel)
        if base_hash != sim_hash:
            changed.append(rel)
    return changed


def _collect_tracked_input_hashes(folder: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in folder.rglob("*"):
        if not path.is_file():
            continue
        rel = str(path.relative_to(folder))
        if not _is_tracked_input_file(rel):
            continue
        out[rel] = _hash_file(path)
    return out


def _is_tracked_input_file(rel_path: str) -> bool:
    name = Path(rel_path).name.lower()
    if name.endswith((".dylib", ".so", ".dll", ".sqlite")):
        return False
    if name in {
        "simulation.out",
        "channel_day.txt",
        "channel_sd_day.txt",
        "basin_cha_day.txt",
        "basin_sd_cha_day.txt",
        "channel_mon.txt",
        "channel_sd_mon.txt",
        "basin_cha_mon.txt",
        "basin_sd_cha_mon.txt",
        "channel_yr.txt",
        "channel_sd_yr.txt",
        "basin_cha_yr.txt",
        "basin_sd_cha_yr.txt",
        "alignment_calibration.csv",
        "optimization_history.json",
        "metric_parity_log.csv",
    }:
        return False
    return True


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _set_print_prt_for_daily_channel_outputs(path: Path) -> None:
    if not path.exists():
        raise SwatBuilderInputError("required print.prt not found", path=str(path))
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if len(lines) < 10:
        raise SwatBuilderInputError("malformed print.prt", path=str(path))

    top_idx = 2 if len(lines) > 2 else None
    if top_idx is not None:
        parts = lines[top_idx].split()
        if len(parts) >= 1 and parts[0].isdigit():
            parts[0] = "0"
            lines[top_idx] = "  ".join(parts)

    wanted = {"channel", "channel_sd", "basin_cha", "basin_sd_cha"}
    found: set[str] = set()
    for i, ln in enumerate(lines):
        parts = ln.split()
        if len(parts) != 5:
            continue
        obj = parts[0]
        if obj in wanted:
            parts[1] = "y"
            lines[i] = "  ".join(parts)
            found.add(obj)
    missing = wanted - found
    if missing:
        raise SwatBuilderInputError(
            "print.prt missing required object rows for calibration outputs",
            path=str(path),
            missing=sorted(missing),
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_bridge_failure_artifact(
    calsim_dir: Path,
    exc: BaseException,
    staged_txtinout: Path | None,
    request: BackendRequest,
    failure_stage: str = "unknown",
) -> None:
    """Persist structured diagnostics when the pySWATPlus bridge fails.

    Writes ``bridge_failure_diagnostic.json`` to ``calsim_dir`` so agents
    can triage failures without re-running the calibration.  The artifact
    includes stdout/stderr from the exception chain, a staged-TxtInOut
    manifest, and a sanitized request summary.
    """
    try:
        calsim_dir.mkdir(parents=True, exist_ok=True)

        # Collect staged manifest (file names + sizes only; never content).
        staged_manifest: list[dict[str, object]] = []
        if staged_txtinout is not None and staged_txtinout.exists():
            for p in sorted(staged_txtinout.rglob("*")):
                if p.is_file():
                    try:
                        size = p.stat().st_size
                    except OSError:
                        size = -1
                    staged_manifest.append({"path": str(p.relative_to(staged_txtinout)), "size_bytes": size})

        # Collect chained traceback strings.
        tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)

        # Sanitized request summary.
        req_summary: dict[str, object] = {
            "algorithm": request.algorithm,
            "n_gen": request.n_gen,
            "pop_size": request.pop_size,
            "objectives": request.objectives,
            "parameter_bounds": [str(p.get("name")) for p in request.parameter_bounds],
            "sim_output_file": request.sim_output_file,
            "outlet_gis_id": int(request.outlet_gis_id),
            "seed": request.seed,
            "txtinout_dir": str(request.txtinout_dir),
            "calsim_dir": str(calsim_dir),
            "staged_txtinout": str(staged_txtinout) if staged_txtinout else None,
        }

        from .bridge_diagnostics import classify_bridge_failure
        failure_class, failure_detail = classify_bridge_failure(
            error_type=type(exc).__name__,
            error_message=str(exc),
            staged_file_count=len(staged_manifest),
            failure_stage=failure_stage,
            traceback_text="".join(tb_lines),
        )

        artifact = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "failure_stage": failure_stage,
            "failure_class": failure_class.value,
            "failure_detail": failure_detail,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "traceback": "".join(tb_lines),
            "request_summary": req_summary,
            "staged_txtinout_manifest": staged_manifest,
            "staged_file_count": len(staged_manifest),
        }
        out_path = calsim_dir / "bridge_failure_diagnostic.json"
        out_path.write_text(json.dumps(artifact, indent=2, default=str) + "\n", encoding="utf-8")
    except Exception:
        pass  # Never let diagnostic writing mask the original exception.


_PY_SWATPLUS_SUPPORTED_UPTO: tuple[int, int, int] = (1, 4, 0)
"""Maximum supported pySWATPlus version (exclusive).

Patches target the 1.3.x API surface.  Before upgrading past this bound the
structural assertions in :func:`_assert_pyswatplus_compatible` and every patch
in :func:`_apply_platform_compatibility_patches` must be reviewed.
"""


def _assert_pyswatplus_compatible(mod: object) -> None:
    """Assert structural API contracts before applying compatibility patches.

    Raises ``RuntimeError`` with a clear message if any expected attribute,
    method, or class is missing (indicating an upstream breaking change).
    """
    missing: list[str] = []

    # Top-level
    if not hasattr(mod, "utils"):
        missing.append("module pySWATPlus.utils")
    if not hasattr(mod, "cpu"):
        missing.append("module pySWATPlus.cpu")
    if not hasattr(mod, "txtinout_reader"):
        missing.append("module pySWATPlus.txtinout_reader")

    # Sub-modules accessed by patches
    cal_mod = getattr(mod, "calibration", None)
    if cal_mod is None:
        missing.append("module pySWATPlus.calibration")
    else:
        if not hasattr(cal_mod, "concurrent"):
            missing.append("module pySWATPlus.calibration.concurrent")
        else:
            futures_mod = getattr(cal_mod, "concurrent", None)
            if not hasattr(futures_mod, "futures"):
                missing.append("pySWATPlus.calibration.concurrent.futures")

    # Specific functions/classes that get patched
    utils = getattr(mod, "utils", None)
    if utils is not None and not callable(getattr(utils, "_is_real_executable", None)):
        missing.append("pySWATPlus.utils._is_real_executable (callable)")

    cpu_mod = getattr(mod, "cpu", None)
    if cpu_mod is not None and not callable(getattr(cpu_mod, "_simulation_output", None)):
        missing.append("pySWATPlus.cpu._simulation_output (callable)")

    txt_mod = getattr(mod, "txtinout_reader", None)
    if txt_mod is not None:
        if not hasattr(txt_mod, "TxtinoutReader"):
            missing.append("pySWATPlus.txtinout_reader.TxtinoutReader")
        elif not hasattr(txt_mod.TxtinoutReader, "_run_swat_exe"):
            missing.append("pySWATPlus.txtinout_reader.TxtinoutReader._run_swat_exe")

    if missing:
        raise RuntimeError(
            "pySWATPlus API contract mismatch — the following expected symbols "
            f"are missing:\n  " + "\n  ".join(missing) + "\n\n"
            f"This package requires pySWATPlus < {_PY_SWATPLUS_SUPPORTED_UPTO[0]}.{_PY_SWATPLUS_SUPPORTED_UPTO[1]}.0. "
            "If you have upgraded pySWATPlus, either pin it back or update the "
            "compatibility patches in calibrator.py."
        )


def _apply_platform_compatibility_patches(mod: object) -> None:
    _assert_pyswatplus_compatible(mod)
    if not sys.platform.startswith("darwin"):
        return
    utils = getattr(mod, "utils", None)
    if utils is None:
        return
    if not getattr(utils, "_swatbuilder_macho_patch", False):
        original = getattr(utils, "_is_real_executable", None)
        if callable(original):
            macho_headers = {
                b"\xcf\xfa\xed\xfe",
                b"\xfe\xed\xfa\xcf",
                b"\xca\xfe\xba\xbe",
                b"\xbe\xba\xfe\xca",
            }

            def _patched_is_real_executable(file_path: Path) -> bool:
                if original(file_path):
                    return True
                if not file_path.is_file() or not os.access(file_path, os.X_OK):
                    return False
                try:
                    with open(file_path, "rb") as f:
                        header = f.read(4)
                except OSError:
                    return False
                return header in macho_headers

            utils._is_real_executable = _patched_is_real_executable
            utils._swatbuilder_macho_patch = True

    calibration_module = getattr(mod, "calibration", None)
    if calibration_module is None:
        return
    futures_mod = getattr(calibration_module, "concurrent", None)
    if futures_mod is None:
        return
    if not getattr(calibration_module, "_swatbuilder_threadpool_patch", False):
        from concurrent.futures import ThreadPoolExecutor

        futures_mod.futures.ProcessPoolExecutor = ThreadPoolExecutor
        calibration_module._swatbuilder_threadpool_patch = True

    cpu_mod = getattr(mod, "cpu", None)
    if cpu_mod is not None and not getattr(cpu_mod, "_swatbuilder_keep_simdirs_patch", False):
        original_sim_output = getattr(cpu_mod, "_simulation_output", None)
        if callable(original_sim_output):
            def _patched_sim_output(*args: object, **kwargs: object) -> dict[str, object]:
                kwargs["clean_setup"] = False
                return original_sim_output(*args, **kwargs)
            cpu_mod._simulation_output = _patched_sim_output
            cpu_mod._swatbuilder_keep_simdirs_patch = True

    txt_reader_mod = getattr(mod, "txtinout_reader", None)
    if txt_reader_mod is None:
        return
    if not getattr(txt_reader_mod, "_swatbuilder_env_patch", False):
        from ..run.swatplus import run_solver_subprocess

        logger = txt_reader_mod.logger

        def _patched_run_swat_exe(self: object) -> None:
            # All solver invocations must go through run_solver_subprocess —
            # never call the binary directly with subprocess.Popen/run.
            exe = Path(self.exe_file).resolve()
            txtinout = Path(self.root_dir).resolve()
            try:
                returncode, stdout_tail, stderr_tail = run_solver_subprocess(
                    exe, txtinout, threads=1
                )
                if stdout_tail:
                    for line in stdout_tail.splitlines():
                        if line.strip():
                            logger.info(line.strip())
                if returncode != 0:
                    raise RuntimeError(
                        f"SWAT+ engine exited {returncode}. stderr: {stderr_tail[-500:]}"
                    )
            except Exception as exc:
                logger.error(f"Failed to run SWAT+: {exc}")
                raise

        txt_reader_mod.TxtinoutReader._run_swat_exe = _patched_run_swat_exe
        txt_reader_mod._swatbuilder_env_patch = True


def _read_best_nse(path: Path) -> float | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    m = payload.get("metrics", {})
    if isinstance(m, dict) and isinstance(m.get("nse"), (int, float)):
        return float(m["nse"])
    return None


def _history_len(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8") as f:
            return max(sum(1 for _ in f) - 1, 0)
    except Exception:
        return 0
