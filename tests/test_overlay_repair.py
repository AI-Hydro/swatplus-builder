import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from swatplus_builder.gis.overlay_repair import OverlayRepairReport, repair_overlay_inputs


def _write_raster(path: Path, data: np.ndarray, *, nodata: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype=str(data.dtype),
        crs="EPSG:5070",
        transform=from_origin(0, 40, 10, 10),
        nodata=nodata,
    ) as dst:
        dst.write(data, 1)


def test_overlay_repair_fills_small_categorical_gaps(tmp_path: Path) -> None:
    dem = tmp_path / "dem.tif"
    landuse = tmp_path / "landuse.tif"
    soil = tmp_path / "soil.tif"
    _write_raster(dem, np.ones((4, 4), dtype="int16"), nodata=-9999)
    _write_raster(
        landuse,
        np.array(
            [
                [41, 41, 41, 41],
                [41, 0, 41, 41],
                [82, 82, 82, 82],
                [82, 82, 82, 82],
            ],
            dtype="int16",
        ),
    )
    _write_raster(
        soil,
        np.array(
            [
                [1001, 1001, 1001, 1001],
                [1001, 1001, 1001, 1001],
                [1002, 1002, 0, 1002],
                [1002, 1002, 1002, 1002],
            ],
            dtype="int32",
        ),
    )

    report = repair_overlay_inputs(
        dem,
        landuse,
        soil,
        tmp_path / "reports" / "overlay_repair",
        max_gap_fraction=0.20,
    )

    assert isinstance(report, OverlayRepairReport)
    assert report.repaired is True
    assert report.reason == "nearest_neighbor_categorical_gap_fill"
    assert report.landuse_filled_cells == 1
    assert report.soil_filled_cells == 1
    assert report.landuse_gap_fraction == 1 / 16
    assert report.soil_gap_fraction == 1 / 16
    report_json = tmp_path / "reports" / "overlay_repair" / "overlay_repair_report.json"
    persisted = json.loads(report_json.read_text(encoding="utf-8"))
    assert persisted["reason"] == "nearest_neighbor_categorical_gap_fill"
    assert persisted["landuse_filled_cells"] == 1
    with rasterio.open(report.landuse_output_path) as src:
        filled_lu = src.read(1)
    with rasterio.open(report.soil_output_path) as src:
        filled_soil = src.read(1)
    assert filled_lu[1, 1] == 41
    assert filled_soil[2, 2] in {1001, 1002}


def test_overlay_repair_blocks_large_categorical_gaps(tmp_path: Path) -> None:
    dem = tmp_path / "dem.tif"
    landuse = tmp_path / "landuse.tif"
    soil = tmp_path / "soil.tif"
    _write_raster(dem, np.ones((4, 4), dtype="int16"), nodata=-9999)
    _write_raster(
        landuse,
        np.array(
            [
                [41, 0, 0, 0],
                [0, 0, 0, 0],
                [0, 0, 0, 0],
                [0, 0, 0, 0],
            ],
            dtype="int16",
        ),
    )
    _write_raster(soil, np.full((4, 4), 1001, dtype="int32"))

    report = repair_overlay_inputs(
        dem,
        landuse,
        soil,
        tmp_path / "repair",
        max_gap_fraction=0.20,
    )

    assert report.repaired is False
    assert report.reason == "categorical_overlay_gap_too_large"
    assert report.landuse_output_path.endswith("landuse.tif")
    assert report.soil_output_path is not None
    assert report.landuse_filled_cells == 0
    assert report.landuse_gap_fraction == 15 / 16
    report_json = tmp_path / "repair" / "overlay_repair_report.json"
    persisted = json.loads(report_json.read_text(encoding="utf-8"))
    assert persisted["reason"] == "categorical_overlay_gap_too_large"
    assert persisted["landuse_gap_fraction"] == 15 / 16
    assert not (tmp_path / "repair" / "landuse_overlay_repaired.tif").exists()


def test_overlay_repair_handles_constant_soil_overlay(tmp_path: Path) -> None:
    dem = tmp_path / "dem.tif"
    landuse = tmp_path / "landuse.tif"
    _write_raster(dem, np.ones((2, 2), dtype="int16"), nodata=-9999)
    _write_raster(landuse, np.array([[41, 41], [41, 41]], dtype="int16"))

    report = repair_overlay_inputs(
        dem,
        landuse,
        None,
        tmp_path / "repair",
    )

    assert report.repaired is False
    assert report.reason == "no_overlay_gaps_detected"
    assert report.soil_output_path is None
    assert report.model_dump()["soil_filled_cells"] == 0
    assert Path(report.landuse_output_path).exists()
