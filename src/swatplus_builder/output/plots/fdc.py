"""Flow Duration Curve — exceedance probability vs log discharge."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Optional

from .style import apply_style, COLORS
from .utils import build_figure_title, save_publication_figure


def plot_fdc(
    obs: pd.Series,
    sim: pd.Series,
    outpath: Path | str,
    metrics: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> None:
    """Plot Flow Duration Curve (exceedance probability vs log discharge).

    Args:
        obs: Observed daily flow series.
        sim: Simulated daily flow series.
        outpath: Base save path (PNG + PDF both written).
        metrics: Optional NSE/KGE for title annotation.
        metadata: Optional basin identifiers for title.
    """
    apply_style()
    outpath = Path(outpath)

    obs_sorted = sorted(obs.dropna(), reverse=True)
    sim_sorted = sorted(sim.dropna(), reverse=True)
    exceed_obs = np.linspace(0, 100, len(obs_sorted))
    exceed_sim = np.linspace(0, 100, len(sim_sorted))

    title = build_figure_title("Flow Duration Curve", metrics, metadata)

    fig, ax = plt.subplots()
    ax.semilogy(exceed_obs, obs_sorted, label="Observed", color=COLORS["obs"])
    ax.semilogy(exceed_sim, sim_sorted, label="Simulated", color=COLORS["sim"])
    ax.set_title(title)
    ax.set_xlabel("Exceedance Probability (%)")
    ax.set_ylabel("Discharge (m³/s, log scale)")
    ax.legend()
    fig.tight_layout()
    save_publication_figure(fig, outpath, metadata=metadata)
    plt.close(fig)
