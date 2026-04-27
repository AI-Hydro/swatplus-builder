"""Surrogate training and uncertainty ensemble utilities (Phase 3D PR-3D-04)."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

import numpy as np
from pydantic import BaseModel, Field

from ..calibration.forward import SurrogateDatasetRow, extract_surrogate_dataset
from ..errors import SwatBuilderInputError
from .loop import SurrogatePrediction


class SurrogateTrainingRequest(BaseModel):
    """Typed request for fitting an uncertainty-aware surrogate ensemble."""

    artifacts_root: Path
    output_root: Path
    target_metric: Literal["nse", "kge", "log_nse", "pbias"] = "nse"
    basin_id: str | None = None
    train_basin_ids: list[str] | None = None
    exclude_basin_ids: list[str] | None = None
    parameter_names: list[str] | None = None
    ensemble_size: int = Field(default=5, ge=2, le=50)
    holdout_fraction: float = Field(default=0.2, ge=0.0, lt=0.9)
    min_rows: int = Field(default=10, ge=3)
    seed: int = 42


class SurrogateMember(BaseModel):
    """One ensemble member coefficients and fit diagnostics."""

    member_index: int
    seed: int
    intercept: float
    coefficients: dict[str, float]
    train_rmse: float
    holdout_rmse: float | None = None
    holdout_mae: float | None = None


class SurrogateEnsemble(BaseModel):
    """Persisted surrogate ensemble artifact descriptor."""

    ensemble_id: str
    created_utc: str
    target_metric: str
    parameter_names: list[str]
    train_rows: int
    holdout_rows: int
    train_rmse_mean: float
    holdout_rmse_mean: float | None
    holdout_mae_mean: float | None
    members: list[SurrogateMember]
    artifact_dir: Path


class SurrogatePredictionEstimate(BaseModel):
    """Prediction payload with uncertainty from ensemble spread."""

    objective_mean: float
    objective_std: float
    member_predictions: list[float]


class RoutingDecision(BaseModel):
    """Uncertainty-gated routing decision."""

    path: Literal["surrogate", "real_engine"]
    uncertainty: float
    threshold: float
    reason: str


class HoldoutEvaluationRequest(BaseModel):
    """Typed request for surrogate-vs-engine hold-out evaluation."""

    artifacts_root: Path
    output_root: Path
    holdout_basin_ids: list[str] = Field(..., min_length=1)
    target_metric: Literal["nse", "kge", "log_nse", "pbias"] = "nse"
    parameter_names: list[str] | None = None
    ensemble_size: int = Field(default=5, ge=2, le=50)
    holdout_fraction: float = Field(default=0.2, ge=0.0, lt=0.9)
    min_rows: int = Field(default=10, ge=3)
    seed: int = 42
    agreement_nse_threshold: float = 0.8
    train_basin_ids: list[str] | None = None


class HoldoutEvaluationCase(BaseModel):
    """One hold-out row prediction vs observed metric."""

    basin_id: str
    content_hash: str
    observed_metric: float
    predicted_metric: float
    prediction_uncertainty: float
    absolute_error: float


class HoldoutEvaluationReport(BaseModel):
    """Hold-out agreement report for surrogate readiness checks."""

    ensemble_id: str
    target_metric: str
    holdout_basin_ids: list[str]
    train_basin_ids: list[str]
    n_train_rows: int
    n_holdout_rows: int
    agreement_nse: float
    median_absolute_error: float
    passed: bool
    agreement_nse_threshold: float
    report_dir: Path
    cases: list[HoldoutEvaluationCase]


def train_surrogate_ensemble(request: SurrogateTrainingRequest) -> SurrogateEnsemble:
    """Fit and persist a bootstrap linear-regression ensemble.

    Failure modes:
    - Raises ``SwatBuilderInputError`` if artifact roots are missing or dataset rows are insufficient.
    - Raises ``SwatBuilderInputError`` when rows do not contain the requested target metric.
    """

    artifacts_root = request.artifacts_root.expanduser().resolve()
    if not artifacts_root.exists():
        raise SwatBuilderInputError("artifacts_root does not exist", path=str(artifacts_root))

    dataset = extract_surrogate_dataset(artifacts_root=artifacts_root, basin_id=request.basin_id)
    filtered_rows = _rows_with_metric(dataset.rows, request.target_metric)
    filtered_rows = _filter_rows_by_basin(
        filtered_rows,
        include_basins=request.train_basin_ids,
        exclude_basins=request.exclude_basin_ids,
    )
    if len(filtered_rows) < request.min_rows:
        raise SwatBuilderInputError(
            "Not enough rows for surrogate training",
            required=request.min_rows,
            available=len(filtered_rows),
            target_metric=request.target_metric,
        )

    parameter_names = (
        sorted({p.upper() for p in request.parameter_names})
        if request.parameter_names is not None
        else dataset.parameter_names
    )
    if not parameter_names:
        raise SwatBuilderInputError("No parameter names available for surrogate training")

    X, y = _matrix_from_rows(filtered_rows, parameter_names, request.target_metric)
    n_rows = X.shape[0]
    holdout_size = int(round(request.holdout_fraction * n_rows))
    if holdout_size >= n_rows:
        holdout_size = n_rows - 1
    if holdout_size < 0:
        holdout_size = 0

    idx_all = np.arange(n_rows)
    rng = np.random.default_rng(request.seed)
    rng.shuffle(idx_all)
    idx_holdout = idx_all[:holdout_size]
    idx_train = idx_all[holdout_size:]
    if idx_train.size == 0:
        raise SwatBuilderInputError("No training rows after holdout split", holdout_size=holdout_size)

    X_train = X[idx_train]
    y_train = y[idx_train]
    X_holdout = X[idx_holdout] if idx_holdout.size > 0 else None
    y_holdout = y[idx_holdout] if idx_holdout.size > 0 else None

    members: list[SurrogateMember] = []
    for member_idx in range(request.ensemble_size):
        member_seed = request.seed + (member_idx + 1) * 1009
        mrng = np.random.default_rng(member_seed)
        boot_idx = mrng.integers(0, X_train.shape[0], size=X_train.shape[0])
        bX = X_train[boot_idx]
        by = y_train[boot_idx]

        intercept, coef = _fit_linear_regression(bX, by)
        train_pred = _predict_linear(X_train, intercept, coef)
        train_rmse = _rmse(y_train, train_pred)

        holdout_rmse: float | None = None
        holdout_mae: float | None = None
        if X_holdout is not None and y_holdout is not None and len(y_holdout) > 0:
            hold_pred = _predict_linear(X_holdout, intercept, coef)
            holdout_rmse = _rmse(y_holdout, hold_pred)
            holdout_mae = _mae(y_holdout, hold_pred)

        members.append(
            SurrogateMember(
                member_index=member_idx,
                seed=member_seed,
                intercept=float(intercept),
                coefficients={p: float(coef[i]) for i, p in enumerate(parameter_names)},
                train_rmse=float(train_rmse),
                holdout_rmse=(None if holdout_rmse is None else float(holdout_rmse)),
                holdout_mae=(None if holdout_mae is None else float(holdout_mae)),
            )
        )

    ensemble_id = _compute_ensemble_id(request, filtered_rows, parameter_names)
    artifact_dir = request.output_root.expanduser().resolve() / "surrogates" / ensemble_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    train_rmse_mean = float(np.mean([m.train_rmse for m in members]))
    hold_rmse_vals = [m.holdout_rmse for m in members if m.holdout_rmse is not None]
    hold_mae_vals = [m.holdout_mae for m in members if m.holdout_mae is not None]

    ensemble = SurrogateEnsemble(
        ensemble_id=ensemble_id,
        created_utc=datetime.now(timezone.utc).isoformat(),
        target_metric=request.target_metric,
        parameter_names=parameter_names,
        train_rows=int(len(idx_train)),
        holdout_rows=int(len(idx_holdout)),
        train_rmse_mean=train_rmse_mean,
        holdout_rmse_mean=(None if not hold_rmse_vals else float(np.mean(hold_rmse_vals))),
        holdout_mae_mean=(None if not hold_mae_vals else float(np.mean(hold_mae_vals))),
        members=members,
        artifact_dir=artifact_dir,
    )

    _write_training_rows_csv(
        artifact_dir / "training_rows.csv",
        rows=filtered_rows,
        parameter_names=parameter_names,
        target_metric=request.target_metric,
    )
    (artifact_dir / "model_cards.json").write_text(
        json.dumps([m.model_dump(mode="json") for m in members], indent=2) + "\n",
        encoding="utf-8",
    )
    (artifact_dir / "training_summary.json").write_text(
        json.dumps(ensemble.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )

    return ensemble


def predict_with_surrogate(
    ensemble: SurrogateEnsemble,
    parameters: dict[str, float],
) -> SurrogatePredictionEstimate:
    """Predict objective and uncertainty from a trained ensemble."""

    vector: list[float] = []
    for p in ensemble.parameter_names:
        if p not in parameters:
            raise SwatBuilderInputError("Missing parameter for surrogate prediction", parameter=p)
        vector.append(float(parameters[p]))
    x = np.asarray(vector, dtype=float)

    preds: list[float] = []
    for member in ensemble.members:
        coef = np.asarray([member.coefficients[p] for p in ensemble.parameter_names], dtype=float)
        val = float(member.intercept + np.dot(x, coef))
        preds.append(val)

    return SurrogatePredictionEstimate(
        objective_mean=float(np.mean(preds)),
        objective_std=float(np.std(preds)),
        member_predictions=preds,
    )


def decide_routing_path(*, uncertainty: float, threshold: float) -> RoutingDecision:
    """Decide whether to use surrogate result or run real engine."""
    if uncertainty <= threshold:
        return RoutingDecision(
            path="surrogate",
            uncertainty=float(uncertainty),
            threshold=float(threshold),
            reason="Ensemble uncertainty is below routing threshold.",
        )
    return RoutingDecision(
        path="real_engine",
        uncertainty=float(uncertainty),
        threshold=float(threshold),
        reason="Ensemble uncertainty exceeds threshold; authoritative run required.",
    )


def make_loop_surrogate_predictor(
    ensemble: SurrogateEnsemble,
    *,
    minimum_uncertainty: float = 1e-9,
) -> Callable[[dict[str, float], int], SurrogatePrediction]:
    """Create a loop-compatible surrogate predictor callable."""

    def _predict(parameters: dict[str, float], iteration: int) -> SurrogatePrediction:
        _ = iteration
        pred = predict_with_surrogate(ensemble, parameters)
        unc = max(float(pred.objective_std), float(minimum_uncertainty))
        metrics = {ensemble.target_metric: float(pred.objective_mean)}
        return SurrogatePrediction(
            objective=float(pred.objective_mean),
            uncertainty=unc,
            metrics=metrics,
        )

    return _predict


def evaluate_surrogate_holdout(request: HoldoutEvaluationRequest) -> HoldoutEvaluationReport:
    """Evaluate surrogate agreement on hold-out basins.

    Agreement metric:
    - NSE between engine-observed target metric values (obs) and surrogate
      predicted metric values (sim) over hold-out rows.
    """

    artifacts_root = request.artifacts_root.expanduser().resolve()
    if not artifacts_root.exists():
        raise SwatBuilderInputError("artifacts_root does not exist", path=str(artifacts_root))

    dataset = extract_surrogate_dataset(artifacts_root=artifacts_root)
    all_rows = _rows_with_metric(dataset.rows, request.target_metric)
    holdout_set = {b.strip() for b in request.holdout_basin_ids if b.strip()}
    if not holdout_set:
        raise SwatBuilderInputError("holdout_basin_ids must contain at least one basin id")

    holdout_rows = [r for r in all_rows if r.basin_id in holdout_set]
    if len(holdout_rows) < 2:
        raise SwatBuilderInputError(
            "Not enough holdout rows for agreement NSE",
            required=2,
            available=len(holdout_rows),
        )

    inferred_train_basins = sorted({r.basin_id for r in all_rows if r.basin_id not in holdout_set})
    train_basins = request.train_basin_ids if request.train_basin_ids is not None else inferred_train_basins
    if not train_basins:
        raise SwatBuilderInputError("No training basins available after holdout split")

    ensemble = train_surrogate_ensemble(
        SurrogateTrainingRequest(
            artifacts_root=artifacts_root,
            output_root=request.output_root,
            target_metric=request.target_metric,
            train_basin_ids=train_basins,
            exclude_basin_ids=sorted(holdout_set),
            parameter_names=request.parameter_names,
            ensemble_size=request.ensemble_size,
            holdout_fraction=request.holdout_fraction,
            min_rows=request.min_rows,
            seed=request.seed,
        )
    )

    obs_vals: list[float] = []
    pred_vals: list[float] = []
    cases: list[HoldoutEvaluationCase] = []
    for row in holdout_rows:
        pred = predict_with_surrogate(ensemble, row.parameters)
        observed = float(row.metrics[request.target_metric])
        predicted = float(pred.objective_mean)
        abs_err = abs(observed - predicted)
        obs_vals.append(observed)
        pred_vals.append(predicted)
        cases.append(
            HoldoutEvaluationCase(
                basin_id=row.basin_id,
                content_hash=row.content_hash,
                observed_metric=observed,
                predicted_metric=predicted,
                prediction_uncertainty=float(pred.objective_std),
                absolute_error=float(abs_err),
            )
        )

    agreement = _safe_nse(obs_vals, pred_vals)
    median_abs_error = float(np.median(np.asarray([c.absolute_error for c in cases], dtype=float)))
    passed = bool(np.isfinite(agreement) and agreement >= request.agreement_nse_threshold)

    report_dir = ensemble.artifact_dir / "holdout_evaluation"
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_holdout_cases_csv(report_dir / "cases.csv", cases=cases)

    report = HoldoutEvaluationReport(
        ensemble_id=ensemble.ensemble_id,
        target_metric=request.target_metric,
        holdout_basin_ids=sorted(holdout_set),
        train_basin_ids=sorted(train_basins),
        n_train_rows=ensemble.train_rows,
        n_holdout_rows=len(cases),
        agreement_nse=agreement,
        median_absolute_error=median_abs_error,
        passed=passed,
        agreement_nse_threshold=request.agreement_nse_threshold,
        report_dir=report_dir,
        cases=cases,
    )
    (report_dir / "summary.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def _rows_with_metric(rows: list[SurrogateDatasetRow], target_metric: str) -> list[SurrogateDatasetRow]:
    filtered = [r for r in rows if target_metric in r.metrics]
    return sorted(filtered, key=lambda r: r.content_hash)


def _filter_rows_by_basin(
    rows: list[SurrogateDatasetRow],
    *,
    include_basins: list[str] | None,
    exclude_basins: list[str] | None,
) -> list[SurrogateDatasetRow]:
    out = rows
    if include_basins is not None:
        allow = {b.strip() for b in include_basins if b.strip()}
        out = [r for r in out if r.basin_id in allow]
    if exclude_basins is not None:
        deny = {b.strip() for b in exclude_basins if b.strip()}
        out = [r for r in out if r.basin_id not in deny]
    return out


def _matrix_from_rows(
    rows: list[SurrogateDatasetRow],
    parameter_names: list[str],
    target_metric: str,
) -> tuple[np.ndarray, np.ndarray]:
    x_rows: list[list[float]] = []
    y_vals: list[float] = []
    for row in rows:
        vec: list[float] = []
        for p in parameter_names:
            if p not in row.parameters:
                raise SwatBuilderInputError(
                    "Row missing requested parameter",
                    content_hash=row.content_hash,
                    parameter=p,
                )
            vec.append(float(row.parameters[p]))
        x_rows.append(vec)
        y_vals.append(float(row.metrics[target_metric]))
    return np.asarray(x_rows, dtype=float), np.asarray(y_vals, dtype=float)


def _fit_linear_regression(X: np.ndarray, y: np.ndarray) -> tuple[float, np.ndarray]:
    ones = np.ones((X.shape[0], 1), dtype=float)
    Xd = np.hstack([ones, X])
    beta, _, _, _ = np.linalg.lstsq(Xd, y, rcond=None)
    return float(beta[0]), np.asarray(beta[1:], dtype=float)


def _predict_linear(X: np.ndarray, intercept: float, coef: np.ndarray) -> np.ndarray:
    return intercept + X @ coef


def _rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    err = y_true - y_pred
    return float(np.sqrt(np.mean(np.square(err))))


def _mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    err = np.abs(y_true - y_pred)
    return float(np.mean(err))


def _compute_ensemble_id(
    request: SurrogateTrainingRequest,
    rows: list[SurrogateDatasetRow],
    parameter_names: list[str],
) -> str:
    payload = {
        "target_metric": request.target_metric,
        "basin_id": request.basin_id,
        "parameter_names": parameter_names,
        "ensemble_size": request.ensemble_size,
        "holdout_fraction": request.holdout_fraction,
        "seed": request.seed,
        "rows": [r.content_hash for r in rows],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _safe_nse(obs: list[float], sim: list[float]) -> float:
    if len(obs) != len(sim) or not obs:
        return float("nan")
    obs_arr = np.asarray(obs, dtype=float)
    sim_arr = np.asarray(sim, dtype=float)
    obs_mean = float(np.mean(obs_arr))
    ss_res = float(np.sum(np.square(obs_arr - sim_arr)))
    ss_tot = float(np.sum(np.square(obs_arr - obs_mean)))
    if ss_tot == 0.0:
        return float("nan")
    return float(1.0 - (ss_res / ss_tot))


def _write_training_rows_csv(
    path: Path,
    *,
    rows: list[SurrogateDatasetRow],
    parameter_names: list[str],
    target_metric: str,
) -> None:
    fieldnames = [
        "content_hash",
        "basin_id",
        "simulation_start",
        "simulation_end",
        *parameter_names,
        target_metric,
        "n_days",
        "mean_observed",
        "mean_simulated",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            rec: dict[str, str | float | int] = {
                "content_hash": row.content_hash,
                "basin_id": row.basin_id,
                "simulation_start": str(row.simulation_start),
                "simulation_end": str(row.simulation_end),
                target_metric: float(row.metrics[target_metric]),
                "n_days": int(row.n_days),
                "mean_observed": float(row.mean_observed),
                "mean_simulated": float(row.mean_simulated),
            }
            for p in parameter_names:
                rec[p] = float(row.parameters[p])
            writer.writerow(rec)


def _write_holdout_cases_csv(path: Path, *, cases: list[HoldoutEvaluationCase]) -> None:
    fieldnames = [
        "basin_id",
        "content_hash",
        "observed_metric",
        "predicted_metric",
        "prediction_uncertainty",
        "absolute_error",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for c in cases:
            writer.writerow(c.model_dump(mode="json"))
