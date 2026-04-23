"""Phase 3C.2 calibration adapter skeleton with artifact integration."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

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
from ..output.metadata import try_git_sha
from ..params import get_parameter, validate_value


ObjectiveFn = Callable[[dict[str, float]], dict[str, float]]


@dataclass(frozen=True)
class CalibrationRequest:
    """Input specification for calibration sampling."""

    basin_id: str
    simulation_start: date
    simulation_end: date
    parameters: list[str]
    n_iter: int
    algorithm: str = "dds"
    seed: int = 42
    engine_version: str = "unknown"
    warm_start: bool = True


@dataclass(frozen=True)
class CalibrationIterationResult:
    """Result summary for one sampled parameter vector."""

    iteration: int
    content_hash: str
    cache_hit: bool
    parameters: dict[str, float]
    metrics: dict[str, float]


def run_calibration(
    request: CalibrationRequest,
    *,
    artifacts_root: Path | str,
    objective_fn: ObjectiveFn,
    builder_git_sha: str | None = None,
) -> list[CalibrationIterationResult]:
    """Run calibration sampling and persist each sample as an artifact.

    This is a SpotPy-aligned skeleton: algorithm labels are accepted but
    sampling remains intentionally lightweight in alpha.
    """
    if request.n_iter <= 0:
        raise ValueError("n_iter must be > 0")
    if not request.parameters:
        raise ValueError("At least one parameter is required for calibration.")

    store = LocalArtifactStore(artifacts_root)
    git_sha = builder_git_sha or try_git_sha(Path(__file__).resolve().parents[3]) or "unknown"
    rng = random.Random(request.seed)

    results: list[CalibrationIterationResult] = []
    for i in range(request.n_iter):
        params = _sample_parameters(request.parameters, rng)
        cfg = RunConfig(
            basin_id=request.basin_id,
            simulation_start=request.simulation_start,
            simulation_end=request.simulation_end,
            parameters={name: {"value": val, "scope": get_parameter(name).scope.value} for name, val in params.items()},
            options={"calibration_algorithm": request.algorithm, "iteration": i},
        )
        content_hash = compute_content_hash(
            cfg,
            engine_version=request.engine_version,
            builder_git_sha=git_sha,
        )
        if request.warm_start and store.exists(content_hash):
            rec = store.read(content_hash)
            metrics = rec.metrics.model_dump(exclude_none=True) if rec.metrics is not None else {}
            results.append(
                CalibrationIterationResult(
                    iteration=i,
                    content_hash=content_hash,
                    cache_hit=True,
                    parameters=params,
                    metrics={k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))},
                )
            )
            continue

        metrics = objective_fn(params)
        record = ArtifactRecord(
            content_hash=content_hash,
            config=cfg,
            metadata=ArtifactMetadata(
                run_id=content_hash,
                timestamp_utc=datetime.now(timezone.utc).isoformat(),
                builder_version=__version__,
                git_sha=git_sha,
                notes=[f"calibration:{request.algorithm}", f"iteration:{i}"],
            ),
            metrics=ArtifactMetrics.model_validate(metrics),
            provenance=ArtifactProvenance(proposal_source=f"{request.algorithm}_iteration_{i}"),
        )
        store.write(record)
        results.append(
            CalibrationIterationResult(
                iteration=i,
                content_hash=content_hash,
                cache_hit=False,
                parameters=params,
                metrics=metrics,
            )
        )
    return results


def _sample_parameters(names: list[str], rng: random.Random) -> dict[str, float]:
    out: dict[str, float] = {}
    for name in names:
        p = get_parameter(name)
        lo, hi = p.range
        val = rng.uniform(lo, hi)
        validate_value(name, val)
        out[name] = val
    return out

