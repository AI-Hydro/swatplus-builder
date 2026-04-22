"""Tests for :mod:`swatplus_builder.gis.hru`.

Strategy
--------

Building a full :class:`WatershedResult` via WhiteboxTools is heavy.
Instead, the tests here synthesize a minimal-but-realistic watershed
on an 8×8 pixel UTM grid:

* Two subbasins, split left/right half of the raster.
* A DEM sloping from upper-left (high) to lower-right (low).
* Landuse / soil / slope rasters with known pixel counts per class
  so dominance expectations are easy to assert.
* A channels GPKG with one ``LineString`` per subbasin carrying
  the attributes :func:`_channel_attrs_by_sub` reads.

Each test then calls :func:`create_hrus` and introspects the
returned :class:`HRUResult`, the catalog JSON, and the typed rows
via :func:`load_lsus_hrus`.
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import Affine, from_origin
from shapely.geometry import LineString, Polygon, box


_CRS_UTM = "EPSG:32617"


# ---------------------------------------------------------------------------
# Synthetic watershed fixture
# ---------------------------------------------------------------------------


PIXEL = 30.0  # metres
ORIGIN = (500_000.0, 4_500_000.0)  # UTM upper-left (x, y)


def _write_raster(
    path: Path,
    arr: np.ndarray,
    *,
    nodata: float | None = 0,
    crs: str = _CRS_UTM,
    origin: tuple[float, float] = ORIGIN,
    pixel: float = PIXEL,
    dtype: str | None = None,
) -> Path:
    out_dtype = dtype or str(arr.dtype)
    transform = from_origin(origin[0], origin[1], pixel, pixel)
    profile = {
        "driver": "GTiff", "height": arr.shape[0], "width": arr.shape[1],
        "count": 1, "dtype": out_dtype, "crs": crs, "transform": transform,
        "nodata": nodata,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arr.astype(out_dtype), 1)
    return path


def _subbasin_polygon(col_start: int, col_stop: int, n_rows: int = 8) -> Polygon:
    """Axis-aligned polygon covering ``rows 0..n_rows``, cols ``col_start..col_stop``."""
    minx = ORIGIN[0] + col_start * PIXEL
    maxx = ORIGIN[0] + col_stop * PIXEL
    maxy = ORIGIN[1]
    miny = ORIGIN[1] - n_rows * PIXEL
    return box(minx, miny, maxx, maxy)


@pytest.fixture
def mini_watershed(tmp_path):
    """Build an 8×8 synthetic watershed and return it + extra rasters.

    Layout (8 rows × 8 cols), subbasin id per pixel::

        1 1 1 1 | 2 2 2 2
        1 1 1 1 | 2 2 2 2
        1 1 1 1 | 2 2 2 2
        1 1 1 1 | 2 2 2 2
        1 1 1 1 | 2 2 2 2
        1 1 1 1 | 2 2 2 2
        1 1 1 1 | 2 2 2 2
        1 1 1 1 | 2 2 2 2

    DEM values decrease left-to-right and top-to-bottom so slopes
    are nonzero everywhere. Landuse: subbasin 1 is code 10 (forest)
    with a 4-pixel strip of code 20 (grassland); subbasin 2 is all
    code 30 (ag). Soil is uniform mukey 12345 everywhere.
    """
    from swatplus_builder.types import WatershedResult

    workdir = tmp_path / "ws"
    (workdir / "rasters").mkdir(parents=True)
    (workdir / "shapes").mkdir()

    # --- DEM: gradient 100 -> 40 over 8x8 ---
    h, w = 8, 8
    rows, cols = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
    dem = (100.0 - 3.5 * rows - 3.5 * cols).astype("float32")
    dem_path = _write_raster(
        workdir / "rasters" / "dem.tif", dem, nodata=-9999.0, dtype="float32"
    )

    # --- Subbasins GPKG: left half = sub 1, right half = sub 2 ---
    sub1 = _subbasin_polygon(0, 4)
    sub2 = _subbasin_polygon(4, 8)
    subs_gdf = gpd.GeoDataFrame(
        {"sub_id": [1, 2]}, geometry=[sub1, sub2], crs=_CRS_UTM
    )
    subs_path = workdir / "shapes" / "subbasins.gpkg"
    subs_gdf.to_file(subs_path, driver="GPKG")

    # --- Channels GPKG: one LineString per subbasin across its centre ---
    cha1 = LineString(
        [(ORIGIN[0] + 2 * PIXEL, ORIGIN[1]),
         (ORIGIN[0] + 2 * PIXEL, ORIGIN[1] - 8 * PIXEL)]
    )
    cha2 = LineString(
        [(ORIGIN[0] + 6 * PIXEL, ORIGIN[1]),
         (ORIGIN[0] + 6 * PIXEL, ORIGIN[1] - 8 * PIXEL)]
    )
    channels_gdf = gpd.GeoDataFrame(
        {
            "sub_id": [1, 2],
            "link_id": [101, 102],
            "length_m": [240.0, 240.0],
            "slope_m_m": [0.01, 0.02],
            "width_m": [2.5, 3.0],
            "depth_m": [0.3, 0.4],
        },
        geometry=[cha1, cha2],
        crs=_CRS_UTM,
    )
    channels_path = workdir / "shapes" / "channels.gpkg"
    channels_gdf.to_file(channels_path, driver="GPKG")

    # --- Landuse raster (integer codes):
    #       sub 1 = code 10 with a 2-col strip of code 20 on the right edge;
    #       sub 2 = code 30 uniformly.
    lu = np.full((h, w), 10, dtype="int32")
    lu[:, 2:4] = 20                # cols 2-3 → code 20 in sub 1 (dominant = 10, 8 vs 16?)
    lu[:, 4:] = 30                 # cols 4-7 → all sub 2
    # Pixel counts per subbasin:
    #   sub 1 (cols 0..3): code 10 in cols 0..1 = 16, code 20 in cols 2..3 = 16 (tie!)
    # Adjust to make dominance unambiguous:
    lu[:, 0:3] = 10                # cols 0..2 code 10 → 24 pixels in sub 1
    lu[:, 3] = 20                  # col 3 code 20 → 8 pixels in sub 1
    lu[:, 4:] = 30                 # sub 2 all code 30
    lu_path = _write_raster(
        workdir / "rasters" / "landuse.tif", lu, nodata=0, dtype="int32"
    )

    # --- Soil (mukey) raster: uniform 12345 everywhere ---
    soil = np.full((h, w), 12345, dtype="int32")
    soil_path = _write_raster(
        workdir / "rasters" / "soil.tif", soil, nodata=0, dtype="int32"
    )

    # --- Placeholder paths for WatershedResult fields we don't exercise ---
    placeholder = workdir / "rasters" / "_.tif"
    placeholder.write_bytes(b"")

    watershed = WatershedResult(
        workdir=workdir,
        crs=_CRS_UTM,
        dem_conditioned=dem_path,
        flow_dir=placeholder,
        flow_acc=placeholder,
        streams_raster=placeholder,
        subbasins_vector=subs_path,
        channels_vector=channels_path,
        outlets_vector=placeholder,
        routing_graph=placeholder,
        stats={},
    )
    return {
        "watershed": watershed,
        "landuse_raster": lu_path,
        "soil_raster": soil_path,
        "dem_path": dem_path,
        "shape": (h, w),
    }


# ---------------------------------------------------------------------------
# Happy path: dominant-HRU mode
# ---------------------------------------------------------------------------


class TestDominantMode:
    def test_single_hru_per_subbasin(self, mini_watershed):
        from swatplus_builder.gis.hru import create_hrus

        result = create_hrus(
            mini_watershed["watershed"],
            mini_watershed["landuse_raster"],
            mini_watershed["soil_raster"],
        )

        assert result.lsus_vector.is_file()
        assert result.hrus_vector.is_file()
        assert result.hru_raster.is_file()
        assert result.catalog_path.is_file()

        # 2 subbasins → 2 LSUs → 2 HRUs in dominant mode.
        assert result.stats["n_lsus"] == 2.0
        assert result.stats["n_hrus"] == 2.0

    def test_rows_are_pydantic_valid_and_ids_unique(self, mini_watershed):
        from swatplus_builder.gis.hru import create_hrus, load_lsus_hrus

        result = create_hrus(
            mini_watershed["watershed"],
            mini_watershed["landuse_raster"],
            mini_watershed["soil_raster"],
        )
        lsus, hrus = load_lsus_hrus(result)

        assert {l.id for l in lsus} == {1, 2}
        assert {l.subbasin for l in lsus} == {1, 2}
        assert [l.category for l in lsus] == [1, 1]
        # HRU ids are globally unique (1-indexed).
        assert sorted(h.id for h in hrus) == [1, 2]

    def test_dominant_landuse_is_selected(self, mini_watershed):
        """Sub 1: 24 px of code 10 vs 8 px of code 20 → dominant = code 10.
        Sub 2: 32 px of code 30 → dominant = code 30."""
        from swatplus_builder.gis.hru import create_hrus, load_lsus_hrus

        lookup = {10: "FRST", 20: "PAST", 30: "AGRR"}
        result = create_hrus(
            mini_watershed["watershed"],
            mini_watershed["landuse_raster"],
            mini_watershed["soil_raster"],
            landuse_lookup=lookup,
        )
        _, hrus = load_lsus_hrus(result)
        by_lsu = {h.lsu: h for h in hrus}
        assert by_lsu[1].landuse == "FRST"
        assert by_lsu[2].landuse == "AGRR"

    def test_soil_name_matches_gnatsgo_convention(self, mini_watershed):
        """HRU.soil must be ``gnatsgo_<mukey>`` so it joins with
        :func:`soil.gnatsgo.fetch_gnatsgo_profiles` output by name."""
        from swatplus_builder.gis.hru import create_hrus, load_lsus_hrus

        _, hrus = load_lsus_hrus(
            create_hrus(
                mini_watershed["watershed"],
                mini_watershed["landuse_raster"],
                mini_watershed["soil_raster"],
            )
        )
        assert all(h.soil == "gnatsgo_12345" for h in hrus)

    def test_areas_sum_to_subbasin_area_within_rounding(self, mini_watershed):
        """LSU area should equal subbasin area (MVP 1-to-1). Each subbasin
        has 32 pixels @ 900 m² → 28_800 m² → 2.88 ha."""
        from swatplus_builder.gis.hru import create_hrus, load_lsus_hrus

        result = create_hrus(
            mini_watershed["watershed"],
            mini_watershed["landuse_raster"],
            mini_watershed["soil_raster"],
        )
        lsus, hrus = load_lsus_hrus(result)
        for l in lsus:
            assert l.area == pytest.approx(2.88, abs=1e-6)
        # arslp == arlsu in dominant mode.
        for h in hrus:
            assert h.arslp == h.arlsu

    def test_channel_attrs_flow_into_lsu(self, mini_watershed):
        from swatplus_builder.gis.hru import create_hrus, load_lsus_hrus

        lsus, _ = load_lsus_hrus(
            create_hrus(
                mini_watershed["watershed"],
                mini_watershed["landuse_raster"],
                mini_watershed["soil_raster"],
            )
        )
        by_id = {l.id: l for l in lsus}
        assert by_id[1].channel == 101
        assert by_id[1].len1 == pytest.approx(240.0)
        assert by_id[1].csl == pytest.approx(0.01 * 100.0)  # slope_m_m → percent
        assert by_id[1].wid1 == pytest.approx(2.5)
        assert by_id[2].dep1 == pytest.approx(0.4)

    def test_hru_raster_labels_pixels_with_hru_id(self, mini_watershed):
        from swatplus_builder.gis.hru import create_hrus, load_lsus_hrus

        result = create_hrus(
            mini_watershed["watershed"],
            mini_watershed["landuse_raster"],
            mini_watershed["soil_raster"],
        )
        _, hrus = load_lsus_hrus(result)
        with rasterio.open(result.hru_raster) as src:
            arr = src.read(1)
        # Every valid pixel should carry an HRU id; the raster's
        # nodata (0) covers pixels outside any HRU.
        unique = set(np.unique(arr).tolist())
        expected = {0} | {h.id for h in hrus}
        assert unique <= expected
        # Both HRU ids must actually appear.
        assert {h.id for h in hrus} <= unique

    def test_lat_lon_in_wgs84_range(self, mini_watershed):
        from swatplus_builder.gis.hru import create_hrus, load_lsus_hrus

        lsus, hrus = load_lsus_hrus(
            create_hrus(
                mini_watershed["watershed"],
                mini_watershed["landuse_raster"],
                mini_watershed["soil_raster"],
            )
        )
        for row in [*lsus, *hrus]:
            assert -90.0 <= row.lat <= 90.0
            assert -180.0 <= row.lon <= 180.0
            # UTM 17N with our origin is in the US Midwest.
            assert 30 < row.lat < 50
            assert -95 < row.lon < -75

    def test_catalog_json_round_trip(self, mini_watershed):
        from swatplus_builder.gis.hru import create_hrus, load_lsus_hrus

        result = create_hrus(
            mini_watershed["watershed"],
            mini_watershed["landuse_raster"],
            mini_watershed["soil_raster"],
        )
        payload = json.loads(result.catalog_path.read_text())
        assert "lsus" in payload and "hrus" in payload and "stats" in payload
        assert payload["stats"]["dominant_only"] is True
        assert payload["stats"]["slope_labels"] == ["0-5", "5+"]

        # And the typed loader matches the JSON row count.
        lsus, hrus = load_lsus_hrus(result)
        assert len(lsus) == len(payload["lsus"])
        assert len(hrus) == len(payload["hrus"])


# ---------------------------------------------------------------------------
# Full-overlay mode
# ---------------------------------------------------------------------------


class TestFullOverlayMode:
    def test_multiple_hrus_per_lsu(self, mini_watershed):
        """With ``dominant_only=False`` subbasin 1 (two landuses) should
        produce two HRUs; subbasin 2 (one landuse) stays at one."""
        from swatplus_builder.gis.hru import create_hrus, load_lsus_hrus

        result = create_hrus(
            mini_watershed["watershed"],
            mini_watershed["landuse_raster"],
            mini_watershed["soil_raster"],
            dominant_only=False,
        )
        lsus, hrus = load_lsus_hrus(result)
        per_lsu = {}
        for h in hrus:
            per_lsu.setdefault(h.lsu, []).append(h)
        assert len(per_lsu[1]) == 2
        assert len(per_lsu[2]) == 1

    def test_min_fraction_filter_drops_minor_hru(self, mini_watershed):
        """LSU 1 has 8/32 = 25% of code 20. ``min_hru_fraction=0.3``
        should drop it, leaving just the dominant one."""
        from swatplus_builder.gis.hru import create_hrus, load_lsus_hrus

        result = create_hrus(
            mini_watershed["watershed"],
            mini_watershed["landuse_raster"],
            mini_watershed["soil_raster"],
            dominant_only=False,
            min_hru_fraction=0.3,
        )
        _, hrus = load_lsus_hrus(result)
        lsu1 = [h for h in hrus if h.lsu == 1]
        assert len(lsu1) == 1
        assert lsu1[0].landuse == "lu_10"  # fallback naming


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestErrors:
    def test_missing_landuse_raster_raises_input_error(self, mini_watershed):
        from swatplus_builder.errors import SwatBuilderInputError
        from swatplus_builder.gis.hru import create_hrus

        with pytest.raises(SwatBuilderInputError):
            create_hrus(
                mini_watershed["watershed"],
                mini_watershed["watershed"].workdir / "does_not_exist.tif",
                mini_watershed["soil_raster"],
            )

    def test_non_monotonic_slope_bands_rejected(self, mini_watershed):
        from swatplus_builder.errors import SwatBuilderInputError
        from swatplus_builder.gis.hru import create_hrus

        with pytest.raises(SwatBuilderInputError):
            create_hrus(
                mini_watershed["watershed"],
                mini_watershed["landuse_raster"],
                mini_watershed["soil_raster"],
                slope_bands=[20.0, 5.0],
            )

    def test_subbasins_without_sub_id_rejected(self, mini_watershed, tmp_path):
        from swatplus_builder.errors import SwatBuilderInputError
        from swatplus_builder.gis.hru import create_hrus

        ws = mini_watershed["watershed"]
        # Rewrite subbasins.gpkg with a bad column name.
        gdf = gpd.read_file(ws.subbasins_vector)
        gdf = gdf.rename(columns={"sub_id": "basin_id"})
        gdf.to_file(ws.subbasins_vector, driver="GPKG")

        with pytest.raises(SwatBuilderInputError) as ei:
            create_hrus(
                ws,
                mini_watershed["landuse_raster"],
                mini_watershed["soil_raster"],
            )
        assert "sub_id" in str(ei.value)

    def test_all_nodata_landuse_raises_pipeline_error(
        self, mini_watershed, tmp_path
    ):
        """If every pixel in the LU raster is the nodata sentinel,
        overlay finds nothing and we surface a pipeline error."""
        from swatplus_builder.errors import SwatBuilderPipelineError
        from swatplus_builder.gis.hru import create_hrus

        all_zero = np.zeros((8, 8), dtype="int32")
        bad_lu = _write_raster(
            tmp_path / "bad_lu.tif", all_zero, nodata=0, dtype="int32"
        )
        with pytest.raises(SwatBuilderPipelineError):
            create_hrus(
                mini_watershed["watershed"],
                bad_lu,
                mini_watershed["soil_raster"],
            )


# ---------------------------------------------------------------------------
# Slope band behavior
# ---------------------------------------------------------------------------


class TestSlopeBands:
    def test_custom_slope_bands_change_labels(self, mini_watershed):
        from swatplus_builder.gis.hru import create_hrus

        result = create_hrus(
            mini_watershed["watershed"],
            mini_watershed["landuse_raster"],
            mini_watershed["soil_raster"],
            slope_bands=[3.0, 10.0, 25.0],
        )
        payload = json.loads(result.catalog_path.read_text())
        assert payload["stats"]["slope_labels"] == ["0-3", "3-10", "10-25", "25+"]

    def test_precomputed_slope_raster_bypasses_dem_gradient(
        self, mini_watershed, tmp_path
    ):
        """A uniform 2% slope raster should put every pixel in the 0-5 band."""
        from swatplus_builder.gis.hru import create_hrus, load_lsus_hrus

        slope_pct = np.full((8, 8), 2.0, dtype="float32")
        slope_path = _write_raster(
            tmp_path / "slope.tif", slope_pct, nodata=-9999.0, dtype="float32"
        )
        result = create_hrus(
            mini_watershed["watershed"],
            mini_watershed["landuse_raster"],
            mini_watershed["soil_raster"],
            slope_raster=slope_path,
        )
        _, hrus = load_lsus_hrus(result)
        assert all(h.slp == "0-5" for h in hrus)


# ---------------------------------------------------------------------------
# Slope-label formatting helper (direct unit test)
# ---------------------------------------------------------------------------


class TestSlopeLabelHelper:
    def test_integer_breakpoints_rendered_as_ints(self):
        from swatplus_builder.gis.hru import _slope_band_labels

        assert _slope_band_labels((5.0, 20.0)) == ["0-5", "5-20", "20+"]

    def test_fractional_breakpoints_rendered_compactly(self):
        from swatplus_builder.gis.hru import _slope_band_labels

        assert _slope_band_labels((2.5,)) == ["0-2.5", "2.5+"]

    def test_no_breakpoints_gives_single_unbounded_band(self):
        from swatplus_builder.gis.hru import _slope_band_labels

        assert _slope_band_labels(()) == ["0+"]
