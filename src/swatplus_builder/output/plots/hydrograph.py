"""Time series hydrograph visualisation — linear + log, peak highlighted."""

from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd
from pathlib import Path
from typing import Optional

from .style import apply_style, COLORS
from .utils import build_figure_title, save_publication_figure


def plot_hydrograph(
    df: pd.DataFrame,
    outpath: Path | str,
    metrics: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> None:
    """Plot observed vs simulated discharge timeseries (linear + log).

    Writes two files:
    * ``{outpath}.png`` / ``{outpath}.pdf`` – linear scale
    * ``{outpath_log}.png`` / ``{outpath_log}.pdf`` – log-scale with peak scatter

    Args:
        df: DataFrame with DatetimeIndex and columns ``obs`` / ``sim``.
        outpath: Base output path (extension ignored; both PNG and PDF saved).
        metrics: Optional ``{"nse": float, "kge": float}`` for title annotation.
        metadata: Optional ``{"basin_name", "usgs_id", "time_range"}`` for title.
    """
    apply_style()
    outpath = Path(outpath)

    title = build_figure_title("Hydrograph", metrics, metadata)

    # ── Linear ────────────────────────────────────────────────────────────────
    fig, ax = plt.subplots()
    ax.plot(df.index, df["obs"], label="Observed", color=COLORS["obs"], alpha=0.85)
    ax.plot(df.index, df["sim"], label="Simulated", color=COLORS["sim"], alpha=0.85)
    ax.set_title(title)
    ax.set_xlabel("Date")
    ax.set_ylabel("Discharge (m³/s)")
    ax.legend()
    fig.tight_layout()
    save_publication_figure(fig, outpath, metadata=metadata)
    plt.close(fig)

    # ── Log scale + peak highlight ─────────────────────────────────────────────
    log_path = outpath.with_name(f"{outpath.stem}_log")
    fig_log, ax_log = plt.subplots()
    ax_log.semilogy(df.index, df["obs"], label="Observed", color=COLORS["obs"], alpha=0.8)
    ax_log.semilogy(df.index, df["sim"], label="Simulated", color=COLORS["sim"], alpha=0.8)
    # Overlay peaks as scatter dots
    ax_log.scatter(df.index, df["sim"], s=4, color=COLORS["sim"], alpha=0.25)
    ax_log.set_title(title + " (log scale)")
    ax_log.set_xlabel("Date")
    ax_log.set_ylabel("Discharge (m³/s, log)")
    ax_log.legend()
    fig_log.tight_layout()
    save_publication_figure(fig_log, log_path, metadata=metadata)
    plt.close(fig_log)
