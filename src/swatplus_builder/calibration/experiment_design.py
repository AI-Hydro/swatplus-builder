"""Explicit shared designs for expensive calibration, without inherited defaults."""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Real
from types import MappingProxyType
from typing import Literal

import numpy as np


@dataclass(frozen=True)
class DesignQuality:
    dimension: int
    npoints: int
    affine_rank: int
    distinct: bool
    gp_ready: bool
    rbf_ready: bool
    normalized: tuple[tuple[float, ...], ...]
    minimum_distance: float | None

    def to_json(self) -> dict:
        """Return JSON-safe primitives; not a serialized JSON string."""
        return {
            "dimension": self.dimension,
            "npoints": self.npoints,
            "affine_rank": self.affine_rank,
            "distinct": self.distinct,
            "gp_ready": self.gp_ready,
            "rbf_ready": self.rbf_ready,
            "normalized": [list(p) for p in self.normalized],
            "minimum_distance": self.minimum_distance,
        }


@dataclass(frozen=True)
class SharedDesign:
    names: tuple[str, ...]
    points: tuple[Mapping[str, float], ...]
    quality: DesignQuality
    seed: int
    generation_attempts: int
    method: str

    def to_json(self) -> dict:
        """Return JSON-safe primitives; mapping proxies need explicit conversion."""
        return {
            "names": list(self.names),
            "points": [dict(p) for p in self.points],
            "quality": self.quality.to_json(),
            "seed": self.seed,
            "generation_attempts": self.generation_attempts,
            "method": self.method,
        }


def _validate_bounds(bounds: Mapping[str, tuple[float, float]]) -> tuple[str, ...]:
    if not bounds:
        raise ValueError("Nonempty governed bounds are required")
    for name, pair in bounds.items():
        if not name or len(pair) != 2:
            raise ValueError("Each named parameter requires two bounds")
        if not all(math.isfinite(v) for v in pair) or pair[0] >= pair[1]:
            raise ValueError("Bounds must be finite and increasing")
    return tuple(sorted(bounds))


def _normalize(
    bounds: Mapping[str, tuple[float, float]],
    names: tuple[str, ...],
    point: Mapping[str, float],
) -> tuple[float, ...]:
    if set(point) != set(names):
        raise ValueError(
            "Every design point must explicitly supply the full parameter vector; no inherited/default filling"
        )
    normalized = []
    for name in names:
        value = point[name]
        lo, hi = bounds[name]
        if (
            isinstance(value, bool)
            or not isinstance(value, Real)
            or not math.isfinite(value)
            or not lo <= value <= hi
        ):
            raise ValueError(f"Design parameter {name} is not a finite in-bounds scalar")
        normalized.append((value - lo) / (hi - lo))
    return tuple(normalized)


def assess_design(
    bounds: Mapping[str, tuple[float, float]],
    points: Sequence[Mapping[str, float]],
    *,
    required_backend: Literal["gp", "rbf"] = "gp",
) -> DesignQuality:
    """Assess rank/readiness without asserting that GP predictions will be accurate.

    The affine rank includes an intercept column. RBF readiness assumes the
    default cubic kernel/linear tail; failed observations must be removed and
    this assessment repeated on the remaining measured finite points.
    """
    if required_backend not in {"gp", "rbf"}:
        raise ValueError("Unknown required backend")
    names = _validate_bounds(bounds)
    normalized = tuple(_normalize(bounds, names, point) for point in points)
    npoints, dimension = len(points), len(names)
    if npoints:
        matrix = np.asarray(normalized, dtype=float)
        affine_rank = int(np.linalg.matrix_rank(np.column_stack((np.ones(npoints), matrix))))
    else:
        matrix = np.empty((0, dimension))
        affine_rank = 0
    distinct = len(set(normalized)) == npoints
    minimum_distance = None
    if npoints >= 2:
        distances = np.linalg.norm(matrix[:, None, :] - matrix[None, :, :], axis=2)
        distances[np.diag_indices(npoints)] = np.inf
        minimum_distance = float(distances.min())
    return DesignQuality(
        dimension=dimension,
        npoints=npoints,
        affine_rank=affine_rank,
        distinct=distinct,
        gp_ready=npoints >= 2 and distinct,
        rbf_ready=npoints >= dimension + 1 and affine_rank == dimension + 1 and distinct,
        normalized=normalized,
        minimum_distance=minimum_distance,
    )


def make_shared_design(
    bounds: Mapping[str, tuple[float, float]],
    n_points: int,
    *,
    seed: int = 42,
    incumbent: Mapping[str, float] | None = None,
    max_attempts: int = 32,
    required_backend: Literal["gp", "rbf"] = "gp",
) -> SharedDesign:
    """Generate a bounded seeded stratified design, optionally with a fixed incumbent.

    With an incumbent, only the remaining points are Latin-stratified; the
    entire design must not be labeled a Latin hypercube. Designs large enough
    to span the affine space are required to do so, even in the GP mode.
    """
    names = _validate_bounds(bounds)
    for name, value in (("n_points", n_points), ("max_attempts", max_attempts), ("seed", seed)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an integer")
    if n_points < 2 or max_attempts < 1:
        raise ValueError("Require at least two points and a positive generation-attempt cap")
    if required_backend not in {"gp", "rbf"}:
        raise ValueError("Unknown required backend")
    if required_backend == "rbf" and n_points < len(names) + 1:
        raise ValueError("Linear-tail RBF requires at least dimension + 1 explicit points")
    incumbent_copy = None
    if incumbent is not None:
        _normalize(bounds, names, incumbent)
        incumbent_copy = {name: float(incumbent[name]) for name in names}
    rng = random.Random(seed)
    remaining = n_points - int(incumbent is not None)
    for attempt in range(1, max_attempts + 1):
        columns = []
        for _ in names:
            strata = list(range(remaining))
            rng.shuffle(strata)
            columns.append([(j + rng.random()) / remaining for j in strata])
        points = [dict(incumbent_copy)] if incumbent_copy is not None else []
        points.extend(
            {
                name: bounds[name][0] + columns[j][i] * (bounds[name][1] - bounds[name][0])
                for j, name in enumerate(names)
            }
            for i in range(remaining)
        )
        quality = assess_design(bounds, points, required_backend=required_backend)
        sufficient_rank = quality.affine_rank == min(n_points, len(names) + 1)
        if quality.distinct and sufficient_rank:
            return SharedDesign(
                names=names,
                points=tuple(MappingProxyType(p) for p in points),
                quality=quality,
                seed=seed,
                generation_attempts=attempt,
                method="latin_remaining_plus_declared_incumbent"
                if incumbent is not None
                else "seeded_latin_design",
            )
    raise ValueError(
        f"No distinct, rank-sufficient design found in {max_attempts} generation attempts"
    )
