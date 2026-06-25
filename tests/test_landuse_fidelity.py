from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def _write_nlcd(path: Path, data: np.ndarray) -> None:
    import rasterio
    from rasterio.transform import from_origin

    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype=data.dtype,
        crs="EPSG:4326",
        transform=from_origin(-80, 42, 0.01, 0.01),
        nodata=127,
    ) as dst:
        dst.write(data, 1)


def test_build_landuse_fidelity_block_reports_present_vs_retained_classes(tmp_path: Path) -> None:
    from swatplus_builder.output.landuse_fidelity import build_landuse_fidelity_block

    run = tmp_path / "run"
    _write_nlcd(
        run / "raw" / "nlcd_2021.tif",
        np.array([[41, 42, 82], [81, 127, 11]], dtype="uint8"),
    )
    catalog = {
        "stats": {
            "n_subbasins": 2,
            "n_lsus": 2,
            "n_hrus": 2,
            "dominant_only": True,
        },
        "hrus": [
            {"id": 1, "landuse": "FRSD"},
            {"id": 2, "landuse": "AGRL"},
        ],
    }
    cat_path = run / "delin" / "hrus" / "hru_catalog.json"
    cat_path.parent.mkdir(parents=True, exist_ok=True)
    cat_path.write_text(json.dumps(catalog), encoding="utf-8")

    block = build_landuse_fidelity_block(
        run,
        sim_start="2007-01-01",
        sim_end="2012-12-31",
    )

    assert block["status"] == "evaluated"
    assert block["hru_mode"] == "dominant_only"
    assert block["n_hrus"] == 2
    assert block["n_subbasins"] == 2
    assert block["landuse_nlcd_classes_present"] == [11, 41, 42, 81, 82]
    assert block["landuse_classes_present"] == ["AGRL", "FRSD", "FRSE", "HAY", "WATR"]
    assert block["landuse_classes_retained"] == ["AGRL", "FRSD"]
    assert block["landuse_classes_missing_from_hrus"] == ["FRSE", "HAY", "WATR"]
    assert block["landuse_class_retention_fraction"] == 2 / 5
    assert block["landuse_vintage_year"] == 2021
    assert block["sim_midpoint_year"] == 2010
    assert block["landuse_vintage_mismatch_years"] == 11


def test_build_landuse_fidelity_block_prefers_recorded_nlcd_selection(tmp_path: Path) -> None:
    from swatplus_builder.output.landuse_fidelity import (
        build_landuse_fidelity_block,
        find_nlcd_raster,
    )

    run = tmp_path / "run"
    _write_nlcd(
        run / "raw" / "nlcd_2021.tif",
        np.array([[82, 82], [82, 82]], dtype="uint8"),
    )
    selected = run / "raw" / "nlcd_2011.tif"
    _write_nlcd(
        selected,
        np.array([[41, 42], [81, 11]], dtype="uint8"),
    )
    (run / "raw" / "nlcd_selection.json").write_text(
        json.dumps(
            {
                "selected_year": 2011,
                "sim_midpoint_year": 2010,
                "landuse_vintage_mismatch_years": 1,
                "raster_path": str(selected),
            }
        ),
        encoding="utf-8",
    )
    cat_path = run / "delin" / "hrus" / "hru_catalog.json"
    cat_path.parent.mkdir(parents=True, exist_ok=True)
    cat_path.write_text(
        json.dumps(
            {
                "stats": {"n_subbasins": 1, "n_lsus": 1, "n_hrus": 1, "dominant_only": True},
                "hrus": [{"id": 1, "landuse": "FRSD"}],
            }
        ),
        encoding="utf-8",
    )

    block = build_landuse_fidelity_block(run, sim_start="2007-01-01", sim_end="2012-12-31")

    assert find_nlcd_raster(run) == selected
    assert block["landuse_raster_path"] == str(selected)
    assert block["landuse_nlcd_classes_present"] == [11, 41, 42, 81]
    assert block["landuse_classes_present"] == ["FRSD", "FRSE", "HAY", "WATR"]
    assert block["landuse_vintage_year"] == 2011
    assert block["landuse_vintage_mismatch_years"] == 1
