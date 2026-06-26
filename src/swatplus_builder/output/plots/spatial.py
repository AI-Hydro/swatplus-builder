"""Spatial visualization for basin, subbasins, HRUs, and source rasters."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np

from ..landuse_fidelity import find_nlcd_raster
from .style import apply_style
from .utils import build_figure_title, save_publication_figure

log = logging.getLogger(__name__)


def read_masked_raster(
    path: Path | str,
    *,
    clip_to_basin: Path | str | None = None,
) -> tuple[np.ma.MaskedArray, tuple[float, float, float, float], float | None]:
    """Read a raster as a masked array, honoring explicit nodata values.

    This is intentionally small and testable because the scientific audit found
    that nodata values such as ``-32768`` were leaking into visual products.
    """

    import rasterio
    from rasterio.transform import array_bounds

    p = Path(path)
    with rasterio.open(p) as src:
        transform = src.transform
        try:
            geoms = _reference_geometries(clip_to_basin, src.crs) if clip_to_basin is not None else None
        except Exception as exc:
            log.debug("Raster crop geometry skipped for %s: %s", p, exc)
            geoms = None
        if geoms:
            try:
                from rasterio.mask import mask as raster_mask

                data, transform = raster_mask(src, geoms, crop=True, filled=False, indexes=1)
                data = np.ma.asarray(data)
            except Exception as exc:
                log.debug("Raster crop failed for %s: %s", p, exc)
                data = src.read(1, masked=True)
                transform = src.transform
        else:
            data = src.read(1, masked=True)
        nodata = src.nodata
        mask = np.ma.getmaskarray(data).copy()
        values = np.asarray(data, dtype=float)
        values[mask] = np.nan
        if nodata is not None:
            mask |= values == nodata
        mask |= ~np.isfinite(values)
        arr = np.ma.array(values, mask=mask)
        west, south, east, north = array_bounds(arr.shape[0], arr.shape[1], transform)
        bounds = (west, east, south, north)
    return arr, bounds, nodata


def plot_basin_spatial_overview(
    run_dir: Path | str,
    outpath: Path | str,
    *,
    metadata: dict | None = None,
) -> list[str]:
    """Generate a multi-panel spatial overview from run artifacts.

    Panels are drawn from artifacts that the canonical workflow already writes:
    conditioned DEM, subbasin raster/vector, channel/outlet vectors, HRU map,
    NLCD land use, and gNATSGO MUKEY soil raster when available.
    """

    run_dir = Path(run_dir)
    outpath = Path(outpath)
    panels = _available_spatial_panels(run_dir)
    if not panels:
        log.info("No spatial rasters found under %s; skipping basin overview.", run_dir)
        return []

    apply_style()
    ncols = 3
    nrows = 2
    fig, axes = plt.subplots(nrows, ncols, figsize=(13.2, 8.0))
    axes_flat = list(axes.ravel())

    for ax in axes_flat:
        ax.set_axis_off()

    reference_vector = _reference_vector_path(run_dir)

    for ax, panel in zip(axes_flat, panels):
        if _plot_vector_panel(run_dir, ax, panel, reference_vector):
            continue
        arr, extent, _nodata = read_masked_raster(panel["path"], clip_to_basin=reference_vector)
        if arr.count() == 0:
            arr, extent, _nodata = read_masked_raster(panel["path"])
        cmap = plt.get_cmap(panel["cmap"]).copy()
        cmap.set_bad("#F7F8FA")
        imshow_kwargs: dict[str, Any] = {}
        if panel["kind"] == "streams":
            imshow_kwargs = {"vmin": 0, "vmax": 1}
        image = ax.imshow(arr, extent=extent, cmap=cmap, interpolation="nearest", **imshow_kwargs)
        ax.set_title(panel["title"], fontsize=11, fontweight="bold")
        _set_panel_extent(ax, extent)
        ax.set_axis_off()
        if panel.get("colorbar"):
            from mpl_toolkits.axes_grid1.inset_locator import inset_axes

            cax = inset_axes(
                ax,
                width="3%",
                height="88%",
                loc="center left",
                bbox_to_anchor=(1.02, 0.0, 1.0, 1.0),
                bbox_transform=ax.transAxes,
                borderpad=0,
            )
            cbar = fig.colorbar(image, cax=cax)
            cbar.set_label(panel["label"], fontsize=9)
        _overlay_reference_boundary(reference_vector, ax, panel["path"])
        if panel["kind"] == "dem":
            _overlay_vectors(run_dir, ax, panel["path"])

    title = build_figure_title("Basin Spatial Overview", None, metadata)
    fig.suptitle(title, y=0.99, fontsize=14, fontweight="bold")
    fig.text(
        0.5,
        0.02,
        "Raster nodata values are masked before plotting; maps are diagnostic overviews, not model-performance evidence.",
        ha="center",
        fontsize=9,
        color="#4A5568",
    )
    fig.subplots_adjust(left=0.035, right=0.975, top=0.90, bottom=0.08, wspace=0.22, hspace=0.34)
    save_publication_figure(fig, outpath, metadata=metadata)
    plt.close(fig)
    return [outpath.with_suffix(".png").name, outpath.with_suffix(".pdf").name]

def plot_spatial_map(
    gdf: Any, 
    column: str,
    outpath: Path | str,
    cmap: str = "viridis",
    title: str | None = None,
    legend_label: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Plot a GeoDataFrame colored by a specific column.
    
    Args:
        gdf: GeoDataFrame to plot.
        column: Column name to use for coloring.
        outpath: Base save path (PNG + PDF).
        cmap: Colormap name.
        title: Optional base title.
        legend_label: Label for the colorbar.
        metadata: Optional basin info for title annotation.
    """
    apply_style()
    outpath = Path(outpath)
    
    if gdf is None or gdf.empty:
        log.warning("GeoDataFrame is empty; skipping spatial plot %s", outpath.name)
        return

    fig, ax = plt.subplots(figsize=(10, 8))
    
    # Plot with legend
    gdf.plot(
        column=column, 
        ax=ax, 
        legend=True, 
        cmap=cmap,
        legend_kwds={'label': legend_label or column, 'orientation': "vertical", 'shrink': 0.8},
        edgecolor='black',
        linewidth=0.5,
        alpha=0.9
    )
    
    # Remove clutter
    ax.set_axis_off()
    
    # Add title with metadata
    fig_title = build_figure_title(title or f"Spatial Map: {column}", None, metadata)
    ax.set_title(fig_title, pad=20)
    
    fig.tight_layout()
    save_publication_figure(fig, outpath, metadata=metadata)
    plt.close(fig)

def plot_basin_summary(
    subbasins_gdf: Any,
    outdir: Path | str,
    metrics: dict | None = None,
    metadata: dict | None = None,
) -> list[str]:
    """Generate a standard set of spatial summary maps for the basin.
    
    Args:
        subbasins_gdf: GeoDataFrame of subbasins.
        outdir: Directory to save plots.
        metrics: Performance metrics (NSE/KGE).
        metadata: Basin info.
    """
    outdir = Path(outdir)
    generated = []
    
    # 1. Figure 08: Subbasin Runoff (if data exists)
    # Note: In a real run, we'd join simulation result to the GDF.
    # For now, we plot the geometry or available attributes.
    if "runoff" in subbasins_gdf.columns:
        p = outdir / "fig_08_subbasin_runoff"
        plot_spatial_map(
            subbasins_gdf, "runoff", p, 
            cmap="YlGnBu", title="Subbasin Runoff Distribution",
            legend_label="Runoff (mm)", metadata=metadata
        )
        generated.extend([p.name + ".png", p.name + ".pdf"])

    # 2. Figure 09: Subbasin Areas/Types
    p = outdir / "fig_09_subbasin_map"
    # Fallback to coloring by ID or Area if specific results aren't joined yet
    col = "area" if "area" in subbasins_gdf.columns else subbasins_gdf.columns[0]
    plot_spatial_map(
        subbasins_gdf, col, p, 
        cmap="tab20", title="Watershed Subbasins",
        legend_label="Subbasin Attribute", metadata=metadata
    )
    generated.extend([p.name + ".png", p.name + ".pdf"])
    
    return generated


def _available_spatial_panels(run_dir: Path) -> list[dict[str, Any]]:
    nlcd_path = find_nlcd_raster(run_dir)
    candidates = [
        {
            "kind": "dem",
            "title": "Conditioned DEM",
            "label": "Elevation (m)",
            "path": run_dir / "delin" / "rasters" / "dem_conditioned.tif",
            "cmap": "terrain",
            "colorbar": True,
        },
        {
            "kind": "subbasins",
            "title": "Subbasins",
            "label": "Subbasin ID",
            "path": run_dir / "delin" / "rasters" / "subbasins.tif",
            "vector_path": run_dir / "delin" / "shapes" / "subbasins.gpkg",
            "cmap": "tab20",
            "colorbar": False,
        },
        {
            "kind": "streams",
            "title": "Stream Network",
            "label": "Stream mask",
            "path": run_dir / "delin" / "rasters" / "streams.tif",
            "vector_path": run_dir / "delin" / "shapes" / "channels.gpkg",
            "cmap": "Blues",
            "colorbar": False,
        },
        {
            "kind": "hru",
            "title": "HRU Map",
            "label": "HRU ID",
            "path": run_dir / "delin" / "hrus" / "hru_map.tif",
            "vector_path": run_dir / "delin" / "hrus" / "hrus.gpkg",
            "cmap": "tab20c",
            "colorbar": False,
        },
        {
            "kind": "landuse",
            "title": "NLCD Land Use",
            "label": "NLCD class",
            "path": nlcd_path or run_dir / "raw" / "nlcd_2021.tif",
            "cmap": "gist_earth",
            "colorbar": False,
        },
        {
            "kind": "soil",
            "title": "gNATSGO Soil MUKEY",
            "label": "MUKEY",
            "path": run_dir / "raw" / "mukey_e5070.tif",
            "cmap": "viridis",
            "colorbar": False,
        },
    ]
    return [panel for panel in candidates if panel["path"].is_file()]


def _plot_vector_panel(
    run_dir: Path,
    ax: Any,
    panel: dict[str, Any],
    reference_vector: Path | None,
) -> bool:
    vector_path = panel.get("vector_path")
    if not vector_path or not Path(vector_path).is_file():
        return False
    try:
        import geopandas as gpd

        frame = gpd.read_file(vector_path)
        if frame.empty or frame.crs is None:
            return False
        target_crs = frame.crs
        ref_frame = None
        if reference_vector is not None and reference_vector.is_file():
            ref_frame = gpd.read_file(reference_vector)
            if not ref_frame.empty and ref_frame.crs is not None:
                ref_frame = ref_frame.to_crs(target_crs)
            else:
                ref_frame = None
        if panel["kind"] == "streams":
            if ref_frame is not None:
                ref_frame.boundary.plot(ax=ax, color="#111827", linewidth=0.75, alpha=0.75, zorder=2)
                minx, miny, maxx, maxy = ref_frame.total_bounds
                _set_panel_extent(ax, (float(minx), float(maxx), float(miny), float(maxy)))
            else:
                minx, miny, maxx, maxy = frame.total_bounds
                _set_panel_extent(ax, (float(minx), float(maxx), float(miny), float(maxy)))
            frame.plot(ax=ax, color="#2563EB", linewidth=0.55, alpha=0.9, zorder=3)
            _overlay_outlets_to_crs(run_dir, ax, target_crs)
            ax.set_title(panel["title"], fontsize=11, fontweight="bold")
            ax.set_axis_off()
            return True
        column = _vector_display_column(frame, panel["kind"])
        frame.plot(
            ax=ax,
            column=column,
            cmap=panel["cmap"],
            edgecolor="#4B5563",
            linewidth=0.35,
            alpha=0.92,
            zorder=2,
        )
        if ref_frame is not None:
            ref_frame.boundary.plot(ax=ax, color="#111827", linewidth=0.75, alpha=0.75, zorder=4)
            minx, miny, maxx, maxy = ref_frame.total_bounds
            _set_panel_extent(ax, (float(minx), float(maxx), float(miny), float(maxy)))
        else:
            minx, miny, maxx, maxy = frame.total_bounds
            _set_panel_extent(ax, (float(minx), float(maxx), float(miny), float(maxy)))
        if panel["kind"] == "subbasins":
            _overlay_vectors_to_crs(run_dir, ax, target_crs)
        ax.set_title(panel["title"], fontsize=11, fontweight="bold")
        ax.set_axis_off()
        return True
    except Exception as exc:
        log.debug("Vector panel failed for %s: %s", vector_path, exc)
        return False


def _vector_display_column(frame: Any, kind: str) -> str | None:
    candidates = {
        "subbasins": ["sub_id", "id", "subbasin"],
        "hru": ["hru", "hru_id", "id", "landuse"],
    }.get(kind, [])
    for column in candidates:
        if column in frame.columns:
            return column
    for column in frame.columns:
        if column != frame.geometry.name:
            return column
    return None


def _reference_vector_path(run_dir: Path) -> Path | None:
    for candidate in [
        run_dir / "raw" / "basin_boundary.gpkg",
        run_dir / "delin" / "shapes" / "subbasins.gpkg",
        run_dir / "delin" / "hrus" / "hrus.gpkg",
    ]:
        if candidate.is_file():
            return candidate
    return None


def _reference_geometries(path: Path | str | None, target_crs: Any) -> list[dict[str, Any]]:
    if path is None:
        return []
    try:
        import geopandas as gpd
        from shapely.geometry import mapping
    except Exception:
        return []
    p = Path(path)
    if not p.is_file() or target_crs is None:
        return []
    frame = gpd.read_file(p)
    if frame.empty or frame.crs is None:
        return []
    frame = frame.to_crs(target_crs)
    geometry = frame.geometry.union_all() if hasattr(frame.geometry, "union_all") else frame.unary_union
    if geometry.is_empty:
        return []
    return [mapping(geometry)]


def _set_panel_extent(ax: Any, extent: tuple[float, float, float, float]) -> None:
    left, right, bottom, top = extent
    width = abs(right - left)
    height = abs(top - bottom)
    if width <= 0 or height <= 0:
        return
    pad_x = width * 0.04
    pad_y = height * 0.04
    ax.set_xlim(left - pad_x, right + pad_x)
    ax.set_ylim(bottom - pad_y, top + pad_y)
    ax.set_aspect("equal", adjustable="box")


def _overlay_reference_boundary(reference_vector: Path | None, ax: Any, raster_path: Path | str) -> None:
    if reference_vector is None:
        return
    try:
        import geopandas as gpd
        import rasterio

        with rasterio.open(raster_path) as src:
            target_crs = src.crs
        if target_crs is None:
            return
        frame = gpd.read_file(reference_vector)
        if frame.empty or frame.crs is None:
            return
        frame.to_crs(target_crs).boundary.plot(ax=ax, color="#111827", linewidth=0.7, alpha=0.75, zorder=4)
    except Exception as exc:
        log.debug("Reference boundary overlay skipped: %s", exc)


def _overlay_vectors(run_dir: Path, ax: Any, raster_path: Path | str) -> None:
    try:
        import geopandas as gpd
        import rasterio
    except Exception:
        return

    channels = run_dir / "delin" / "shapes" / "channels.gpkg"
    outlets = run_dir / "delin" / "shapes" / "outlets.gpkg"
    try:
        with rasterio.open(raster_path) as src:
            target_crs = src.crs
        if target_crs is None:
            return
        if channels.is_file():
            frame = gpd.read_file(channels)
            if frame.crs is not None:
                frame.to_crs(target_crs).plot(ax=ax, color="#0B4F8A", linewidth=0.8, zorder=5)
        if outlets.is_file():
            frame = gpd.read_file(outlets)
            if frame.crs is not None:
                frame.to_crs(target_crs).plot(ax=ax, color="#D62728", markersize=28, marker="*", zorder=6)
    except Exception as exc:
        log.debug("Vector overlay skipped: %s", exc)


def _overlay_vectors_to_crs(run_dir: Path, ax: Any, target_crs: Any) -> None:
    try:
        import geopandas as gpd
    except Exception:
        return
    if target_crs is None:
        return
    channels = run_dir / "delin" / "shapes" / "channels.gpkg"
    outlets = run_dir / "delin" / "shapes" / "outlets.gpkg"
    try:
        if channels.is_file():
            frame = gpd.read_file(channels)
            if frame.crs is not None:
                frame.to_crs(target_crs).plot(ax=ax, color="#0B4F8A", linewidth=0.8, zorder=5)
        if outlets.is_file():
            frame = gpd.read_file(outlets)
            if frame.crs is not None:
                frame.to_crs(target_crs).plot(ax=ax, color="#D62728", markersize=28, marker="*", zorder=6)
    except Exception as exc:
        log.debug("Vector CRS overlay skipped: %s", exc)


def _overlay_outlets_to_crs(run_dir: Path, ax: Any, target_crs: Any) -> None:
    try:
        import geopandas as gpd
    except Exception:
        return
    if target_crs is None:
        return
    outlets = run_dir / "delin" / "shapes" / "outlets.gpkg"
    try:
        if outlets.is_file():
            frame = gpd.read_file(outlets)
            if frame.crs is not None:
                frame.to_crs(target_crs).plot(ax=ax, color="#D62728", markersize=28, marker="*", zorder=6)
    except Exception as exc:
        log.debug("Outlet CRS overlay skipped: %s", exc)
