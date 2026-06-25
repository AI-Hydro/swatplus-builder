from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest


def _write_landuse_fixture(run: Path) -> None:
    import rasterio
    from rasterio.transform import from_origin

    raw = run / "raw"
    raw.mkdir(parents=True)
    arr = np.array(
        [
            [41, 41, 41, 82],
            [41, 82, 82, 82],
            [21, 21, 22, 22],
            [90, 90, 95, 95],
        ],
        dtype="int16",
    )
    with rasterio.open(
        raw / "nlcd_2021.tif",
        "w",
        driver="GTiff",
        height=arr.shape[0],
        width=arr.shape[1],
        count=1,
        dtype=arr.dtype,
        crs="EPSG:5070",
        transform=from_origin(0, 4, 1, 1),
        nodata=0,
    ) as dst:
        dst.write(arr, 1)

    catalog = {
        "stats": {"dominant_only": True, "n_hrus": 2, "n_lsus": 2, "n_subbasins": 2},
        "hrus": [
            {"id": 1, "landuse": "FRSD", "arland": 70.0},
            {"id": 2, "landuse": "AGRL", "arland": 30.0},
        ],
    }
    hru_dir = run / "delin" / "hrus"
    hru_dir.mkdir(parents=True)
    (hru_dir / "hru_catalog.json").write_text(json.dumps(catalog), encoding="utf-8")


def test_summarize_landuse_composition_compares_present_and_retained(tmp_path: Path) -> None:
    from swatplus_builder.output.plots.landuse_composition import summarize_landuse_composition

    _write_landuse_fixture(tmp_path)

    values = summarize_landuse_composition(tmp_path, sim_start="2007-01-01", sim_end="2012-12-31")

    assert values.hru_mode == "dominant_only"
    assert values.n_present_classes == 6
    assert values.n_retained_classes == 2
    assert values.retention_fraction == pytest.approx(2 / 6)
    assert values.landuse_vintage_year == 2021
    assert values.sim_midpoint_year == 2010
    assert values.landuse_vintage_mismatch_years == 11
    assert values.present_fraction["FRSD"] == pytest.approx(4 / 16)
    assert values.present_fraction["AGRL"] == pytest.approx(4 / 16)
    assert values.retained_fraction["FRSD"] == pytest.approx(0.7)
    assert values.retained_fraction["AGRL"] == pytest.approx(0.3)
    assert values.retained_fraction.get("WETF", 0.0) == 0.0


def test_plot_landuse_composition_writes_png_and_pdf(tmp_path: Path) -> None:
    from swatplus_builder.output.plots.landuse_composition import plot_landuse_composition

    _write_landuse_fixture(tmp_path)
    out = tmp_path / "plots" / "fig_11_landuse_composition"

    values = plot_landuse_composition(
        tmp_path,
        out,
        sim_start="2007-01-01",
        sim_end="2012-12-31",
    )

    assert values.n_present_classes == 6
    assert out.with_suffix(".png").is_file()
    assert out.with_suffix(".pdf").is_file()
    assert out.with_suffix(".png").stat().st_size > 1000
