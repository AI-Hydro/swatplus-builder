"""Observed vs Simulated 1:1 scatter plot."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from .style import COLORS, apply_style
from .utils import align_timeseries, build_figure_title, save_publication_figure


def plot_scatter(
    obs: pd.Series,
    sim: pd.Series,
    outpath: Path | str,
    metrics: dict | None = None,
    metadata: dict | None = None,
) -> None:
    """Plot Q_obs vs Q_sim with 1:1 reference line.

    Args:
        obs: Observed flow series.
        sim: Simulated flow series.
        outpath: Base save path (PNG + PDF both written).
        metrics: Optional NSE/KGE for title annotation.
        metadata: Optional basin identifiers for title.
    """
    apply_style()
    outpath = Path(outpath)

    df = align_timeseries(obs, sim)
    if df.empty:
        return

    max_val = max(df["obs"].max(), df["sim"].max()) * 1.05

    title = build_figure_title("Simulated vs Observed Scatter", metrics, metadata)

    fig, ax = plt.subplots(figsize=(7, 7))
    ax.scatter(df["obs"], df["sim"], alpha=0.45, color=COLORS["sim"],
               edgecolor="white", s=40)
    ax.plot([0, max_val], [0, max_val], linestyle="--", color="black",
            linewidth=1.5, label="1:1 Perfect Fit")
    ax.set_title(title)
    ax.set_xlabel("Observed Flow (m³/s)")
    ax.set_ylabel("Simulated Flow (m³/s)")
    ax.set_xlim(0, max_val)
    ax.set_ylim(0, max_val)
    ax.set_aspect("equal", adjustable="box")
    ax.legend()
    fig.tight_layout()
    save_publication_figure(fig, outpath, metadata=metadata)
    plt.close(fig)
