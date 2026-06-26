from __future__ import annotations

import importlib.util
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Polygon, box

from swatplus_builder.gis.nldi_fallback import (
    BoundaryProvenance,
    fetch_basin_boundary_cascade,
    fetch_nhd_flowlines,
)


def test_boundary_provenance_model_dump() -> None:
    provenance = BoundaryProvenance(
        usgs_id="01654000",
        source="nldi_authoritative",
        tier=1,
        generated_at="2026-05-13T00:00:00Z",
        notes=["ok"],
        fallback_attempts=[],
    )

    assert provenance.model_dump()["source"] == "nldi_authoritative"
    assert provenance.model_dump()["tier"] == 1


def test_fetch_basin_boundary_cascade_uses_nldi(monkeypatch) -> None:
    basin = gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])],
        crs="EPSG:4326",
    )

    monkeypatch.setattr("swatplus_builder.gis.nldi_fallback._fetch_nldi_boundary", lambda usgs_id: basin)

    result, provenance = fetch_basin_boundary_cascade("01654000")

    assert len(result) == 1
    assert provenance.source == "nldi_authoritative"
    assert provenance.tier == 1
    assert provenance.model_dump()["usgs_id"] == "01654000"


def test_fetch_basin_boundary_cascade_fails_without_silent_fallback(monkeypatch, tmp_path: Path) -> None:
    def fail(usgs_id: str):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("swatplus_builder.gis.nldi_fallback._fetch_nldi_boundary", fail)

    try:
        fetch_basin_boundary_cascade("01654000", dem_path=tmp_path / "dem.tif")
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected boundary acquisition failure")

    assert "basin_boundary_unavailable" in message
    assert "provider unavailable" in message


def test_fetch_nhd_flowlines_saves_gpkg_and_returns_path(monkeypatch, tmp_path: Path) -> None:
    flowlines = gpd.GeoDataFrame(
        {"id": [1, 2]},
        geometry=[Polygon([(0, 0), (1, 0), (1, 1)]), Polygon([(1, 1), (2, 1), (2, 2)])],
        crs="EPSG:4326",
    )
    captured: dict = {}

    class _FakeNLDI:
        def navigate_byid(self, fsource, fid, nav, data_source, distance=9999):
            captured["data_source"] = data_source
            return flowlines

    import pynhd
    monkeypatch.setattr(pynhd, "NLDI", _FakeNLDI)

    out = tmp_path / "nhd_flowlines.gpkg"
    result = fetch_nhd_flowlines("03339000", out)

    assert result == out
    assert out.exists()
    assert captured["data_source"] == "flowlines", f"invalid source name: {captured['data_source']!r}"


def test_fetch_nhd_flowlines_returns_none_when_empty(monkeypatch, tmp_path: Path) -> None:
    empty = gpd.GeoDataFrame({"id": []}, geometry=[], crs="EPSG:4326")

    class _FakeNLDI:
        def navigate_byid(self, *args, **kwargs):
            return empty

    import pynhd
    monkeypatch.setattr(pynhd, "NLDI", _FakeNLDI)

    result = fetch_nhd_flowlines("03339000", tmp_path / "nhd_flowlines.gpkg")
    assert result is None


def test_fetch_nhd_flowlines_returns_none_on_exception(monkeypatch, tmp_path: Path) -> None:
    class _FakeNLDI:
        def navigate_byid(self, *args, **kwargs):
            raise RuntimeError("network unavailable")

    import pynhd
    monkeypatch.setattr(pynhd, "NLDI", _FakeNLDI)

    result = fetch_nhd_flowlines("03339000", tmp_path / "nhd_flowlines.gpkg")
    assert result is None


def test_example_fetch_basin_boundary_uses_cascade_without_stale_nldi_import(monkeypatch, tmp_path: Path) -> None:
    basin = gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])],
        crs="EPSG:4326",
    )
    provenance = BoundaryProvenance(
        usgs_id="01654000",
        source="nldi_authoritative",
        tier=1,
        generated_at="2026-05-13T00:00:00Z",
        notes=["ok"],
        fallback_attempts=[],
    )

    repo_root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "usgs_basin_workflow_under_test",
        repo_root / "examples" / "usgs_basin_workflow.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.setattr(
        "swatplus_builder.gis.nldi_fallback.fetch_basin_boundary_cascade",
        lambda usgs_id, dem_path=None: (basin, provenance),
    )

    result, result_provenance = module.fetch_basin_boundary(
        "01654000",
        tmp_path / "basin.gpkg",
    )

    assert len(result) == 1
    assert result_provenance["source"] == "nldi_authoritative"


def test_mask_dem_to_basin_constrains_valid_dem_domain(tmp_path: Path) -> None:
    from swatplus_builder.examples.usgs_basin_workflow import mask_dem_to_basin

    dem_path = tmp_path / "dem.tif"
    out_path = tmp_path / "dem_masked.tif"
    data = np.arange(16, dtype="float32").reshape(4, 4)
    with rasterio.open(
        dem_path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="float32",
        crs="EPSG:5070",
        transform=from_origin(0, 40, 10, 10),
        nodata=-9999.0,
    ) as dst:
        dst.write(data, 1)

    basin = gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[box(0, 0, 20, 40)],
        crs="EPSG:5070",
    )

    result = mask_dem_to_basin(dem_path, basin, out_path, buffer_m=0.0)

    assert result == out_path
    assert out_path.with_suffix(".source.json").exists()
    with rasterio.open(out_path) as src:
        masked = src.read(1)

    assert np.all(masked[:, :2] != -9999.0)
    assert np.all(masked[:, 2:] == -9999.0)


def test_stage_output_file_hardlinks_large_engine_table(tmp_path: Path) -> None:
    from swatplus_builder.examples.usgs_basin_workflow import _stage_output_file

    src = tmp_path / "TxtInOut" / "channel_sd_day.txt"
    dst = tmp_path / "outputs" / "channel_sd_day.txt"
    src.parent.mkdir()
    src.write_bytes(b"0123456789" * 1024)

    method = _stage_output_file(src, dst, hardlink_above_mb=0.001)

    assert method in {"hardlink", "symlink"}
    assert dst.read_bytes() == src.read_bytes()
    if method == "hardlink":
        assert src.stat().st_ino == dst.stat().st_ino
