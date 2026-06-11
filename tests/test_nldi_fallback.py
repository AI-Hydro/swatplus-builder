from __future__ import annotations

import importlib.util
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Polygon

from swatplus_builder.gis.nldi_fallback import (
    BoundaryProvenance,
    fetch_basin_boundary_cascade,
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
        "build_real_basin_under_test",
        repo_root / "examples" / "build_real_basin.py",
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
