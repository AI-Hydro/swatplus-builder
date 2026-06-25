"""Bounded HRU overlay gap repair.

The full-mode builder may ask this module to repair landuse/soil overlay
inputs when too many delineated subbasins have no valid HRU pixels.  Categorical
landuse and mukey rasters must not be interpolated as continuous values, so the
only automated production repair allowed here is a bounded nearest-neighbor
fill of small nodata gaps inside the DEM domain.  Larger coverage failures stay
blocked with a typed reason because extrapolating categorical classes over a
large fraction of a basin would be a scientific overclaim.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import rasterio.warp
from rasterio.enums import Resampling

_LU_NODATA_SENTINELS: frozenset[int] = frozenset({0, 2_147_483_647, 255})
_MUKEY_NODATA_SENTINELS: frozenset[int] = frozenset({0, 2_147_483_647})
_DEFAULT_MAX_GAP_FRACTION = 0.15


@dataclass(frozen=True)
class OverlayRepairReport:
    repaired: bool
    reason: str
    landuse_output_path: str
    soil_output_path: str | None
    landuse_filled_cells: int = 0
    soil_filled_cells: int = 0
    max_gap_fraction: float = _DEFAULT_MAX_GAP_FRACTION
    landuse_gap_fraction: float = 0.0
    soil_gap_fraction: float = 0.0

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


def repair_overlay_inputs(
    dem_raster: str | Path,
    landuse_raster: str | Path,
    soil_raster: str | Path | None,
    outdir: str | Path,
    *,
    max_gap_fraction: float = _DEFAULT_MAX_GAP_FRACTION,
) -> OverlayRepairReport:
    """Repair small categorical nodata gaps by nearest valid category.

    The fill domain is limited to finite DEM cells.  If landuse or soil gaps
    exceed ``max_gap_fraction`` of that domain, no output raster is written and
    the caller should keep the HRU realism gate failed.
    """
    if not 0.0 <= max_gap_fraction <= 1.0:
        raise ValueError(f"max_gap_fraction must be in [0, 1], got {max_gap_fraction!r}")

    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    dem = Path(dem_raster)
    landuse = Path(landuse_raster)
    soil = Path(soil_raster) if soil_raster is not None else None

    with rasterio.open(dem) as dsrc:
        dem_arr = dsrc.read(1, masked=True)
        dem_profile = dsrc.profile.copy()
    fill_domain = ~np.ma.getmaskarray(dem_arr)
    domain_cells = int(fill_domain.sum())
    if domain_cells <= 0:
        return _write_report(
            out,
            OverlayRepairReport(
                repaired=False,
                reason="dem_domain_empty",
                landuse_output_path=str(landuse),
                soil_output_path=str(soil) if soil is not None else None,
                max_gap_fraction=max_gap_fraction,
            ),
        )

    lu_out = out / "landuse_overlay_repaired.tif"
    lu_result = _repair_one_categorical_raster(
        src_path=landuse,
        dem_profile=dem_profile,
        fill_domain=fill_domain,
        nodata_sentinels=_LU_NODATA_SENTINELS,
        output_path=lu_out,
        max_gap_fraction=max_gap_fraction,
    )

    soil_result: _RasterRepairResult | None = None
    if soil is not None:
        soil_out = out / "soil_overlay_repaired.tif"
        soil_result = _repair_one_categorical_raster(
            src_path=soil,
            dem_profile=dem_profile,
            fill_domain=fill_domain,
            nodata_sentinels=_MUKEY_NODATA_SENTINELS,
            output_path=soil_out,
            max_gap_fraction=max_gap_fraction,
        )

    blocked = [r for r in (lu_result, soil_result) if r is not None and not r.allowed]
    if blocked:
        reason = "categorical_overlay_gap_too_large"
        if any(r.reason == "no_valid_source_cells" for r in blocked):
            reason = "categorical_overlay_has_no_valid_source_cells"
        return _write_report(
            out,
            OverlayRepairReport(
                repaired=False,
                reason=reason,
                landuse_output_path=str(landuse),
                soil_output_path=str(soil) if soil is not None else None,
                landuse_filled_cells=0,
                soil_filled_cells=0,
                max_gap_fraction=max_gap_fraction,
                landuse_gap_fraction=lu_result.gap_fraction,
                soil_gap_fraction=soil_result.gap_fraction if soil_result is not None else 0.0,
            ),
        )

    repaired = lu_result.filled_cells > 0 or (
        soil_result is not None and soil_result.filled_cells > 0
    )
    reason = "nearest_neighbor_categorical_gap_fill" if repaired else "no_overlay_gaps_detected"
    return _write_report(
        out,
        OverlayRepairReport(
            repaired=repaired,
            reason=reason,
            landuse_output_path=str(lu_result.output_path),
            soil_output_path=str(soil_result.output_path) if soil_result is not None else None,
            landuse_filled_cells=lu_result.filled_cells,
            soil_filled_cells=soil_result.filled_cells if soil_result is not None else 0,
            max_gap_fraction=max_gap_fraction,
            landuse_gap_fraction=lu_result.gap_fraction,
            soil_gap_fraction=soil_result.gap_fraction if soil_result is not None else 0.0,
        ),
    )


@dataclass(frozen=True)
class _RasterRepairResult:
    output_path: Path
    filled_cells: int
    gap_fraction: float
    allowed: bool
    reason: str


def _repair_one_categorical_raster(
    *,
    src_path: Path,
    dem_profile: dict[str, Any],
    fill_domain: np.ndarray,
    nodata_sentinels: frozenset[int],
    output_path: Path,
    max_gap_fraction: float,
) -> _RasterRepairResult:
    arr, src_nodata = _align_categorical_to_dem(src_path, dem_profile)
    invalid = fill_domain & _invalid_category_mask(arr, src_nodata, nodata_sentinels)
    valid = fill_domain & ~_invalid_category_mask(arr, src_nodata, nodata_sentinels)
    gap_cells = int(invalid.sum())
    domain_cells = int(fill_domain.sum())
    gap_fraction = gap_cells / domain_cells if domain_cells else 0.0

    if gap_cells == 0:
        _write_categorical_raster(output_path, arr, dem_profile, nodata=src_nodata)
        return _RasterRepairResult(output_path, 0, 0.0, True, "no_overlay_gaps_detected")
    if not valid.any():
        return _RasterRepairResult(src_path, 0, gap_fraction, False, "no_valid_source_cells")
    if gap_fraction > max_gap_fraction:
        return _RasterRepairResult(src_path, 0, gap_fraction, False, "gap_fraction_exceeds_limit")

    filled = _nearest_category_fill(arr, valid, invalid)
    _write_categorical_raster(output_path, filled, dem_profile, nodata=src_nodata)
    return _RasterRepairResult(
        output_path,
        gap_cells,
        gap_fraction,
        True,
        "nearest_neighbor_categorical_gap_fill",
    )


def _align_categorical_to_dem(
    src_path: Path,
    dem_profile: dict[str, Any],
) -> tuple[np.ndarray, int | float | None]:
    dst_shape = (int(dem_profile["height"]), int(dem_profile["width"]))
    with rasterio.open(src_path) as src:
        src_nodata = src.nodata
        dst = np.zeros(dst_shape, dtype=src.dtypes[0])
        if src_nodata is not None:
            dst.fill(src_nodata)
        rasterio.warp.reproject(
            source=rasterio.band(src, 1),
            destination=dst,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dem_profile["transform"],
            dst_crs=dem_profile["crs"],
            resampling=Resampling.nearest,
        )
    return dst, src_nodata


def _invalid_category_mask(
    arr: np.ndarray,
    src_nodata: int | float | None,
    nodata_sentinels: frozenset[int],
) -> np.ndarray:
    if np.issubdtype(arr.dtype, np.floating):
        invalid = ~np.isfinite(arr)
    else:
        invalid = np.zeros(arr.shape, dtype=bool)
    if src_nodata is not None:
        invalid |= arr == src_nodata
    invalid |= np.isin(arr, list(nodata_sentinels))
    return invalid


def _nearest_category_fill(arr: np.ndarray, valid: np.ndarray, invalid: np.ndarray) -> np.ndarray:
    out = arr.copy()
    seen = valid.copy()
    q: deque[tuple[int, int]] = deque((int(r), int(c)) for r, c in zip(*np.where(valid)))
    height, width = arr.shape
    neighbors = (
        (-1, 0),
        (1, 0),
        (0, -1),
        (0, 1),
        (-1, -1),
        (-1, 1),
        (1, -1),
        (1, 1),
    )
    while q:
        r, c = q.popleft()
        value = out[r, c]
        for dr, dc in neighbors:
            nr, nc = r + dr, c + dc
            if nr < 0 or nr >= height or nc < 0 or nc >= width or seen[nr, nc]:
                continue
            if not invalid[nr, nc]:
                continue
            out[nr, nc] = value
            seen[nr, nc] = True
            q.append((nr, nc))
    return out


def _write_categorical_raster(
    path: Path,
    arr: np.ndarray,
    dem_profile: dict[str, Any],
    *,
    nodata: int | float | None,
) -> None:
    profile = dem_profile.copy()
    profile.update(
        driver="GTiff",
        count=1,
        dtype=str(arr.dtype),
        nodata=nodata,
        compress="deflate",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arr, 1)


def _write_report(outdir: Path, report: OverlayRepairReport) -> OverlayRepairReport:
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "overlay_repair_report.json").write_text(
        json.dumps(report.model_dump(), indent=2) + "\n",
        encoding="utf-8",
    )
    return report
