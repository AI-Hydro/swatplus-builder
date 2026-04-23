"""Tests for :mod:`swatplus_builder.gis.soil`.

Strategy
--------

The module has three entry points:

1. :func:`extract_unique_mukeys` — pure-local rasterio. We write a
   small synthetic GeoTIFF with a known mukey palette and verify
   both the full-scan path and the polygon-mask path return the
   expected int sets.
2. :func:`fetch_mukey_raster` — Planetary Computer. Mocked identically
   to ``tests/test_soil_gnatsgo.py``: inject fake ``pystac_client`` /
   ``planetary_computer`` modules into ``sys.modules`` and point the
   "mukey asset" href at a local GeoTIFF so rasterio can read it.
3. :func:`extract_mukeys_for_watershed` — agent-facing wrapper; we
   fake both a :class:`WatershedResult` and a ``subbasins.gpkg`` on
   disk, and point at a local mukey raster to keep the test hermetic.

Opt-in integration (real PC) is not added here — the round-trip is
already exercised by ``tests/test_soil_gnatsgo.py::test_real_pc_endpoint``
and the mocked paths below are sufficient to pin the wrapper's
contract.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Polygon, box


# ---------------------------------------------------------------------------
# Synthetic GeoTIFF fixture
# ---------------------------------------------------------------------------


_CRS_UTM = "EPSG:32617"  # UTM 17N, convenient for metre units
_CRS_WGS = "EPSG:4326"


def _write_mukey_raster(
    path: Path,
    array: np.ndarray,
    *,
    nodata: int = 0,
    crs: str = _CRS_UTM,
    origin_xy: tuple[float, float] = (500_000.0, 4_500_000.0),
    pixel_size: float = 30.0,
) -> Path:
    """Write a single-band integer mukey raster at ``path``."""
    transform = from_origin(origin_xy[0], origin_xy[1], pixel_size, pixel_size)
    profile = {
        "driver": "GTiff",
        "height": array.shape[0],
        "width": array.shape[1],
        "count": 1,
        "dtype": str(array.dtype),
        "crs": crs,
        "transform": transform,
        "nodata": nodata,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(array, 1)
    return path


@pytest.fixture
def mukey_raster(tmp_path: Path) -> Path:
    """4x4 mukey raster with four distinct mukeys + a nodata patch.

    Layout (row-major)::

        100 100 200 200
        100 100 200 200
        300 300 400 400
        300 300   0   0     <-- two nodata cells in bottom-right
    """
    arr = np.array(
        [
            [100, 100, 200, 200],
            [100, 100, 200, 200],
            [300, 300, 400, 400],
            [300, 300,   0,   0],
        ],
        dtype=np.int32,
    )
    return _write_mukey_raster(tmp_path / "mukey.tif", arr, nodata=0)


# ---------------------------------------------------------------------------
# extract_unique_mukeys
# ---------------------------------------------------------------------------


class TestExtractUniqueMukeys:
    def test_full_scan_returns_all_mukeys_minus_nodata(self, mukey_raster):
        from swatplus_builder.gis.soil import extract_unique_mukeys

        mks = extract_unique_mukeys(mukey_raster)
        assert mks == {100, 200, 300, 400}

    def test_respects_rasterio_nodata_attr(self, tmp_path):
        """When nodata isn't the default 0, honor what's in the GeoTIFF."""
        from swatplus_builder.gis.soil import extract_unique_mukeys

        arr = np.array([[10, 20], [99, 99]], dtype=np.int32)
        p = _write_mukey_raster(tmp_path / "custom_nd.tif", arr, nodata=99)
        assert extract_unique_mukeys(p) == {10, 20}

    def test_boundary_mask_excludes_outside_pixels(self, mukey_raster):
        """A polygon covering only the top-left 2x2 should yield {100} alone."""
        from swatplus_builder.gis.soil import extract_unique_mukeys

        # Top-left 2x2 cells. Pixel size 30 m; origin (500000, 4500000) with
        # Y decreasing downward → top-left corner (500000, 4500000), bottom-
        # right of the 2x2 is (500060, 4499940).
        poly = box(500_000, 4_499_940, 500_060, 4_500_000)
        mks = extract_unique_mukeys(
            mukey_raster, boundary=poly, boundary_crs=_CRS_UTM
        )
        assert mks == {100}

    def test_boundary_reprojects_wgs84_input(self, mukey_raster):
        """Callers routinely pass WGS84 polygons; we reproject internally."""
        from swatplus_builder.gis.soil import extract_unique_mukeys

        # Reproject the top-left 2x2 bbox into WGS84 and pass THAT in.
        from pyproj import Transformer

        tf = Transformer.from_crs(_CRS_UTM, _CRS_WGS, always_xy=True)
        minx, miny, maxx, maxy = 500_000, 4_499_940, 500_060, 4_500_000
        (mnx, mny), (mxx, mxy) = (
            tf.transform(minx, miny),
            tf.transform(maxx, maxy),
        )
        poly_wgs = box(mnx, mny, mxx, mxy)

        mks = extract_unique_mukeys(
            mukey_raster, boundary=poly_wgs, boundary_crs=_CRS_WGS
        )
        assert mks == {100}

    def test_polygon_fully_outside_raises_pipeline_error(self, mukey_raster):
        """A polygon in the raster's CRS but outside its extent should
        surface as a typed pipeline error, not a raw rasterio crash."""
        from swatplus_builder.errors import SwatBuilderPipelineError
        from swatplus_builder.gis.soil import extract_unique_mukeys

        # UTM 17N, but far from the raster's (500_000, 4_500_000) origin.
        far_in_utm = box(100_000, 100_000, 100_060, 100_060)
        with pytest.raises(SwatBuilderPipelineError) as ei:
            extract_unique_mukeys(
                mukey_raster, boundary=far_in_utm, boundary_crs=_CRS_UTM
            )
        assert "intersect" in str(ei.value).lower()

    def test_custom_nodata_sentinels_override_default(self, tmp_path):
        from swatplus_builder.gis.soil import extract_unique_mukeys

        arr = np.array([[100, 200], [300, 0]], dtype=np.int32)
        # Disable the default (0, 2**31-1) sentinels → 0 now appears.
        p = _write_mukey_raster(tmp_path / "no_sentinels.tif", arr, nodata=-1)
        mks = extract_unique_mukeys(p, nodata_sentinels=())
        assert mks == {0, 100, 200, 300}

    def test_missing_file_raises_input_error(self, tmp_path):
        from swatplus_builder.errors import SwatBuilderInputError
        from swatplus_builder.gis.soil import extract_unique_mukeys

        with pytest.raises(SwatBuilderInputError):
            extract_unique_mukeys(tmp_path / "nope.tif")

    def test_multiband_raster_raises_pipeline_error(self, tmp_path):
        from swatplus_builder.errors import SwatBuilderPipelineError
        from swatplus_builder.gis.soil import extract_unique_mukeys

        p = tmp_path / "multi.tif"
        profile = {
            "driver": "GTiff", "height": 2, "width": 2, "count": 2,
            "dtype": "int32", "crs": _CRS_UTM,
            "transform": from_origin(0, 2, 1, 1), "nodata": 0,
        }
        with rasterio.open(p, "w", **profile) as dst:
            dst.write(np.full((2, 2), 1, dtype=np.int32), 1)
            dst.write(np.full((2, 2), 2, dtype=np.int32), 2)
        with pytest.raises(SwatBuilderPipelineError) as ei:
            extract_unique_mukeys(p)
        assert "single-band" in str(ei.value)

    def test_float_raster_raises_pipeline_error(self, tmp_path):
        from swatplus_builder.errors import SwatBuilderPipelineError
        from swatplus_builder.gis.soil import extract_unique_mukeys

        p = tmp_path / "float.tif"
        arr = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
        _write_mukey_raster(p, arr, nodata=0, crs=_CRS_UTM)
        with pytest.raises(SwatBuilderPipelineError) as ei:
            extract_unique_mukeys(p)
        assert "integer" in str(ei.value)


# ---------------------------------------------------------------------------
# fetch_mukey_raster — mocked Planetary Computer
# ---------------------------------------------------------------------------


class _FakeAsset:
    def __init__(self, href: str):
        self.href = href


class _FakeItem:
    def __init__(self, item_id: str, assets: dict[str, _FakeAsset]):
        self.id = item_id
        self.assets = assets


class _FakeSearch:
    def __init__(self, items: list[_FakeItem]):
        self._items = items

    def items(self):
        return list(self._items)


class _FakeClient:
    _singleton: "_FakeClient"

    def __init__(self, items: list[_FakeItem]):
        self._items = items

    @classmethod
    def open(cls, url, modifier=None):
        cls._last_url = url
        return cls._singleton

    def search(self, collections=None, bbox=None):
        type(self)._last_collections = collections
        type(self)._last_bbox = bbox
        return _FakeSearch(self._items)


def _install_fake_pc(monkeypatch, items: list[_FakeItem]) -> None:
    pystac_mod = types.ModuleType("pystac_client")
    _FakeClient._singleton = _FakeClient(items)
    pystac_mod.Client = _FakeClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pystac_client", pystac_mod)

    pc_mod = types.ModuleType("planetary_computer")
    pc_mod.sign_inplace = lambda x: x  # type: ignore[attr-defined]
    pc_mod.sign = lambda x: x  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "planetary_computer", pc_mod)


class TestFetchMukeyRaster:
    def test_happy_path_clips_and_writes(
        self, tmp_path, monkeypatch, mukey_raster
    ):
        """PC returns a STAC item whose ``mukey`` href is our local
        fixture — we should open it with rasterio, clip to the boundary,
        and write a valid GeoTIFF to ``output_path``.
        """
        from swatplus_builder.gis.soil import extract_unique_mukeys, fetch_mukey_raster

        items = [
            _FakeItem(
                "gnatsgo_state_X",
                {"mukey": _FakeAsset(str(mukey_raster))},
            )
        ]
        _install_fake_pc(monkeypatch, items)

        # Boundary = top-left 2x2 pixels of the fixture (UTM 17N).
        boundary = box(500_000, 4_499_940, 500_060, 4_500_000)
        out = tmp_path / "out" / "mukey_clipped.tif"

        result = fetch_mukey_raster(
            boundary,
            output_path=out,
            boundary_crs=_CRS_UTM,
        )
        assert result == out.resolve()
        assert out.is_file()

        # Re-opening the result should yield ONLY the mukey from the
        # top-left 2x2 quadrant, which is 100.
        assert extract_unique_mukeys(result) == {100}
        # Sanity: we asked PC for bbox-in-WGS84 (collection too).
        assert _FakeClient._last_collections == ["gnatsgo-rasters"]
        bbox = _FakeClient._last_bbox
        assert bbox is not None and len(bbox) == 4
        # Bbox is tiny and near (-84, 40.6) for EPSG:32617 coords given.
        assert -90 < bbox[0] < -75
        assert 38 < bbox[1] < 45

    def test_empty_item_set_raises_external(self, tmp_path, monkeypatch):
        from swatplus_builder.errors import SwatBuilderExternalError
        from swatplus_builder.gis.soil import fetch_mukey_raster

        _install_fake_pc(monkeypatch, [])
        with pytest.raises(SwatBuilderExternalError) as ei:
            fetch_mukey_raster(
                box(500_000, 4_499_940, 500_060, 4_500_000),
                output_path=tmp_path / "x.tif",
                boundary_crs=_CRS_UTM,
            )
        assert "no 'gnatsgo-rasters'" in str(ei.value) or "no" in str(ei.value).lower()

    def test_missing_mukey_asset_raises_pipeline(
        self, tmp_path, monkeypatch
    ):
        from swatplus_builder.errors import SwatBuilderPipelineError
        from swatplus_builder.gis.soil import fetch_mukey_raster

        items = [_FakeItem("bad_item", {"not_mukey": _FakeAsset("/dev/null")})]
        _install_fake_pc(monkeypatch, items)
        with pytest.raises(SwatBuilderPipelineError) as ei:
            fetch_mukey_raster(
                box(500_000, 4_499_940, 500_060, 4_500_000),
                output_path=tmp_path / "x.tif",
                boundary_crs=_CRS_UTM,
            )
        assert "mukey" in str(ei.value).lower()

    def test_missing_extras_raises_external(self, tmp_path, monkeypatch):
        """Simulate ``[soils]`` extras not installed."""
        from swatplus_builder.errors import SwatBuilderExternalError
        from swatplus_builder.gis.soil import fetch_mukey_raster

        # Remove any cached modules then make the import raise.
        for name in ("pystac_client", "planetary_computer"):
            monkeypatch.delitem(sys.modules, name, raising=False)

        # Replace finder so the import will ImportError.
        import builtins
        real_import = builtins.__import__

        def guard(name, *a, **k):
            if name in ("pystac_client", "planetary_computer"):
                raise ImportError(f"No module named {name!r}")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", guard)

        with pytest.raises(SwatBuilderExternalError) as ei:
            fetch_mukey_raster(
                box(500_000, 4_499_940, 500_060, 4_500_000),
                output_path=tmp_path / "x.tif",
                boundary_crs=_CRS_UTM,
            )
        assert "swatplus-builder[soils]" in str(ei.value)

    def test_tries_next_item_when_first_item_does_not_overlap(
        self, tmp_path, monkeypatch, mukey_raster
    ):
        """Regression: STAC can return a nearby non-overlapping tile first."""
        from swatplus_builder.gis.soil import extract_unique_mukeys, fetch_mukey_raster

        # First raster is far away (no overlap), second is the valid fixture.
        far_arr = np.full((4, 4), 999, dtype=np.int32)
        far_raster = _write_mukey_raster(
            tmp_path / "far.tif",
            far_arr,
            nodata=0,
            origin_xy=(900_000.0, 5_000_000.0),
        )

        items = [
            _FakeItem("far_item", {"mukey": _FakeAsset(str(far_raster))}),
            _FakeItem("good_item", {"mukey": _FakeAsset(str(mukey_raster))}),
        ]
        _install_fake_pc(monkeypatch, items)

        boundary = box(500_000, 4_499_940, 500_060, 4_500_000)
        out = tmp_path / "out" / "mukey_retry.tif"
        result = fetch_mukey_raster(boundary, output_path=out, boundary_crs=_CRS_UTM)
        assert result == out.resolve()
        assert extract_unique_mukeys(result) == {100}


# ---------------------------------------------------------------------------
# extract_mukeys_for_watershed
# ---------------------------------------------------------------------------


def _build_fake_watershed(
    tmp_path: Path, *, geometry: Polygon, crs: str = _CRS_UTM
):
    """Minimal :class:`WatershedResult` with a real subbasins GeoPackage."""
    import geopandas as gpd

    from swatplus_builder.types import WatershedResult

    workdir = tmp_path / "ws"
    workdir.mkdir(parents=True, exist_ok=True)
    subs_path = workdir / "subbasins.gpkg"
    gpd.GeoDataFrame(
        {"id": [1]}, geometry=[geometry], crs=crs
    ).to_file(subs_path, driver="GPKG")

    placeholder = workdir / "_.tif"
    placeholder.write_bytes(b"")
    return WatershedResult(
        workdir=workdir,
        crs=crs,
        dem_conditioned=placeholder,
        flow_dir=placeholder,
        flow_acc=placeholder,
        streams_raster=placeholder,
        subbasins_vector=subs_path,
        channels_vector=placeholder,
        outlets_vector=placeholder,
        routing_graph=placeholder,
        stats={},
    )


class TestExtractMukeysForWatershed:
    def test_happy_path_with_local_raster(self, tmp_path, mukey_raster):
        """Caller supplies ``mukey_raster`` → no PC call, pure-local."""
        from swatplus_builder.gis.soil import extract_mukeys_for_watershed

        # Cover the top-left 2x2 → should see {100}.
        geom = box(500_000, 4_499_940, 500_060, 4_500_000)
        ws = _build_fake_watershed(tmp_path, geometry=geom, crs=_CRS_UTM)
        result = extract_mukeys_for_watershed(ws, mukey_raster=mukey_raster)
        assert result == {100}

    def test_fetches_from_pc_when_no_raster(
        self, tmp_path, monkeypatch, mukey_raster
    ):
        from swatplus_builder.gis.soil import extract_mukeys_for_watershed

        items = [
            _FakeItem("gnatsgo_X", {"mukey": _FakeAsset(str(mukey_raster))})
        ]
        _install_fake_pc(monkeypatch, items)

        # Cover the bottom-left 2x2 of the fixture → should see {300}.
        geom = box(500_000, 4_499_880, 500_060, 4_499_940)
        ws = _build_fake_watershed(tmp_path, geometry=geom, crs=_CRS_UTM)

        result = extract_mukeys_for_watershed(ws)
        assert result == {300}
        # Wrapper wrote the fetched raster to the default cache.
        assert (ws.workdir / "rasters" / "mukey.tif").is_file()

    def test_custom_cache_dir(
        self, tmp_path, monkeypatch, mukey_raster
    ):
        from swatplus_builder.gis.soil import extract_mukeys_for_watershed

        items = [
            _FakeItem("gnatsgo_X", {"mukey": _FakeAsset(str(mukey_raster))})
        ]
        _install_fake_pc(monkeypatch, items)
        cache = tmp_path / "custom_cache"

        geom = box(500_000, 4_499_940, 500_060, 4_500_000)
        ws = _build_fake_watershed(tmp_path, geometry=geom, crs=_CRS_UTM)
        extract_mukeys_for_watershed(ws, cache_dir=cache)
        assert (cache / "mukey.tif").is_file()

    def test_empty_subbasins_raises_pipeline(self, tmp_path):
        import geopandas as gpd

        from swatplus_builder.errors import SwatBuilderPipelineError
        from swatplus_builder.gis.soil import extract_mukeys_for_watershed
        from swatplus_builder.types import WatershedResult

        workdir = tmp_path / "ws_empty"
        workdir.mkdir()
        subs = workdir / "subs.gpkg"
        # GeoDataFrame with zero rows — geopandas still writes a valid layer.
        gpd.GeoDataFrame({"id": []}, geometry=[], crs=_CRS_UTM).to_file(
            subs, driver="GPKG"
        )

        placeholder = workdir / "_.tif"
        placeholder.write_bytes(b"")
        ws = WatershedResult(
            workdir=workdir, crs=_CRS_UTM,
            dem_conditioned=placeholder, flow_dir=placeholder,
            flow_acc=placeholder, streams_raster=placeholder,
            subbasins_vector=subs, channels_vector=placeholder,
            outlets_vector=placeholder, routing_graph=placeholder,
            stats={},
        )
        with pytest.raises(SwatBuilderPipelineError):
            extract_mukeys_for_watershed(ws)
