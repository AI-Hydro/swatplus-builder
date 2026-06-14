"""Master wrapper: generate the full manuscript figure suite.

Figure naming follows a journal-friendly convention:
    fig_01_hydrograph.{png,pdf}
    fig_02_hydrograph_log.{png,pdf}
    fig_03_fdc.{png,pdf}
    fig_04_scatter.{png,pdf}
    fig_05_residuals.{png,pdf}
    fig_06_seasonal.{png,pdf}
    fig_07_soil_sources.{png,pdf}

Every plot also writes a matching PDF for manuscript submission.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def generate_all_plots(
    run_dir: str | Path,
    *,
    include_spatial: bool = False,
    include_soil: bool = True,
    metadata: dict | None = None,
) -> dict[str, Any]:
    """Generate the complete manuscript figure suite.

    Args:
        run_dir: Project output directory containing ``outputs/``, ``reports/``.
        include_spatial: Generate spatial (GIS) maps (requires geopandas).
        include_soil: Generate soil provenance bar chart.
        metadata: Optional ``{"basin_name", "usgs_id", "time_range"}`` passed
            through to every figure title for automatic manuscript-level labelling.

    Returns:
        Summary dictionary with ``{"plots_generated", "n_plots", "path", "files"}``.
    """
    run_dir = Path(run_dir)
    plots_dir = run_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    try:
        import pandas as pd
    except ImportError:
        log.warning("pandas not installed; skipping all plots.")
        return {"plots_generated": False, "reason": "pandas_not_installed"}

    files: list[str] = []

    # Merge caller metadata with persisted run metadata, if present.
    merged_metadata = dict(metadata or {})
    persisted_md = run_dir / "metadata.json"
    if persisted_md.exists():
        try:
            with persisted_md.open(encoding="utf-8") as f:
                persisted = json.load(f)
            for k, v in persisted.items():
                merged_metadata.setdefault(k, v)
        except Exception as exc:
            log.debug("Could not read metadata.json for plot annotations: %s", exc)
    if not merged_metadata:
        merged_metadata = None

    # ── Load metrics for title annotation (best-effort) ────────────────────
    metrics: dict | None = None
    metrics_path = run_dir / "reports" / "metrics.json"
    if metrics_path.exists():
        try:
            with metrics_path.open(encoding="utf-8") as f:
                metrics = json.load(f)
        except Exception:
            pass

    # ── fig_07 Soil sources ────────────────────────────────────────────────
    if include_soil:
        soil_json = run_dir / "reports" / "soil_report.json"
        if soil_json.exists():
            try:
                from .soil import plot_soil_sources
                with soil_json.open(encoding="utf-8") as f:
                    soil_report = json.load(f)
                plot_soil_sources(
                    soil_report,
                    plots_dir / "fig_07_soil_sources",
                    metadata=merged_metadata,
                )
                files += ["fig_07_soil_sources.png", "fig_07_soil_sources.pdf"]
            except Exception as exc:
                log.warning("Soil plot failed: %s", exc)

    # ── fig_08+09 Spatial Maps ─────────────────────────────────────────────
    if include_spatial:
        # We look for subbasins.geojson in the expected delin/ folder
        sub_path = run_dir / "delin" / "subbasins.geojson"
        if sub_path.exists():
            try:
                import geopandas as gpd

                from .spatial import plot_basin_summary
                sub_gdf = gpd.read_file(sub_path)
                spatial_files = plot_basin_summary(
                    sub_gdf, plots_dir, metrics=metrics, metadata=merged_metadata
                )
                files += spatial_files
            except Exception as exc:
                log.warning("Spatial plots failed: %s", exc)
        else:
            log.info("subbasins.geojson not found in %s; skipping spatial plots.", sub_path.parent)

    # ── Load aligned timeseries ────────────────────────────────────────────
    ts_path = run_dir / "outputs" / "alignment.csv"
    if not ts_path.exists():
        log.info("alignment.csv not found; skipping hydrological plots.")
        return _summary(plots_dir, files, partial=True)

    try:
        df = pd.read_csv(ts_path, index_col=0, parse_dates=True)
        if df.empty or "obs" not in df.columns or "sim" not in df.columns:
            raise ValueError("alignment.csv must have 'obs' and 'sim' columns.")

        # ── fig_01+02 Hydrograph (linear + log) ───────────────────────────
        from .hydrograph import plot_hydrograph
        plot_hydrograph(df, plots_dir / "fig_01_hydrograph",
                        metrics=metrics, metadata=merged_metadata)
        files += ["fig_01_hydrograph.png", "fig_01_hydrograph.pdf",
                  "fig_02_hydrograph_log.png", "fig_02_hydrograph_log.pdf"]

        # ── fig_03 FDC ────────────────────────────────────────────────────
        from .fdc import plot_fdc
        plot_fdc(df["obs"], df["sim"], plots_dir / "fig_03_fdc",
                 metrics=metrics, metadata=merged_metadata)
        files += ["fig_03_fdc.png", "fig_03_fdc.pdf"]

        # ── fig_04 Scatter ────────────────────────────────────────────────
        from .scatter import plot_scatter
        plot_scatter(df["obs"], df["sim"], plots_dir / "fig_04_scatter",
                     metrics=metrics, metadata=merged_metadata)
        files += ["fig_04_scatter.png", "fig_04_scatter.pdf"]

        # ── fig_05 Residuals ──────────────────────────────────────────────
        from .residuals import plot_residuals
        plot_residuals(df["obs"], df["sim"], plots_dir / "fig_05_residuals",
                       metrics=metrics, metadata=merged_metadata)
        files += ["fig_05_residuals.png", "fig_05_residuals.pdf"]

        # ── fig_06 Seasonal ───────────────────────────────────────────────
        try:
            from .seasonal import plot_seasonal
            plot_seasonal(df, plots_dir / "fig_06_seasonal",
                          metrics=metrics, metadata=merged_metadata)
            files += ["fig_06_seasonal.png", "fig_06_seasonal.pdf"]
        except Exception as exc:
            log.debug("Seasonal plot skipped (insufficient data?): %s", exc)

    except Exception as exc:
        log.warning("Hydrological plotting suite failed: %s", exc)
        return {"plots_generated": False, "reason": str(exc)}

    return _summary(plots_dir, files)


def _summary(plots_dir: Path, files: list[str], partial: bool = False) -> dict[str, Any]:
    actual = list(plots_dir.glob("fig_*.png")) + list(plots_dir.glob("fig_*.pdf"))
    return {
        "plots_generated": True,
        "partial": partial,
        "n_plots": len(actual),
        "path": str(plots_dir),
        "files": files,
    }
