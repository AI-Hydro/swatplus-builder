"""Phase 3D autoresearch loop orchestrator.

Implements a typed, artifact-native experiment loop:

propose -> (surrogate predict or real evaluate) -> persist artifact -> compare -> iterate
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from ..artifacts import (
    ArtifactMetadata,
    ArtifactMetrics,
    ArtifactProvenance,
    ArtifactRecord,
    LocalArtifactStore,
    RunConfig,
    compute_content_hash,
)
from ..params import get_parameter
from ..skills.swatplus_playbook import (
    PlaybookContext,
    PlaybookEvidenceEntry,
    append_playbook_evidence,
    recommend_next_action,
)


class LoopStoppingCriteria(BaseModel):
    """Stopping criteria for autoresearch runs."""

    n_iterations: int = Field(default=20, ge=1, le=10000)
    objective_metric: Literal["nse", "kge", "log_nse", "pbias"] = "nse"
    objective_threshold: float | None = None
    convergence_tolerance: float | None = Field(default=None, gt=0.0)
    convergence_window: int = Field(default=3, ge=2, le=1000)


class LoopRequest(BaseModel):
    """Typed request for one autoresearch loop execution."""

    basin_id: str = Field(..., min_length=1)
    simulation_start: str = Field(..., description="YYYY-MM-DD")
    simulation_end: str = Field(..., description="YYYY-MM-DD")
    artifacts_root: str
    proposal_source: Literal["random", "grid", "history"] = "random"
    proposal_parameters: list[str] = Field(default_factory=lambda: ["CN2", "ESCO", "SURLAG"])
    seed: int = 42
    uncertainty_threshold: float = Field(default=0.15, ge=0.0)
    consult_playbook: bool = True
    playbook_path: str | None = None
    stopping: LoopStoppingCriteria = Field(default_factory=LoopStoppingCriteria)


class SurrogatePrediction(BaseModel):
    """Surrogate output used for uncertainty-gated routing."""

    objective: float
    uncertainty: float = Field(..., ge=0.0)
    metrics: dict[str, float] = Field(default_factory=dict)


class LoopIterationResult(BaseModel):
    """One persisted loop iteration summary."""

    iteration: int
    content_hash: str
    objective_value: float
    proposal_source: str
    parameters: dict[str, float]
    used_surrogate: bool
    uncertainty: float | None = None
    parent_run: str | None = None


class LoopResult(BaseModel):
    """Aggregate loop output."""

    status: Literal["completed", "objective_threshold", "converged"]
    objective_metric: str
    best_content_hash: str
    best_objective: float
    iterations: list[LoopIterationResult]


class RealEvaluator(Protocol):
    """Callable for authoritative model evaluation."""

    def __call__(self, parameters: dict[str, float], iteration: int) -> dict[str, float]:
        """Return metrics dict containing objective metric key."""


class SurrogatePredictor(Protocol):
    """Callable for surrogate inference with uncertainty."""

    def __call__(self, parameters: dict[str, float], iteration: int) -> SurrogatePrediction:
        """Return surrogate prediction payload."""


def run_autoresearch_loop(
    request: LoopRequest,
    *,
    evaluator: RealEvaluator,
    surrogate_predictor: SurrogatePredictor | None = None,
    engine_version: str = "unknown",
    builder_git_sha: str = "unknown",
) -> LoopResult:
    """Run a deterministic artifact-native autoresearch loop.

    Failure modes:
    - Raises ``ValueError`` when parameters/objective metric are invalid.
    - Raises downstream evaluator exceptions unchanged (fail loud).
    - Raises artifact-schema validation errors if payloads are malformed.
    """

    if not request.proposal_parameters:
        raise ValueError("proposal_parameters must contain at least one parameter.")

    params = [p.strip().upper() for p in request.proposal_parameters if p.strip()]
    if not params:
        raise ValueError("proposal_parameters must contain non-empty names.")
    for p in params:
        get_parameter(p)

    store = LocalArtifactStore(request.artifacts_root)
    history = _seed_history(store=store, basin_id=request.basin_id, objective_metric=request.stopping.objective_metric)

    results: list[LoopIterationResult] = []
    prev_hash: str | None = None
    effective_proposal_source = request.proposal_source
    if request.consult_playbook:
        recommendation = recommend_next_action(
            PlaybookContext(
                basin_id=request.basin_id,
                metric_source="evaluate_run",
                proposal_source=request.proposal_source,
                calibration_history_rows=len(history),
                calibration_history_unique_nse=_unique_objective_count(history),
            )
        )
        if request.proposal_source in recommendation.rejected_paths:
            effective_proposal_source = recommendation.fallback_proposal_source or "random"

    for i in range(request.stopping.n_iterations):
        proposal = _propose_parameters(
            strategy=effective_proposal_source,
            parameter_names=params,
            iteration=i,
            max_iterations=request.stopping.n_iterations,
            history=history,
            seed=request.seed,
        )

        used_surrogate = False
        uncertainty: float | None = None
        if surrogate_predictor is not None:
            pred = surrogate_predictor(proposal, i)
            uncertainty = float(pred.uncertainty)
            if pred.uncertainty <= request.uncertainty_threshold:
                metrics = dict(pred.metrics)
                metrics.setdefault(request.stopping.objective_metric, float(pred.objective))
                used_surrogate = True
            else:
                metrics = evaluator(proposal, i)
        else:
            metrics = evaluator(proposal, i)

        obj_key = request.stopping.objective_metric
        if obj_key not in metrics:
            raise ValueError(f"Evaluator did not return objective metric '{obj_key}'.")
        objective = float(metrics[obj_key])

        cfg = RunConfig.model_validate(
            {
                "basin_id": request.basin_id,
                "simulation_start": request.simulation_start,
                "simulation_end": request.simulation_end,
                "parameters": _to_run_parameters(proposal),
                "options": {
                    "proposal_source": effective_proposal_source,
                    "iteration": i,
                    "used_surrogate": used_surrogate,
                },
            }
        )
        content_hash = compute_content_hash(
            cfg,
            engine_version=engine_version,
            builder_git_sha=builder_git_sha,
        )

        metrics_payload = _artifact_metrics_from_metrics(metrics)
        md = ArtifactMetadata(
            run_id=content_hash,
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
        )
        prov = ArtifactProvenance(parent_run=prev_hash, proposal_source=request.proposal_source)
        store.write(
            ArtifactRecord(
                content_hash=content_hash,
                config=cfg,
                metadata=md,
                metrics=metrics_payload,
                provenance=prov,
            )
        )

        row = LoopIterationResult(
            iteration=i,
            content_hash=content_hash,
            objective_value=objective,
            proposal_source=effective_proposal_source,
            parameters=proposal,
            used_surrogate=used_surrogate,
            uncertainty=uncertainty,
            parent_run=prev_hash,
        )
        results.append(row)
        history.append(row)
        prev_hash = content_hash
        if request.playbook_path is not None:
            append_playbook_evidence(
                Path(request.playbook_path),
                [
                    PlaybookEvidenceEntry(
                        title=f"Autoresearch iteration {i} ({request.basin_id})",
                        status="tentative",
                        category="experiment_evidence",
                        source="autoresearch_loop",
                        evidence=(
                            f"objective={request.stopping.objective_metric} "
                            f"value={objective:.6f}; used_surrogate={used_surrogate}"
                        ),
                        consequence="Evidence appended for future rule updates.",
                    )
                ],
            )

        best = _best_result(results, request.stopping.objective_metric)
        if _threshold_met(
            value=best.objective_value,
            threshold=request.stopping.objective_threshold,
            objective_metric=request.stopping.objective_metric,
        ):
            return LoopResult(
                status="objective_threshold",
                objective_metric=request.stopping.objective_metric,
                best_content_hash=best.content_hash,
                best_objective=best.objective_value,
                iterations=results,
            )

        if _is_converged(results, request.stopping):
            best = _best_result(results, request.stopping.objective_metric)
            return LoopResult(
                status="converged",
                objective_metric=request.stopping.objective_metric,
                best_content_hash=best.content_hash,
                best_objective=best.objective_value,
                iterations=results,
            )

    best = _best_result(results, request.stopping.objective_metric)
    return LoopResult(
        status="completed",
        objective_metric=request.stopping.objective_metric,
        best_content_hash=best.content_hash,
        best_objective=best.objective_value,
        iterations=results,
    )


def _to_run_parameters(parameters: dict[str, float]) -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = {}
    for name, value in parameters.items():
        p = get_parameter(name)
        out[name] = {
            "value": float(value),
            "scope": p.scope.value,
        }
    return out


def _artifact_metrics_from_metrics(metrics: dict[str, float]) -> ArtifactMetrics:
    payload = {
        "nse": metrics.get("nse"),
        "kge": metrics.get("kge"),
        "log_nse": metrics.get("log_nse"),
        "pbias": metrics.get("pbias"),
    }
    return ArtifactMetrics.model_validate(payload)


def _seed_history(
    *,
    store: LocalArtifactStore,
    basin_id: str,
    objective_metric: str,
) -> list[LoopIterationResult]:
    seeded: list[LoopIterationResult] = []
    for idx, summary in enumerate(store.query()):
        if summary.basin_id != basin_id or summary.nse is None:
            continue
        seeded.append(
            LoopIterationResult(
                iteration=-(idx + 1),
                content_hash=summary.content_hash,
                objective_value=float(summary.nse if objective_metric == "nse" else summary.nse),
                proposal_source="history",
                parameters={},
                used_surrogate=False,
                parent_run=summary.parent_run,
            )
        )
    return seeded


def _propose_parameters(
    *,
    strategy: str,
    parameter_names: list[str],
    iteration: int,
    max_iterations: int,
    history: list[LoopIterationResult],
    seed: int,
) -> dict[str, float]:
    if strategy == "grid":
        return _grid_proposal(parameter_names, iteration, max_iterations)
    if strategy == "history":
        return _history_proposal(parameter_names, iteration, history, seed)
    return _random_proposal(parameter_names, iteration, seed)


def _grid_proposal(parameter_names: list[str], iteration: int, max_iterations: int) -> dict[str, float]:
    out: dict[str, float] = {}
    alpha = 0.0 if max_iterations <= 1 else iteration / float(max_iterations - 1)
    for name in parameter_names:
        p = get_parameter(name)
        lo, hi = p.range
        out[name] = float(lo + alpha * (hi - lo))
    return out


def _random_proposal(parameter_names: list[str], iteration: int, seed: int) -> dict[str, float]:
    rng = random.Random(seed + iteration * 7919)
    out: dict[str, float] = {}
    for name in parameter_names:
        p = get_parameter(name)
        lo, hi = p.range
        out[name] = float(rng.uniform(lo, hi))
    return out


def _history_proposal(
    parameter_names: list[str],
    iteration: int,
    history: list[LoopIterationResult],
    seed: int,
) -> dict[str, float]:
    if not history:
        return _random_proposal(parameter_names, iteration, seed)

    best = max(history, key=lambda r: r.objective_value)
    if not best.parameters:
        return _random_proposal(parameter_names, iteration, seed)

    rng = random.Random(seed + iteration * 3571)
    out: dict[str, float] = {}
    for name in parameter_names:
        p = get_parameter(name)
        lo, hi = p.range
        base = float(best.parameters.get(name, p.default))
        step = 0.1 * float(hi - lo)
        proposal = base + rng.uniform(-step, step)
        out[name] = float(min(hi, max(lo, proposal)))
    return out


def _best_result(results: list[LoopIterationResult], objective_metric: str) -> LoopIterationResult:
    if objective_metric == "pbias":
        return min(results, key=lambda r: abs(r.objective_value))
    return max(results, key=lambda r: r.objective_value)


def _threshold_met(value: float, threshold: float | None, objective_metric: str) -> bool:
    if threshold is None:
        return False
    if objective_metric == "pbias":
        return abs(value) <= abs(threshold)
    return value >= threshold


def _is_converged(results: list[LoopIterationResult], stopping: LoopStoppingCriteria) -> bool:
    if stopping.convergence_tolerance is None:
        return False
    if len(results) < stopping.convergence_window:
        return False
    window = results[-stopping.convergence_window :]
    vals = [abs(r.objective_value) if stopping.objective_metric == "pbias" else r.objective_value for r in window]
    return (max(vals) - min(vals)) <= stopping.convergence_tolerance


def _unique_objective_count(history: list[LoopIterationResult]) -> int:
    vals = {round(float(item.objective_value), 12) for item in history}
    return len(vals)
