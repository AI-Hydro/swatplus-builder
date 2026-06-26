"""Shared utilities for performance metrics and plotting data pre-processing."""

from __future__ import annotations

import pandas as pd


def soil_quality_flag(metadata: dict | None) -> str | None:
    """Return a visible soil-quality flag string for figure annotation.

    Emits a flag for non-ideal soil modes only.
    """
    if not metadata:
        return None
    mode = str(metadata.get("soil_mode", "")).strip().lower()
    if mode not in {"fallback", "synthetic"}:
        return None

    pct = metadata.get("pct_fallback_soils")
    pct_txt = ""
    if isinstance(pct, (int, float)):
        pct_txt = f" ({float(pct) * 100.0:.1f}% fallback)"
    return f"SOIL QUALITY: {mode.upper()}{pct_txt}"

def align_timeseries(obs: pd.Series, sim: pd.Series) -> pd.DataFrame:
    """Strictly align observed and simulated time series.
    
    Drops any non-overlapping indices to prevent phantom errors from NaNs
    during metrics calculation and visualization plotting.
    
    Args:
        obs: Series of observed daily flows with DatetimeIndex.
        sim: Series of simulated daily flows with DatetimeIndex.
        
    Returns:
        DataFrame with strictly aligned 'obs' and 'sim' columns.
    """
    df = pd.concat([obs, sim], axis=1).dropna()
    df.columns = ["obs", "sim"]
    return df

def build_figure_title(base_title: str, metrics: dict | None, metadata: dict | None) -> str:
    """Assemble a standard publication title string.
    
    Args:
        base_title: Name of the plot (e.g. 'Hydrograph').
        metrics: Optional nse, kge.
        metadata: Optional dictionary with basin_name, usgs_id, time_range.
    """
    parts: list[str] = []
    
    # Metadata string
    if metadata:
        meta_str: list[str] = []
        basin_name = str(metadata.get("basin_name", "")).strip()
        usgs_id = str(metadata.get("usgs_id", "")).strip()
        has_usgs_in_name = usgs_id and f"({usgs_id})" in basin_name
        has_usgs_bare = usgs_id and usgs_id in basin_name
        
        if basin_name:
            meta_str.append(basin_name)
        if usgs_id and not (has_usgs_in_name or has_usgs_bare):
            meta_str.append(f"({usgs_id})")
        time_range = metadata.get("time_range")
        if not time_range and metadata.get("start_date") and metadata.get("end_date"):
            time_range = f"{metadata['start_date']} to {metadata['end_date']}"
        if time_range:
            meta_str.append(f"| {time_range}")
        
        if meta_str:
            parts.append(" ".join(meta_str))
            
    # Add the base title
    if parts:
        parts[-1] += f" - {base_title}"
    else:
        parts.append(base_title)
        
    # Metrics
    if metrics and "nse" in metrics and "kge" in metrics:
        parts.append(f"NSE={metrics['nse']:.2f}, KGE={metrics['kge']:.2f}")

    flag = soil_quality_flag(metadata)
    if flag:
        parts.append(flag)

    return "\n".join(parts)


def _annotate_quality_flag(fig, metadata: dict | None) -> None:
    flag = soil_quality_flag(metadata)
    if not flag:
        return
    fig.text(
        0.995,
        0.01,
        flag,
        ha="right",
        va="bottom",
        fontsize=8,
        color="#8B0000",
        bbox={"facecolor": "#fff5f5", "edgecolor": "#8B0000", "boxstyle": "round,pad=0.25"},
    )


def save_publication_figure(fig, base_path: str | object, metadata: dict | None = None) -> None:
    """Save the figure in both standard raster (PNG) and vector (PDF) formats."""
    from pathlib import Path
    p = Path(str(base_path))
    p.parent.mkdir(parents=True, exist_ok=True)

    _annotate_quality_flag(fig, metadata)

    # Save standard high-res PNG
    png_path = p.with_suffix(".png")
    fig.savefig(png_path, dpi=300, bbox_inches="tight")

    # Save vectorized PDF for manuscript submission
    pdf_path = p.with_suffix(".pdf")
    fig.savefig(pdf_path, bbox_inches="tight")
