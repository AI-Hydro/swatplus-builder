"""Watershed discretization policy helpers.

SWAT/SWAT+ does not define one universal stream-threshold value.  The
threshold is a modeling choice that trades spatial detail against runtime,
calibration stability, and interpretability.  These helpers keep that choice
explicit and reproducible for automated basin builds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DiscretizationPolicy:
    """Practical limits for research-grade automated delineation.

    The defaults intentionally target streamflow modeling, not fine-scale BMP
    siting.  Users can still override them for diagnostic or management-scale
    workflows, but automated research runs should not silently create thousands
    of subbasins.
    """

    stream_threshold_area_pct: float = 2.0
    """Contributing-area threshold as percent of watershed area.

    For a 1000 km2 basin, ``2.0`` means streams are initiated after roughly
    20 km2 of contributing area.  The value is converted to flow-accumulation
    cells using the DEM resolution.
    """

    min_target_subbasins: int = 8
    max_target_subbasins: int = 350
    max_acceptable_subbasins: int = 500
    min_acceptable_avg_subbasin_area_km2: float = 5.0
    min_threshold_cells: int = 100
    max_threshold_cells: int = 250_000


@dataclass(frozen=True)
class ComplexityAssessment:
    """Result of checking a delineated topology against a policy."""

    acceptable: bool
    n_subbasins: int
    n_channels: int
    avg_subbasin_area_km2: float | None
    reasons: tuple[str, ...]


def adaptive_stream_threshold(
    area_km2: float,
    dem_resolution_m: int,
    policy: DiscretizationPolicy | None = None,
) -> int:
    """Choose a stream threshold from percent contributing area.

    Higher threshold values create fewer, coarser subbasins.  Expressing the
    threshold as a basin-area percentage is more portable than hard-coding a
    fixed cell count because the same percent adapts to basin size and DEM
    resolution.
    """
    pol = policy or DiscretizationPolicy()
    if area_km2 <= 0:
        return pol.min_threshold_cells
    cell_area_m2 = float(dem_resolution_m * dem_resolution_m)
    threshold_area_m2 = area_km2 * 1_000_000.0 * max(pol.stream_threshold_area_pct, 0.0) / 100.0
    threshold = int(round(threshold_area_m2 / max(cell_area_m2, 1.0)))
    return max(pol.min_threshold_cells, min(pol.max_threshold_cells, threshold))


def stream_threshold_candidates(
    area_km2: float,
    dem_resolution_m: int,
    *,
    seed_threshold: int | None = None,
    policy: DiscretizationPolicy | None = None,
) -> list[int]:
    """Return ordered stream-threshold candidates for a basin.

    Adaptive and coarser candidates are tried before very fine candidates.  The
    seed threshold is retained for reproducibility, but it is not allowed to
    dominate the order when it would produce excessive discretization.
    """
    pol = policy or DiscretizationPolicy()
    adaptive = adaptive_stream_threshold(area_km2, dem_resolution_m, pol)
    raw = [
        adaptive,
        max(pol.min_threshold_cells, int(round(adaptive * 1.5))),
        adaptive * 2,
        max(pol.min_threshold_cells, adaptive // 2),
        seed_threshold or adaptive,
        max(pol.min_threshold_cells, (seed_threshold or adaptive) // 2),
    ]
    out: list[int] = []
    for val in raw:
        bounded = max(pol.min_threshold_cells, min(pol.max_threshold_cells, int(round(val))))
        if bounded not in out:
            out.append(bounded)
    return out


def assess_topology_complexity(
    stats: dict[str, Any],
    policy: DiscretizationPolicy | None = None,
) -> ComplexityAssessment:
    """Assess whether subbasin density is practical for research calibration."""
    pol = policy or DiscretizationPolicy()
    n_sub = int(float(stats.get("n_subbasins", 0) or 0))
    n_cha = int(float(stats.get("n_channels", 0) or 0))
    area = float(stats.get("total_area_km2", 0.0) or 0.0)
    avg_area = (area / n_sub) if n_sub > 0 and area > 0 else None
    reasons: list[str] = []
    if n_sub <= 0:
        reasons.append("no_subbasins")
    if n_sub > pol.max_acceptable_subbasins:
        reasons.append("too_many_subbasins")
    if avg_area is not None and avg_area < pol.min_acceptable_avg_subbasin_area_km2:
        # Scale threshold with basin size: allow smaller subbasins for smaller basins
        scaled_threshold = max(0.5, area / 200.0)
        if avg_area < scaled_threshold:
            reasons.append("avg_subbasin_area_too_small")
    return ComplexityAssessment(
        acceptable=not reasons,
        n_subbasins=n_sub,
        n_channels=n_cha,
        avg_subbasin_area_km2=avg_area,
        reasons=tuple(reasons),
    )
