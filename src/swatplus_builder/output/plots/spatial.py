"""Spatial visualization for basin, subbasins, and HRUs."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt

from .style import apply_style
from .utils import build_figure_title, save_publication_figure

log = logging.getLogger(__name__)

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
