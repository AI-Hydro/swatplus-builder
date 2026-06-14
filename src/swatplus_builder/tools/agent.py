"""The four agent-facing tools.

Thin orchestrators: call stage modules in the right order and present a clean,
typed surface that is safe to expose via MCP, CLI, or direct Python import.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import DEFAULT_SETTINGS, Settings
from ..types import HRUResult, Outlet, SwatPlusProject, SwatPlusRun, WatershedResult

log = logging.getLogger(__name__)


def build_watershed(
    dem_path: Path | str,
    outlet: Outlet | tuple[float, float],
    *,
    workdir: Path | str | None = None,
    stream_threshold_cells: int = 500,
    snap_dist_m: float = 500.0,
    validate: bool = True,
    usgs_id: str | None = None,
    reference_polygon: Path | str | None = None,
    area_tolerance_pct: float = 10.0,
    settings: Settings = DEFAULT_SETTINGS,
) -> WatershedResult:
    """Agent tool: delineate subbasins + channels + routing from a DEM.

    Args:
        dem_path:               GeoTIFF DEM (any CRS; reprojected internally if geographic).
        outlet:                 ``(lon, lat)`` in WGS84, or an :class:`~swatplus_builder.types.Outlet`.
        workdir:                Output directory. Defaults to ``./swatplus_runs/<project_hash>``.
        stream_threshold_cells: Flow-accumulation threshold for stream extraction.
                                Higher → fewer, coarser subbasins. Default 500.
        snap_dist_m:            Outlet snap radius in metres. Default 500 m.
        validate:               If True (default), run the post-delineation validation step.
        usgs_id:                USGS gauge ID — if provided, fetches the NLDI reference basin
                                for validation (requires network + pynhd).
        reference_polygon:      Path to a reference watershed polygon. Overrides ``usgs_id``.
        area_tolerance_pct:     Pass threshold for area_diff validation. Default ±10 %.
        settings:               Runtime overrides.

    Returns:
        :class:`~swatplus_builder.types.WatershedResult` — paths to all artifacts.
        Validation metrics are logged; the result is attached as ``result.stats["validation_*"]``.
    """
    from ..gis.delineation import delineate as _delineate
    from ..gis.validate import validate_watershed

    # Resolve workdir
    if workdir is None:
        import hashlib, json
        key = json.dumps({"dem": str(dem_path), "outlet": str(outlet)}, sort_keys=True)
        h = hashlib.sha256(key.encode()).hexdigest()[:12]
        workdir = settings.workdir_base / f"run_{h}"

    result = _delineate(
        dem_path=dem_path,
        outlet=outlet,
        workdir=workdir,
        stream_threshold_cells=stream_threshold_cells,
        snap_dist_m=snap_dist_m,
        settings=settings,
    )

    if validate:
        vr = validate_watershed(
            result,
            usgs_id=usgs_id,
            reference_polygon=reference_polygon,
            area_tolerance_pct=area_tolerance_pct,
        )
        vr.print_report()

        # Attach validation metrics to stats for downstream use
        result.stats["validation_delineated_area_km2"] = vr.delineated_area_km2
        if vr.reference_area_km2 is not None:
            result.stats["validation_reference_area_km2"] = vr.reference_area_km2
        if vr.area_diff_pct is not None:
            result.stats["validation_area_diff_pct"] = vr.area_diff_pct
        if vr.iou_pct is not None:
            result.stats["validation_iou_pct"] = vr.iou_pct
        result.stats["validation_passed"] = float(vr.passed)

        if not vr.passed:
            log.warning(
                "Validation FAILED (area_diff=%.1f %%). "
                "Continuing — inspect the subbasins shapefile before proceeding.",
                vr.area_diff_pct or 0.0,
            )

    return result


def create_hrus(
    watershed: WatershedResult,
    landuse_raster: Path | str,
    soil_raster: Path | str,
    *,
    slope_bands: list[float] | None = None,
    settings: Settings = DEFAULT_SETTINGS,
) -> HRUResult:
    """Agent tool: build HRUs by LU × Soil × Slope overlay.

    See :func:`~swatplus_builder.gis.hru.create_hrus`.
    """
    from ..gis.hru import create_hrus as _create_hrus
    return _create_hrus(
        watershed=watershed,
        landuse_raster=landuse_raster,
        soil_raster=soil_raster,
        slope_bands=slope_bands,
        settings=settings,
    )


def generate_swat_project(
    watershed: WatershedResult,
    hrus: HRUResult,
    weather_dir: Path | str,
    *,
    sim_start: str,
    sim_end: str,
    project_name: str,
    settings: Settings = DEFAULT_SETTINGS,
) -> SwatPlusProject:
    """Agent tool: build a complete SWAT+ project (SQLite + TxtInOut).

    Orchestration (see docs/ARCHITECTURE.md §3 for the diagram):

        1. db.project.create_project_db
        2. db.writer.write_all         (gis_* tables)
        3. editor.api.create_database
        4. editor.api.import_gis
        5. editor.api.import_weather   (wgn + observed)
        6. editor.api.write_files
    """
    raise NotImplementedError("tools.generate_swat_project is not yet implemented.")


def run_swat(
    project: SwatPlusProject,
    *,
    threads: int = 1,
    timeout_s: float | None = None,
    settings: Settings = DEFAULT_SETTINGS,
) -> SwatPlusRun:
    """Agent tool: run the SWAT+ engine on a prepared project.

    Thin wrapper over :func:`swatplus_builder.run.swatplus.run_project` so
    the tool surface stays stable even as the runner primitive evolves.
    """
    from ..run.swatplus import run_project as _run_project
    return _run_project(project, threads=threads, timeout_s=timeout_s, settings=settings)
