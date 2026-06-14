"""Monthly and seasonal aggregation plots."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from .style import COLORS, apply_style
from .utils import align_timeseries, build_figure_title, save_publication_figure

_MONTH_LABELS = ["Jan","Feb","Mar","Apr","May","Jun",
                 "Jul","Aug","Sep","Oct","Nov","Dec"]


def plot_seasonal(
    df: pd.DataFrame,
    outpath: Path | str,
    metrics: dict | None = None,
    metadata: dict | None = None,
) -> None:
    """Plot mean monthly discharge — obs vs sim.

    Args:
        df: DataFrame with DatetimeIndex, columns ``obs`` / ``sim``.
        outpath: Base save path (PNG + PDF both written).
        metrics: Optional NSE/KGE for title annotation.
        metadata: Optional basin identifiers for title.
    """
    apply_style()
    outpath = Path(outpath)

    if df.empty or not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("plot_seasonal requires DatetimeIndex DataFrame with obs/sim columns.")

    df = align_timeseries(df["obs"], df["sim"])
    monthly = df.groupby(df.index.month).mean()

    title = build_figure_title("Seasonal Distribution (Monthly Mean)", metrics, metadata)

    fig, ax = plt.subplots()
    ax.plot(monthly.index, monthly["obs"], label="Observed",
            color=COLORS["obs"], marker="o")
    ax.plot(monthly.index, monthly["sim"], label="Simulated",
            color=COLORS["sim"], marker="s")
    ax.set_title(title)
    ax.set_xlabel("Month")
    ax.set_ylabel("Mean Flow (m³/s)")
    ax.set_xticks(range(1, 13))
    ax.set_xticklabels(_MONTH_LABELS)
    ax.legend()
    fig.tight_layout()
    save_publication_figure(fig, outpath, metadata=metadata)
    plt.close(fig)
