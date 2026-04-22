"""Terrain analysis: slope, aspect, slope classes, per-subbasin zonal reductions.

Ports ``../../../pipeline/02_get_terrain.py`` into a typed function.

Phase 1 TODO:
    - compute_slope(dem_path) -> slope_degrees_raster
    - classify_slope(slope_raster, bands) -> slope_classes_raster
    - per_subbasin_stats(subbasins_gdf, dem, slope) -> dict[sub_id, {mean_elev, mean_slope, ...}]
"""

from __future__ import annotations

from pathlib import Path

from ..config import DEFAULT_SETTINGS, Settings


def compute_slope(
    dem_path: Path | str,
    output_path: Path | str,
    *,
    in_degrees: bool = True,
    settings: Settings = DEFAULT_SETTINGS,
) -> Path:
    """Compute slope raster from a DEM.

    Args:
        dem_path:    Input DEM GeoTIFF (projected CRS, metres).
        output_path: Where to write the slope raster.
        in_degrees:  True for degrees (default), False for percent rise.
        settings:    Runtime overrides.

    Returns:
        Path to the written slope raster.
    """
    # TODO(phase1): rasterio + numpy Horn method, or whitebox.Slope.
    raise NotImplementedError("terrain.compute_slope is a Phase 1 deliverable.")


def classify_slope(
    slope_raster_path: Path | str,
    output_path: Path | str,
    bands: list[float] | None = None,
    *,
    settings: Settings = DEFAULT_SETTINGS,
) -> Path:
    """Bucket a continuous slope raster into discrete classes.

    Args:
        slope_raster_path: Continuous slope raster (degrees, from :func:`compute_slope`).
        output_path:       Where to write the classified raster (uint8).
        bands:             Break points between classes, e.g. ``[5.0, 15.0]`` for three classes.
                           If None, use ``settings.slope_bands`` (which defaults from
                           QSWATPlus conventions).
        settings:          Runtime overrides.

    Returns:
        Path to the written classified raster.
    """
    # TODO(phase1): numpy digitize.
    raise NotImplementedError("terrain.classify_slope is a Phase 1 deliverable.")
