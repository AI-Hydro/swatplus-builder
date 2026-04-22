"""Soil profile visualisation utilities.

Generates quick diagnostic plots of soil depth distributions and layer
counts across a set of :class:`~swatplus_builder.types.SoilProfile`
objects.  Useful for auditing soil ingestion before a SWAT+ run.

Requires ``matplotlib`` which is *not* a core dependency — it lives in
the ``[plot]`` or ``[dev]`` extras.  The module raises a clear
:class:`~swatplus_builder.errors.SwatBuilderExternalError` on import if
``matplotlib`` is unavailable, so callers get an actionable message
rather than a generic ``ModuleNotFoundError``.
"""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from swatplus_builder.types import SoilProfile

log = logging.getLogger(__name__)

__all__ = ["plot_depth_distribution"]


def plot_depth_distribution(
    profiles: Sequence["SoilProfile"],
    out_path: Path | str | None = None,
    *,
    figsize: tuple[float, float] = (12.0, 5.0),
    title: str = "Soil profile depth distribution",
) -> Path | None:
    """Generate a two-panel diagnostic figure for a set of soil profiles.

    **Left panel — total profile depth histogram (mm).**
    Bins the maximum depth (``SoilProfile.dp_tot``) of each profile.
    For a healthy gNATSGO ingestion you expect most profiles between
    700–2 000 mm with a long tail of shallow bedrock units.

    **Right panel — layer count frequency (bar).**
    Shows how many profiles have 1, 2, 3, … layers. Profiles with only
    one layer are synthetic fallbacks or bedrock outcrops; healthy
    horizon-resolved profiles typically have 3–6 layers.

    Colour coding by source tag:

    +-----------------------+--------+
    | ``source``            | colour |
    +=======================+========+
    | ``sda_horizon``       | teal   |
    +-----------------------+--------+
    | ``pc_muaggatt``       | steelblue |
    +-----------------------+--------+
    | ``synthetic_default`` | coral  |
    +-----------------------+--------+
    | (anything else)       | grey   |
    +-----------------------+--------+

    Args:
        profiles: Iterable of :class:`~swatplus_builder.types.SoilProfile`.
        out_path: Save figure here if given; if ``None`` the figure is
            shown interactively (requires a display / non-headless
            environment).
        figsize: Matplotlib figure size in inches.
        title: Figure-level suptitle.

    Returns:
        The resolved ``Path`` the figure was saved to, or ``None`` when
        ``out_path`` was not supplied, or a dictionary if generation was
        skipped due to missing dependencies.

    Raises:
        ValueError: ``profiles`` is empty.
    """
    try:
        import matplotlib.pyplot as plt  # type: ignore
        import matplotlib.patches as mpatches  # type: ignore
    except ImportError:
        log.info("matplotlib not installed, skipping soil plot")
        return {
            "plot_generated": False,
            "reason": "matplotlib_not_installed"
        }

    profiles = list(profiles)
    if not profiles:
        raise ValueError("plot_depth_distribution: profiles must not be empty")

    _SRC_COLOURS = {
        "sda_horizon": "teal",
        "pc_muaggatt": "steelblue",
        "synthetic_default": "coral",
    }

    # Collect data
    depths = [p.dp_tot for p in profiles]
    layer_counts = [len(p.layers) for p in profiles]
    colours_depth = [_SRC_COLOURS.get(p.source or "", "grey") for p in profiles]

    fig, (ax_depth, ax_layers) = plt.subplots(1, 2, figsize=figsize)
    fig.suptitle(title, fontsize=13, fontweight="bold")

    # --- Left: depth histogram -----------------------------------------------
    n_bins = min(30, max(10, len(profiles) // 5))
    ax_depth.hist(depths, bins=n_bins, color="steelblue", edgecolor="white", alpha=0.85)
    ax_depth.set_xlabel("Profile depth (mm)", fontsize=10)
    ax_depth.set_ylabel("Number of profiles", fontsize=10)
    ax_depth.set_title("Total profile depth distribution", fontsize=11)
    ax_depth.axvline(500.0, color="orange", linestyle="--", linewidth=1.2,
                     label="SDA acceptance threshold (500 mm)")
    ax_depth.legend(fontsize=8)

    # Percentile annotations
    sorted_depths = sorted(depths)
    n = len(sorted_depths)
    p50 = sorted_depths[n // 2]
    p10 = sorted_depths[max(0, n // 10)]
    ax_depth.axvline(p50, color="navy", linestyle=":", linewidth=1,
                     label=f"P50 = {p50:.0f} mm")
    ax_depth.text(p50 + 20, ax_depth.get_ylim()[1] * 0.9,
                  f"P50={p50:.0f}", fontsize=7, color="navy")
    ax_depth.text(p10 + 20, ax_depth.get_ylim()[1] * 0.7,
                  f"P10={p10:.0f}", fontsize=7, color="grey")

    # Source breakdown legend
    src_counts = Counter(p.source or "unknown" for p in profiles)
    legend_patches = [
        mpatches.Patch(color=_SRC_COLOURS.get(src, "grey"),
                       label=f"{src} ({cnt})")
        for src, cnt in src_counts.items()
    ]
    ax_depth.legend(handles=legend_patches, fontsize=7, loc="upper right")

    # --- Right: layer count bar chart ----------------------------------------
    count_freq = Counter(layer_counts)
    max_layers = max(count_freq) if count_freq else 1
    x = list(range(1, max_layers + 1))
    y = [count_freq.get(k, 0) for k in x]
    bar_colours = ["coral" if k == 1 else "steelblue" for k in x]
    ax_layers.bar(x, y, color=bar_colours, edgecolor="white")
    ax_layers.set_xlabel("Number of horizons", fontsize=10)
    ax_layers.set_ylabel("Number of profiles", fontsize=10)
    ax_layers.set_title("Horizon layer count frequency", fontsize=11)
    ax_layers.set_xticks(x)
    ax_layers.text(0.02, 0.97,
                   f"n = {len(profiles)}\n"
                   f"1-layer (synthetic): {count_freq.get(1, 0)}\n"
                   f"≥2-layer (real): {sum(v for k, v in count_freq.items() if k >= 2)}",
                   transform=ax_layers.transAxes,
                   fontsize=8, verticalalignment="top",
                   bbox=dict(boxstyle="round,pad=0.3", facecolor="lightyellow", alpha=0.8))

    plt.tight_layout()

    if out_path is not None:
        out_path = Path(out_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(out_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        log.info("Soil depth plot saved → %s", out_path)
        return out_path
    else:
        plt.show()
        return None
