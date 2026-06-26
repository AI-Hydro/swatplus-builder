from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


def test_validation_requires_spatial_overlap_not_only_matching_area(tmp_path: Path) -> None:
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import box

    from swatplus_builder.gis.validate import validate_watershed

    delineated = tmp_path / "delineated.gpkg"
    reference = tmp_path / "reference.gpkg"
    gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[box(0, 0, 1000, 1000)],
        crs="EPSG:5070",
    ).to_file(delineated, driver="GPKG")
    gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[box(500, 0, 1500, 1000)],
        crs="EPSG:5070",
    ).to_file(reference, driver="GPKG")

    result = SimpleNamespace(subbasins_vector=delineated, crs="EPSG:5070")
    validation = validate_watershed(
        result,
        reference_polygon=reference,
        area_tolerance_pct=10.0,
        min_iou_pct=70.0,
    )

    assert validation.area_diff_pct == 0.0
    assert validation.iou_pct == pytest.approx(33.33, abs=0.01)
    assert validation.passed is False
