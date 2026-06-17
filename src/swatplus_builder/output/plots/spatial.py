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


def read_masked_raster(path: Path | str) -> tuple[np.ma.MaskedArray, tuple[float, float, float, float], float | None]:
    """Read a raster as a masked array, honoring explicit nodata values.

    This is intentionally small and testable because the scientific audit found
    that nodata values such as ``-32768`` were leaking into visual products.
    """

    import rasterio

    p = Path(path)
    with rasterio.open(p) as src:
        data = src.read(1)
        nodata = src.nodata
        mask = np.zeros(data.shape, dtype=bool)
        if nodata is not None:
            mask |= data == nodata
        mask |= ~np.isfinite(data)
        arr = np.ma.array(data, mask=mask)
        bounds = (src.bounds.left, src.bounds.right, src.bounds.bottom, src.bounds.top)
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

    for ax, panel in zip(axes_flat, panels):
        arr, extent, _nodata = read_masked_raster(panel["path"])
        cmap = plt.get_cmap(panel["cmap"]).copy()
        cmap.set_bad("#F7F8FA")
        imshow_kwargs: dict[str, Any] = {}
        if panel["kind"] == "streams":
            imshow_kwargs = {"vmin": 0, "vmax": 1}
        image = ax.imshow(arr, extent=extent, cmap=cmap, interpolation="nearest", **imshow_kwargs)
        ax.set_title(panel["title"], fontsize=11, fontweight="bold")
        ax.set_axis_off()
        if panel.get("colorbar"):
            cbar = fig.colorbar(image, ax=ax, fraction=0.046, pad=0.02)
            cbar.set_label(panel["label"], fontsize=9)
        if panel["kind"] == "dem":
            _overlay_vectors(run_dir, ax)

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
    fig.tight_layout(rect=[0, 0.04, 1, 0.95])
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
            "cmap": "tab20",
            "colorbar": False,
        },
        {
            "kind": "streams",
            "title": "Stream Raster",
            "label": "Stream mask",
            "path": run_dir / "delin" / "rasters" / "streams.tif",
            "cmap": "Blues",
            "colorbar": False,
        },
        {
            "kind": "hru",
            "title": "HRU Map",
            "label": "HRU ID",
            "path": run_dir / "delin" / "hrus" / "hru_map.tif",
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


def _overlay_vectors(run_dir: Path, ax: Any) -> None:
    try:
        import geopandas as gpd
    except Exception:
        return

    channels = run_dir / "delin" / "shapes" / "channels.gpkg"
    outlets = run_dir / "delin" / "shapes" / "outlets.gpkg"
    try:
        if channels.is_file():
            gpd.read_file(channels).plot(ax=ax, color="#0B4F8A", linewidth=0.8)
        if outlets.is_file():
            gpd.read_file(outlets).plot(ax=ax, color="#D62728", markersize=28, marker="*", zorder=5)
    except Exception as exc:
        log.debug("Vector overlay skipped: %s", exc)
