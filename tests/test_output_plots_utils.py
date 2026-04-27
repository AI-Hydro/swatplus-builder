from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

from swatplus_builder.output.plots.utils import (
    build_figure_title,
    save_publication_figure,
    soil_quality_flag,
)


def test_soil_quality_flag_for_fallback_mode() -> None:
    meta = {"soil_mode": "fallback", "pct_fallback_soils": 0.25}
    flag = soil_quality_flag(meta)
    assert flag is not None
    assert "SOIL QUALITY: FALLBACK" in flag
    assert "25.0%" in flag


def test_soil_quality_flag_absent_for_high_fidelity() -> None:
    assert soil_quality_flag({"soil_mode": "high_fidelity", "pct_fallback_soils": 0.0}) is None


def test_build_figure_title_includes_quality_flag() -> None:
    title = build_figure_title(
        "Hydrograph",
        {"nse": 0.1, "kge": 0.2},
        {"basin_name": "A", "usgs_id": "1", "soil_mode": "synthetic", "pct_fallback_soils": 1.0},
    )
    assert "Hydrograph" in title
    assert "NSE=0.10, KGE=0.20" in title
    assert "SOIL QUALITY: SYNTHETIC" in title


def test_save_publication_figure_writes_outputs_with_metadata(tmp_path: Path) -> None:
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    out = tmp_path / "fig_test"
    save_publication_figure(
        fig,
        out,
        metadata={"soil_mode": "fallback", "pct_fallback_soils": 0.4},
    )
    plt.close(fig)
    assert out.with_suffix(".png").exists()
    assert out.with_suffix(".pdf").exists()

