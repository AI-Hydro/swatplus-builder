"""Centralized plotting style for publication-ready consistency."""

import matplotlib.pyplot as plt

COLORS = {
    "obs": "#1f77b4",   # blue
    "sim": "#d62728",   # red
    "bias": "#9467bd",  # purple
    "soil_sda": "#17becf", # teal
    "soil_pc": "#2ca02c",  # green
    "soil_default": "#ff7f0e", # orange
}

def apply_style():
    """Apply global matplotlib rcParams for consistent, high-quality figures."""
    plt.rcParams.update({
        "figure.figsize": (10, 5),
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
        "font.size": 11,
        "axes.labelsize": 12,
        "axes.titlesize": 13,
        "legend.fontsize": 10,
        "lines.linewidth": 2,
        "axes.grid": True,
        "grid.alpha": 0.5,
        "grid.linestyle": "--",
        "figure.dpi": 200,
        "savefig.dpi": 300,
        "axes.spines.top": False,
        "axes.spines.right": False,
    })
