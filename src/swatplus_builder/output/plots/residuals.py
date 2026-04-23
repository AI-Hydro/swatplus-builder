"""Residual error diagnostics — bias vs observed flow."""

from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd
from pathlib import Path
from typing import Optional

from .style import apply_style, COLORS
from .utils import align_timeseries, build_figure_title, save_publication_figure


def plot_residuals(
    obs: pd.Series,
    sim: pd.Series,
    outpath: Path | str,
    metrics: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> None:
    """Plot simulation residuals vs observed flows.

    Reveals systematic bias, heteroscedasticity, and underestimation regimes.

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

    residuals = df["sim"] - df["obs"]
    title = build_figure_title("Residual Diagnostics", metrics, metadata)

    fig, ax = plt.subplots()
    ax.scatter(df["obs"], residuals, alpha=0.4, color=COLORS["bias"],
               edgecolor="white", s=35)
    ax.axhline(0, linestyle="--", color="black", linewidth=1.5)
    ax.set_title(title)
    ax.set_xlabel("Observed Flow (m³/s)")
    ax.set_ylabel("Residual: Simulated − Observed (m³/s)")
    fig.tight_layout()
    save_publication_figure(fig, outpath, metadata=metadata)
    plt.close(fig)
