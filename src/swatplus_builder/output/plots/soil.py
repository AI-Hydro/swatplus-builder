"""Soil profile provenance bar chart — percentage-normalised."""

from __future__ import annotations

import matplotlib.pyplot as plt
from pathlib import Path
from typing import TypedDict

from .style import apply_style, COLORS
from .utils import save_publication_figure


class SoilReportShape(TypedDict, total=False):
    horizon_profiles: int
    aggregated_profiles: int
    default_profiles: int


def plot_soil_sources(
    soil_report: SoilReportShape,
    outpath: Path | str,
    metadata: dict | None = None,
) -> None:
    """Bar chart of soil data provenance, percentage-normalised.

    Visualises your hybrid soil architecture impact by showing what
    fraction of profiles came from SDA horizon data, Planetary Computer
    muaggatt aggregation, or the synthetic fallback.

    Args:
        soil_report: dict with counts from ``SoilProfilesResult.soil_report``.
        outpath: Base save path (PNG + PDF both written).
        metadata: Optional basin/run info for title.
    """
    apply_style()
    outpath = Path(outpath)

    labels = ["SDA\n(Horizon)", "PC\n(muaggatt)", "Synthetic\n(Default)"]
    values = [
        int(soil_report.get("horizon_profiles", 0)),
        int(soil_report.get("aggregated_profiles", 0)),
        int(soil_report.get("default_profiles", 0)),
    ]
    total = sum(values) or 1  # guard div/0
    pct = [v / total * 100 for v in values]
    bar_colors = [COLORS["soil_sda"], COLORS["soil_pc"], COLORS["soil_default"]]

    title_parts = ["Soil Architecture Provenance"]
    if metadata:
        basin_name = str(metadata.get("basin_name", "")).strip()
        usgs_id = str(metadata.get("usgs_id", "")).strip()
        has_usgs_in_name = usgs_id and (f"({usgs_id})" in basin_name or usgs_id in basin_name)
        if basin_name:
            name = basin_name
            if not has_usgs_in_name and usgs_id:
                name += f" ({usgs_id})"
            title_parts.insert(0, name)
    title = "\n".join(title_parts)

    fig, ax = plt.subplots(figsize=(7, 5))
    bars = ax.bar(labels, pct, color=bar_colors, edgecolor="white", alpha=0.9)

    # Annotate each bar with percentage label
    for bar, p, v in zip(bars, pct, values):
        if p > 0:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.8,
                f"{p:.1f}%\n(n={v})",
                ha="center", va="bottom", fontsize=9, fontweight="bold",
            )

    ax.set_title(title)
    ax.set_ylabel("Profile Share (%)")
    ax.set_ylim(0, 110)
    fig.tight_layout()
    save_publication_figure(fig, outpath, metadata=metadata)
    plt.close(fig)
