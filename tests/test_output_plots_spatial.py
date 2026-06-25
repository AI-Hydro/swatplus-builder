from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest


def _write_raster(path: Path, data: np.ndarray, *, nodata: float = -32768.0) -> None:
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
        crs="EPSG:5070",
        transform=from_origin(0, 3, 1, 1),
        nodata=nodata,
    ) as dst:
        dst.write(data, 1)


def test_read_masked_raster_honors_nodata_value(tmp_path: Path) -> None:
    from swatplus_builder.output.plots.spatial import read_masked_raster

    raster = tmp_path / "dem.tif"
    _write_raster(
        raster,
        np.array(
            [
                [-32768.0, 100.0, 101.0],
                [102.0, 103.0, 104.0],
                [105.0, 106.0, -32768.0],
            ],
            dtype="float32",
        ),
    )

    arr, _extent, nodata = read_masked_raster(raster)

    assert nodata == pytest.approx(-32768.0)
    assert arr.mask[0, 0]
    assert arr.mask[2, 2]
    assert float(arr.min()) == pytest.approx(100.0)


def test_plot_basin_spatial_overview_writes_outputs(tmp_path: Path) -> None:
    from swatplus_builder.output.plots.spatial import plot_basin_spatial_overview

    _write_raster(
        tmp_path / "delin" / "rasters" / "dem_conditioned.tif",
        np.array([[100.0, 101.0], [102.0, -32768.0]], dtype="float32"),
    )

    out = tmp_path / "plots" / "fig_08_basin_spatial_overview"
    files = plot_basin_spatial_overview(tmp_path, out)

    assert files == ["fig_08_basin_spatial_overview.png", "fig_08_basin_spatial_overview.pdf"]
    assert out.with_suffix(".png").is_file()
    assert out.with_suffix(".pdf").is_file()
    assert out.with_suffix(".png").stat().st_size > 1000


def test_plot_basin_spatial_overview_uses_recorded_nlcd_selection(tmp_path: Path) -> None:
    from swatplus_builder.output.plots.spatial import plot_basin_spatial_overview

    _write_raster(
        tmp_path / "delin" / "rasters" / "dem_conditioned.tif",
        np.array([[100.0, 101.0], [102.0, -32768.0]], dtype="float32"),
    )
    selected = tmp_path / "raw" / "nlcd_2011.tif"
    _write_raster(
        selected,
        np.array([[41, 42], [81, 11]], dtype="int16"),
        nodata=127,
    )
    (tmp_path / "raw" / "nlcd_selection.json").write_text(
        json.dumps({"selected_year": 2011, "raster_path": str(selected)}),
        encoding="utf-8",
    )

    out = tmp_path / "plots" / "fig_08_basin_spatial_overview"
    files = plot_basin_spatial_overview(tmp_path, out)

    assert files == ["fig_08_basin_spatial_overview.png", "fig_08_basin_spatial_overview.pdf"]
    assert out.with_suffix(".png").is_file()
    assert out.with_suffix(".pdf").is_file()
