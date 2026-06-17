"""HRU creation: per-subbasin LU × Soil × Slope overlay → typed LSU + HRU rows.

Ports and tightens ``../../../pipeline/05_create_hru.py`` from a basin-
global overlay to the per-subbasin / per-LSU schema SWAT+ expects.

Phase 1 MVP (what this module does today)
-----------------------------------------

* **One LSU per subbasin** — category ``1`` (floodplain), geometry
  identical to the subbasin polygon. Upslope split (HAND) is a Phase 2
  upgrade.
* **Dominant-HRU mode** (the default, ``dominant_only=True``) — one
  HRU per LSU using the most-frequent ``(landuse, soil, slope_band)``
  triple among the LSU's pixels. This is enough for a first SWAT+ run
  and keeps ``gis_hrus`` trivially small.
* **Optional full-overlay mode** (``dominant_only=False``) — one HRU
  per distinct ``(landuse, soil, slope_band)`` combination within the
  LSU. ``min_hru_fraction`` drops combinations below a threshold of
  the LSU's area to keep table size manageable.

Inputs
------

* ``watershed`` — the :class:`WatershedResult` from
  :func:`gis.delineation.delineate`. Used for the DEM grid (the
  canonical resampling target), the subbasin polygons, and
  channel attributes (joined by ``sub_id``).
* ``landuse_raster`` — single-band integer GeoTIFF; pixel values are
  land-use codes. Resampled nearest-neighbor to the DEM grid.
* ``soil_raster`` — single-band integer GeoTIFF; pixel values are
  gNATSGO mukeys. Naming convention ``soil = f"gnatsgo_{mukey}"``
  matches :func:`swatplus_builder.soil.gnatsgo.fetch_gnatsgo_profiles`
  so HRUs and the ``soils_sol`` table line up at import time.
* ``slope_raster`` — optional single-band float GeoTIFF of slope in
  percent. If omitted, slope is computed from the DEM using a
  3×3 finite-difference (Horn's method, as implemented by
  :func:`numpy.gradient`).
* ``slope_bands`` — list of break points in percent, e.g.
  ``[5.0, 20.0]`` → three classes ``"0-5"``, ``"5-20"``, ``"20+"``.
  Defaults to the SWAT+ Editor's default (``[5.0]`` → two bands).
* ``landuse_lookup`` — optional ``{int code: str name}`` map to
  translate raster codes into SWAT+ plant names (``"AGRL"``,
  ``"FRST"``, …). If omitted, the module's built-in NLCD-2021
  lookup (:data:`swatplus_builder.gis.landuse.NLCD_TO_SWATPLUS`) is
  consulted. Codes present in neither fall back to ``f"lu_{code}"``,
  which is fine for tests but will fail the editor's ``plants_plt``
  FK check at ``import_gis`` time — use that signal to extend your
  lookup.

Outputs (the :class:`HRUResult` file set)
-----------------------------------------

* ``lsus_vector`` — ``lsus.gpkg`` with one polygon per LSU, carrying
  ``lsu_id``, ``sub_id``, ``channel``, ``category``, and the same
  attributes as :class:`LsuRow` in the ``gis_lsus`` table.
* ``hrus_vector`` — ``hrus.gpkg`` with one polygon per HRU. In
  dominant mode the HRU geometry equals the LSU geometry; in full-
  overlay mode the HRU geometry is the union of its pixels
  vectorized via :func:`rasterio.features.shapes`.
* ``hru_raster`` — ``hru_map.tif``, int32 with each pixel labelled
  by its HRU id. Pixels outside any HRU get the raster's ``nodata``.
* ``catalog_path`` — ``hru_catalog.json`` containing the
  serialized :class:`LsuRow` and :class:`HruRow` lists under keys
  ``"lsus"`` / ``"hrus"`` plus summary ``"stats"``. Round-trip via
  :func:`load_lsus_hrus` returns the typed rows ready for
  :func:`swatplus_builder.db.writer.write_all`.

Agent contract
--------------

The module is pure — no network, no subprocesses. All heavy lifting
is local numpy + rasterio. The only external call sites are
``rasterio.open`` (local files) and ``geopandas.GeoDataFrame.to_file``
(local GPKG). This makes HRU generation trivially re-runnable and
deterministic for a given input set — the same inputs produce the
same outputs byte-for-byte.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
import rasterio.features
import rasterio.warp
from pyproj import Transformer
from rasterio.enums import Resampling

from ..config import DEFAULT_SETTINGS, Settings
from ..errors import SwatBuilderInputError, SwatBuilderPipelineError
from ..types import HRUResult, HruRow, LsuRow, WatershedResult
from .landuse import NLCD_TO_SWATPLUS, resolve_landuse

log = logging.getLogger(__name__)

__all__ = ["DEFAULT_SLOPE_BANDS", "create_hrus", "load_lsus_hrus"]

DEFAULT_SLOPE_BANDS: tuple[float, ...] = (5.0,)
"""SWAT+ Editor default: two slope bands split at 5%. Override via
``create_hrus(..., slope_bands=[...])``."""

# Nodata sentinels dropped from the overlay. gNATSGO's mukey and typical
# NLCD-style landuse rasters both use 0; 2**31 - 1 covers rioxarray's
# int32-promoted uint32 nodata. Slope has no zero class (slope bands
# are 1-indexed), so 0 in ``slope_cls_arr`` is "out of watershed".
_MUKEY_NODATA_SENTINELS: frozenset[int] = frozenset({0, 2_147_483_647})
_LU_NODATA_SENTINELS: frozenset[int] = frozenset({0, 2_147_483_647, 255})


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def create_hrus(
    watershed: WatershedResult,
    landuse_raster: Path | str,
    soil_raster: Path | str | None,
    slope_raster: Path | str | None = None,
    *,
    constant_soil_mukey: int | None = None,
    slope_bands: list[float] | tuple[float, ...] | None = None,
    landuse_lookup: dict[int, str] | None = None,
    dominant_only: bool = True,
    min_hru_fraction: float = 0.0,
    workdir_subdir: str = "hrus",
    settings: Settings = DEFAULT_SETTINGS,
) -> HRUResult:
    """Build HRUs from per-subbasin LU × Soil × Slope overlay.

    See the module docstring for behavior; this docstring focuses on
    edge cases.

    Args:
        watershed: Output of :func:`gis.delineation.delineate`.
        landuse_raster: Integer GeoTIFF; values encode landuse classes.
        soil_raster: Integer mukey GeoTIFF (gNATSGO).
            May be ``None`` only when ``constant_soil_mukey`` is supplied.
        constant_soil_mukey: Explicit representative mukey to apply to every
            valid landuse/slope pixel when a spatial soil raster is unavailable.
        slope_raster: Optional slope percent GeoTIFF. If ``None``,
            computed from ``watershed.dem_conditioned``.
        slope_bands: Slope break points in percent. Defaults to
            ``(5.0,)`` (two bands).
        landuse_lookup: Map landuse raster codes → SWAT+ plant names.
            Overrides the built-in NLCD-2021 lookup
            (:data:`swatplus_builder.gis.landuse.NLCD_TO_SWATPLUS`)
            on a per-code basis. Codes missing from both fall back to
            ``f"lu_{code}"``.
        dominant_only: If ``True`` (default), emit one HRU per LSU
            using the most-frequent ``(LU, soil, slope)`` triple.
            Otherwise enumerate every distinct triple per LSU.
        min_hru_fraction: In full-overlay mode (``dominant_only=False``),
            drop HRUs whose area is less than this fraction of the
            parent LSU's area. Ignored when ``dominant_only=True``
            since a single HRU always has fraction ``1.0``.
        workdir_subdir: Subdirectory under ``watershed.workdir`` to
            drop HRU artifacts into. Created if missing.
        settings: Runtime overrides (future-proofing; unused today).

    Returns:
        :class:`HRUResult` with paths to LSU + HRU vectors, the HRU
        id raster, and the catalog JSON. Call :func:`load_lsus_hrus`
        on the result to get back the typed :class:`LsuRow` and
        :class:`HruRow` lists.

    Raises:
        SwatBuilderInputError: any input raster / GPKG is missing or
            unreadable.
        SwatBuilderPipelineError: overlay produced zero HRUs (usually
            means every subbasin was masked out by nodata in one of
            the rasters — check alignment / CRS).
    """
    _ = settings  # reserved

    bands = tuple(slope_bands) if slope_bands is not None else DEFAULT_SLOPE_BANDS
    if not all(b0 < b1 for b0, b1 in zip(bands, bands[1:])):
        raise SwatBuilderInputError(
            f"slope_bands must be strictly increasing, got {bands!r}",
            slope_bands=list(bands),
        )
    slope_labels = _slope_band_labels(bands)

    # --- 1. Validate paths + prepare output dir ---
    lu_path = _require_file(Path(landuse_raster), "landuse_raster")
    soil_path = _require_file(Path(soil_raster), "soil_raster") if soil_raster is not None else None
    if soil_path is None and constant_soil_mukey is None:
        raise SwatBuilderInputError(
            "soil_raster is required unless constant_soil_mukey is supplied.",
            soil_raster=None,
            constant_soil_mukey=None,
        )
    dem_path = _require_file(Path(watershed.dem_conditioned), "dem_conditioned")
    subs_path = _require_file(Path(watershed.subbasins_vector), "subbasins_vector")
    cha_path = _require_file(Path(watershed.channels_vector), "channels_vector")
    out_dir = Path(watershed.workdir).expanduser().resolve() / workdir_subdir
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- 2. Reference grid = DEM ---
    with rasterio.open(dem_path) as dem:
        ref_profile = dem.profile.copy()
        ref_transform = dem.transform
        ref_crs = dem.crs
        ref_shape = (dem.height, dem.width)
        dem_arr = dem.read(1, masked=True).astype("float64").filled(np.nan)

    pixel_area_m2 = abs(ref_transform.a * ref_transform.e)
    pixel_area_ha = pixel_area_m2 / 10_000.0
    log.info(
        "HRU overlay: grid=%sx%s, pixel=%s m², CRS=%s",
        ref_shape[0], ref_shape[1], pixel_area_m2, ref_crs,
    )

    # --- 3. Load + align the three overlay rasters ---
    lu_arr = _align_raster_to_ref(lu_path, ref_profile)
    lu_nodata_values = _nodata_values(lu_path, _LU_NODATA_SENTINELS)
    if soil_path is not None:
        soil_arr = _align_raster_to_ref(soil_path, ref_profile)
        soil_nodata_values = _nodata_values(soil_path, _MUKEY_NODATA_SENTINELS)
        soil_source_mode = "raster"
    else:
        soil_arr = np.full(ref_shape, int(constant_soil_mukey), dtype=np.int64)
        soil_nodata_values = _MUKEY_NODATA_SENTINELS
        soil_source_mode = "constant"

    # Slope: read-and-align or derive from DEM.
    if slope_raster is not None:
        slope_pct_arr = _align_raster_to_ref(
            _require_file(Path(slope_raster), "slope_raster"),
            ref_profile,
            dtype="float32",
        ).astype("float64")
    else:
        slope_pct_arr = _slope_percent_from_dem(dem_arr, ref_transform)
    slope_cls_arr = _classify_slope(slope_pct_arr, bands)

    # --- 4. Rasterize subbasins onto the DEM grid ---
    subs_gdf = gpd.read_file(subs_path).to_crs(ref_crs)
    if "sub_id" not in subs_gdf.columns:
        raise SwatBuilderInputError(
            f"subbasins vector must have a 'sub_id' column; found {list(subs_gdf.columns)}",
            path=str(subs_path),
        )
    sub_arr = rasterio.features.rasterize(
        shapes=((row.geometry, int(row.sub_id)) for row in subs_gdf.itertuples()),
        out_shape=ref_shape,
        transform=ref_transform,
        fill=0,
        dtype="int32",
    )

    # --- 5. Channel attribute lookup for LSU fields ---
    channels_gdf = gpd.read_file(cha_path).to_crs(ref_crs)
    channel_by_sub = _channel_attrs_by_sub(channels_gdf)

    # --- 6. lat/lon transformer ---
    to_wgs84 = Transformer.from_crs(ref_crs, "EPSG:4326", always_xy=True)

    # --- 7. Iterate subbasins → LSUs → HRUs ---
    lsu_rows: list[LsuRow] = []
    hru_rows: list[HruRow] = []
    all_touched_fallback_subbasins: list[int] = []
    missing_hru_subbasins: list[int] = []
    # Per-pixel HRU id output raster (int32, nodata=0 so positive ids are always HRU).
    hru_map = np.zeros(ref_shape, dtype=np.int32)
    next_hru_id = 1

    for sub_row in subs_gdf.itertuples():
        sub_id = int(sub_row.sub_id)
        sub_mask = sub_arr == sub_id
        fallback_mask = rasterio.features.geometry_mask(
            [sub_row.geometry],
            out_shape=ref_shape,
            transform=ref_transform,
            invert=True,
            all_touched=True,
        )
        if not sub_mask.any():
            if fallback_mask.any() and _has_valid_overlay_pixels(fallback_mask, lu_arr, soil_arr, slope_cls_arr, lu_nodata_values, soil_nodata_values):
                sub_mask = fallback_mask
                all_touched_fallback_subbasins.append(sub_id)
                log.warning(
                    "subbasin %s had zero center pixels after rasterization; using all_touched fallback",
                    sub_id,
                )
            else:
                log.warning("subbasin %s has zero raster pixels after rasterization; skipping", sub_id)
                missing_hru_subbasins.append(sub_id)
                continue
        elif not _has_valid_overlay_pixels(sub_mask, lu_arr, soil_arr, slope_cls_arr, lu_nodata_values, soil_nodata_values):
            if fallback_mask.any() and _has_valid_overlay_pixels(fallback_mask, lu_arr, soil_arr, slope_cls_arr, lu_nodata_values, soil_nodata_values):
                sub_mask = fallback_mask
                all_touched_fallback_subbasins.append(sub_id)
                log.warning(
                    "subbasin %s had no valid center-pixel overlay; using all_touched fallback",
                    sub_id,
                )
            else:
                missing_hru_subbasins.append(sub_id)

        sub_area_ha = float(sub_mask.sum()) * pixel_area_ha

        # --- LSU = the subbasin itself, 1-to-1 ---
        lsu_id = sub_id
        lsu_mask = sub_mask  # MVP: no further splitting
        lsu_pixel_count = int(lsu_mask.sum())
        lsu_area_ha = float(lsu_pixel_count) * pixel_area_ha

        # Centroid/elev/slope for the LSU from pixel stats.
        lsu_center_x, lsu_center_y = _pixel_centroid_xy(lsu_mask, ref_transform)
        lsu_lon, lsu_lat = to_wgs84.transform(lsu_center_x, lsu_center_y)
        lsu_slope_pct = _safe_mean(slope_pct_arr[lsu_mask])
        lsu_elev = _safe_mean(dem_arr[lsu_mask])

        # Channel attributes — fall back to safe minimal defaults if
        # the subbasin has no channel row (usually means a headwater
        # lost its single-pixel link during vectorization).
        chan = channel_by_sub.get(sub_id, _DEFAULT_CHANNEL_ATTRS)

        lsu_rows.append(
            LsuRow(
                id=lsu_id,
                category=1,
                channel=int(chan["channel_id"]),
                subbasin=sub_id,
                area=round(lsu_area_ha, 6),
                slope=round(lsu_slope_pct, 6),
                len1=round(chan["length_m"], 3),
                csl=round(chan["slope_pct"], 6),
                wid1=round(chan["width_m"], 3),
                dep1=round(chan["depth_m"], 3),
                lat=round(float(lsu_lat), 8),
                lon=round(float(lsu_lon), 8),
                elev=round(lsu_elev, 3),
            )
        )

        # --- HRUs inside the LSU ---
        lu_flat = lu_arr[lsu_mask]
        soil_flat = soil_arr[lsu_mask]
        slope_flat = slope_cls_arr[lsu_mask]
        valid = (
            np.isin(lu_flat, list(lu_nodata_values), invert=True)
            & np.isin(soil_flat, list(soil_nodata_values), invert=True)
            & (slope_flat > 0)
        )
        if not valid.any():
            log.warning("subbasin %s has no valid overlay pixels; LSU has no HRUs", sub_id)
            if sub_id not in missing_hru_subbasins:
                missing_hru_subbasins.append(sub_id)
            continue

        triples = list(
            zip(
                lu_flat[valid].astype(int).tolist(),
                soil_flat[valid].astype(int).tolist(),
                slope_flat[valid].astype(int).tolist(),
            )
        )
        combo_counts = Counter(triples)
        total_valid_pixels = sum(combo_counts.values())

        if dominant_only:
            dominant_combo, _ = combo_counts.most_common(1)[0]
            selected = [(dominant_combo, total_valid_pixels)]
        else:
            selected = [
                (combo, count)
                for combo, count in combo_counts.most_common()
                if count / total_valid_pixels >= min_hru_fraction
            ]
            if not selected:
                # Even with aggressive filtering, keep the dominant.
                dominant_combo, cnt = combo_counts.most_common(1)[0]
                selected = [(dominant_combo, cnt)]

        # Precompute per-(lu) and per-(lu,soil) pixel counts inside LSU
        # so ``arland`` / ``arso`` are correct even when the same LU
        # appears with multiple soils.
        lu_pixel_counts: Counter[int] = Counter()
        lu_soil_pixel_counts: Counter[tuple[int, int]] = Counter()
        for lu_v, soil_v, _cls in triples:
            lu_pixel_counts[lu_v] += 1
            lu_soil_pixel_counts[(lu_v, soil_v)] += 1

        for (lu_code, mukey, slope_cls), _count in selected:
            hru_id = next_hru_id
            next_hru_id += 1

            # Pixel mask of the combo as it actually appears in the LSU —
            # used for slope / centroid in full-overlay mode.
            combo_mask = (
                lsu_mask
                & (lu_arr == lu_code)
                & (soil_arr == mukey)
                & (slope_cls_arr == slope_cls)
            )

            # SWAT+ dominance semantics: in dominant mode, the single HRU
            # inherits the ENTIRE LSU's geometry + area. The non-dominant
            # pixels are "reassigned" to the dominant class for routing
            # purposes — this is the point of the approximation. In full-
            # overlay mode the HRU keeps only its own pixels.
            if dominant_only:
                hru_mask = lsu_mask
                arland = lsu_area_ha
                arso = lsu_area_ha
                hru_slope = lsu_slope_pct
                hru_elev = lsu_elev
                h_lon, h_lat = lsu_lon, lsu_lat
            else:
                if not combo_mask.any():
                    continue
                hru_mask = combo_mask
                arland = float(lu_pixel_counts[lu_code]) * pixel_area_ha
                arso = float(lu_soil_pixel_counts[(lu_code, mukey)]) * pixel_area_ha
                hru_slope = _safe_mean(slope_pct_arr[combo_mask])
                hru_elev = _safe_mean(dem_arr[combo_mask])
                cx, cy = _pixel_centroid_xy(combo_mask, ref_transform)
                h_lon, h_lat = to_wgs84.transform(cx, cy)

            hru_map[hru_mask] = hru_id
            hru_pixel_count = int(hru_mask.sum())
            hru_area_ha = float(hru_pixel_count) * pixel_area_ha

            hru_rows.append(
                HruRow(
                    id=hru_id,
                    lsu=lsu_id,
                    arsub=round(sub_area_ha, 6),
                    arlsu=round(lsu_area_ha, 6),
                    landuse=_landuse_name(lu_code, landuse_lookup),
                    arland=round(arland, 6),
                    soil=f"gnatsgo_{mukey}",
                    arso=round(arso, 6),
                    slp=slope_labels[slope_cls - 1],
                    arslp=round(hru_area_ha, 6),
                    slope=round(hru_slope, 6),
                    lat=round(float(h_lat), 8),
                    lon=round(float(h_lon), 8),
                    elev=round(hru_elev, 3),
                )
            )

    if not hru_rows:
        raise SwatBuilderPipelineError(
            "HRU overlay produced zero HRUs — check that landuse / soil / "
            "slope rasters cover the watershed and share its CRS.",
            landuse_raster=str(lu_path),
            soil_raster=str(soil_path) if soil_path is not None else None,
            constant_soil_mukey=constant_soil_mukey,
            n_subbasins=int(len(subs_gdf)),
        )

    # --- 8. Write HRU id raster ---
    hru_raster_path = out_dir / "hru_map.tif"
    hru_profile = {
        "driver": "GTiff",
        "height": ref_shape[0],
        "width": ref_shape[1],
        "count": 1,
        "dtype": "int32",
        "crs": ref_crs,
        "transform": ref_transform,
        "nodata": 0,
        "compress": "deflate",
    }
    with rasterio.open(hru_raster_path, "w", **hru_profile) as dst:
        dst.write(hru_map, 1)

    # --- 9. Write LSU + HRU vectors ---
    lsus_vector_path = out_dir / "lsus.gpkg"
    hrus_vector_path = out_dir / "hrus.gpkg"
    _write_lsu_vector(lsus_vector_path, lsu_rows, subs_gdf, ref_crs)
    _write_hru_vector(
        hrus_vector_path, hru_rows, hru_map, ref_transform, ref_crs,
        subs_gdf=subs_gdf,  # used to copy geometry in dominant mode
        dominant_only=dominant_only,
    )

    # --- 10. Catalog JSON (typed rows embedded) ---
    catalog_path = out_dir / "hru_catalog.json"
    catalog = {
        "lsus": [r.model_dump() for r in lsu_rows],
        "hrus": [r.model_dump() for r in hru_rows],
        "stats": {
            "n_subbasins": int(len(subs_gdf)),
            "n_lsus": len(lsu_rows),
            "n_hrus": len(hru_rows),
            "pixel_area_m2": float(pixel_area_m2),
            "dominant_only": bool(dominant_only),
            "slope_bands": list(bands),
            "slope_labels": list(slope_labels),
            "soil_source_mode": soil_source_mode,
            "constant_soil_mukey": constant_soil_mukey,
            "landuse_nodata_values": sorted(lu_nodata_values),
            "soil_nodata_values": sorted(soil_nodata_values),
            "overlay_all_touched_fallback_subbasins": all_touched_fallback_subbasins,
            "overlay_missing_hru_subbasins": missing_hru_subbasins,
            "overlay_all_touched_fallback_count": len(all_touched_fallback_subbasins),
            "overlay_missing_hru_subbasin_count": len(missing_hru_subbasins),
        },
    }
    catalog_path.write_text(json.dumps(catalog, indent=2))
    log.info(
        "wrote %s LSUs and %s HRUs to %s", len(lsu_rows), len(hru_rows), out_dir
    )

    return HRUResult(
        workdir=out_dir,
        lsus_vector=lsus_vector_path,
        hrus_vector=hrus_vector_path,
        hru_raster=hru_raster_path,
        catalog_path=catalog_path,
        stats={
            "n_subbasins": float(len(subs_gdf)),
            "n_lsus": float(len(lsu_rows)),
            "n_hrus": float(len(hru_rows)),
            "hru_coverage_ratio": float(len(hru_rows) / max(len(subs_gdf), 1)),
            "overlay_all_touched_fallback_count": float(len(all_touched_fallback_subbasins)),
            "overlay_missing_hru_subbasin_count": float(len(missing_hru_subbasins)),
            "total_lsu_area_ha": round(sum(r.area for r in lsu_rows), 3),
            "total_hru_area_ha": round(sum(r.arslp for r in hru_rows), 3),
        },
    )


# ---------------------------------------------------------------------------
# load_lsus_hrus — round-trip helper
# ---------------------------------------------------------------------------


def load_lsus_hrus(hru_result: HRUResult) -> tuple[list[LsuRow], list[HruRow]]:
    """Parse the catalog JSON produced by :func:`create_hrus` back into typed rows.

    Designed for the handoff to :func:`swatplus_builder.db.writer.write_all` —
    callers can assemble a :class:`GisTables` without re-running any GIS.

    Args:
        hru_result: The :class:`HRUResult` returned by
            :func:`create_hrus`.

    Returns:
        ``(lsu_rows, hru_rows)`` — pydantic-validated lists mirroring the
        order written to ``hru_catalog.json``.
    """
    path = Path(hru_result.catalog_path)
    if not path.is_file():
        raise SwatBuilderInputError(
            f"HRU catalog not found: {path}", catalog_path=str(path)
        )
    data = json.loads(path.read_text())
    lsus = [LsuRow.model_validate(r) for r in data.get("lsus", [])]
    hrus = [HruRow.model_validate(r) for r in data.get("hrus", [])]
    return lsus, hrus


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_DEFAULT_CHANNEL_ATTRS: dict[str, float] = {
    "channel_id": 1,
    "length_m": 100.0,
    "slope_pct": 0.01,
    "width_m": 1.0,
    "depth_m": 0.1,
}


def _require_file(path: Path, label: str) -> Path:
    p = path.expanduser().resolve()
    if not p.is_file():
        raise SwatBuilderInputError(f"{label} not found: {p}", path=str(p))
    return p


def _slope_band_labels(bands: tuple[float, ...]) -> list[str]:
    """Turn break points into human labels: ``(5.0, 20.0)`` → ``["0-5", "5-20", "20+"]``."""
    if not bands:
        return ["0+"]
    out: list[str] = [f"0-{_fmt(bands[0])}"]
    for lo, hi in zip(bands, bands[1:]):
        out.append(f"{_fmt(lo)}-{_fmt(hi)}")
    out.append(f"{_fmt(bands[-1])}+")
    return out


def _fmt(v: float) -> str:
    """Compact numeric formatting for slope-band labels (``5`` not ``5.0``)."""
    if float(v).is_integer():
        return str(int(v))
    return f"{v:g}"


def _align_raster_to_ref(
    src_path: Path,
    ref_profile: dict[str, Any],
    *,
    dtype: str | None = None,
) -> np.ndarray:
    """Reproject ``src_path`` to the reference grid via nearest-neighbor.

    Always returns a single-band 2D array. Output dtype follows the
    source dtype unless ``dtype`` overrides.
    """
    dst_shape = (ref_profile["height"], ref_profile["width"])
    with rasterio.open(src_path) as src:
        src_dtype = src.dtypes[0]
        out_dtype = dtype or src_dtype
        src_nodata = src.nodata
        dst = np.zeros(dst_shape, dtype=out_dtype)
        if src_nodata is not None:
            dst.fill(src_nodata if np.issubdtype(np.dtype(out_dtype), np.integer)
                     else 0)
        rasterio.warp.reproject(
            source=rasterio.band(src, 1),
            destination=dst,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=ref_profile["transform"],
            dst_crs=ref_profile["crs"],
            resampling=Resampling.nearest,
        )
    return dst


def _nodata_values(path: Path, sentinels: frozenset[int]) -> frozenset[int]:
    """Return hard-coded plus raster-declared integer nodata values."""
    values = set(sentinels)
    with rasterio.open(path) as src:
        if src.nodata is not None and np.isfinite(src.nodata):
            values.add(int(src.nodata))
    return frozenset(values)


def _slope_percent_from_dem(
    dem: np.ndarray, transform: rasterio.Affine
) -> np.ndarray:
    """Percent slope from a DEM via nodata-aware finite differences.

    Slopes are computed only where the current cell and both opposite
    neighbors are finite along an axis. Cells touching DEM nodata remain
    ``NaN`` instead of being differenced against an artificial zero value.
    This avoids creating edge cliffs at the watershed/DEM boundary.
    """
    dx = abs(transform.a)
    dy = abs(transform.e)
    dem_arr = np.asarray(dem, dtype="float64")
    dzdx = _central_gradient_where_finite(dem_arr, dx, axis=1)
    dzdy = _central_gradient_where_finite(dem_arr, dy, axis=0)
    slope = np.sqrt(dzdx**2 + dzdy**2) * 100.0
    return slope.astype("float64")


def _central_gradient_where_finite(
    arr: np.ndarray,
    spacing: float,
    *,
    axis: int,
) -> np.ndarray:
    """Finite difference that preserves nodata edges as ``NaN``.

    Interior cells require finite opposite neighbors. The outer raster frame
    uses ordinary one-sided differences when the adjacent cell is finite; this
    avoids creating artificial slope classes on otherwise complete rasters.
    """
    out = np.full(arr.shape, np.nan, dtype="float64")
    if spacing <= 0 or arr.shape[axis] < 2:
        return out

    first = [slice(None)] * arr.ndim
    second = [slice(None)] * arr.ndim
    first[axis] = 0
    second[axis] = 1
    first_vals = arr[tuple(first)]
    second_vals = arr[tuple(second)]
    valid_first = np.isfinite(first_vals) & np.isfinite(second_vals)
    first_gradient = np.full(first_vals.shape, np.nan, dtype="float64")
    first_gradient[valid_first] = (second_vals[valid_first] - first_vals[valid_first]) / spacing
    out[tuple(first)] = first_gradient

    last = [slice(None)] * arr.ndim
    penultimate = [slice(None)] * arr.ndim
    last[axis] = -1
    penultimate[axis] = -2
    last_vals = arr[tuple(last)]
    penultimate_vals = arr[tuple(penultimate)]
    valid_last = np.isfinite(last_vals) & np.isfinite(penultimate_vals)
    last_gradient = np.full(last_vals.shape, np.nan, dtype="float64")
    last_gradient[valid_last] = (last_vals[valid_last] - penultimate_vals[valid_last]) / spacing
    out[tuple(last)] = last_gradient

    if arr.shape[axis] >= 3:
        core = [slice(None)] * arr.ndim
        before = [slice(None)] * arr.ndim
        after = [slice(None)] * arr.ndim
        core[axis] = slice(1, -1)
        before[axis] = slice(0, -2)
        after[axis] = slice(2, None)

        center_vals = arr[tuple(core)]
        before_vals = arr[tuple(before)]
        after_vals = arr[tuple(after)]
        valid = (
            np.isfinite(center_vals)
            & np.isfinite(before_vals)
            & np.isfinite(after_vals)
        )
        gradient = np.full(center_vals.shape, np.nan, dtype="float64")
        gradient[valid] = (after_vals[valid] - before_vals[valid]) / (2.0 * spacing)
        out[tuple(core)] = gradient
    return out


def _classify_slope(
    slope_pct: np.ndarray, bands: tuple[float, ...]
) -> np.ndarray:
    """Map a percent-slope array into 1-indexed band ids.

    Cell ``v`` with ``bands=(5.0, 20.0)`` maps to:
      * ``1`` when ``v <= 5``      (band label ``"0-5"``)
      * ``2`` when ``5 < v <= 20`` (band label ``"5-20"``)
      * ``3`` when ``v > 20``      (band label ``"20+"``)

    Always returns ``int8`` — number of slope classes is bounded by
    ``len(bands) + 1`` which is always ≤ 10 in practice.
    """
    classes = np.ones(slope_pct.shape, dtype=np.int8)
    for idx, cut in enumerate(bands, start=1):
        classes = np.where(slope_pct > cut, idx + 1, classes)
    # Cells with NaN slope fall into band 1 (see _slope_percent_from_dem).
    return classes


def _has_valid_overlay_pixels(
    mask: np.ndarray,
    lu_arr: np.ndarray,
    soil_arr: np.ndarray,
    slope_cls_arr: np.ndarray,
    lu_nodata_values: frozenset[int],
    soil_nodata_values: frozenset[int],
) -> bool:
    """Return true when a candidate LSU mask contains usable HRU overlay cells."""
    if not mask.any():
        return False
    lu_flat = lu_arr[mask]
    soil_flat = soil_arr[mask]
    slope_flat = slope_cls_arr[mask]
    valid = (
        np.isin(lu_flat, list(lu_nodata_values), invert=True)
        & np.isin(soil_flat, list(soil_nodata_values), invert=True)
        & (slope_flat > 0)
    )
    return bool(valid.any())


def _pixel_centroid_xy(
    mask: np.ndarray, transform: rasterio.Affine
) -> tuple[float, float]:
    """Return the (x, y) centroid of the True pixels in ``mask``.

    Uses the geometric mean of pixel *centers* rather than the bounding
    box. For an LSU spanning the whole watershed this is effectively
    the area-weighted centroid because every pixel has equal area.
    """
    rows, cols = np.where(mask)
    if rows.size == 0:
        return 0.0, 0.0
    # rasterio.transform.xy returns pixel centers when offset='center' (default).
    xs, ys = rasterio.transform.xy(transform, rows.tolist(), cols.tolist())
    # ``xy`` returns lists of the same length; mean is fine.
    xs_arr = np.asarray(xs, dtype="float64")
    ys_arr = np.asarray(ys, dtype="float64")
    return float(xs_arr.mean()), float(ys_arr.mean())


def _safe_mean(values: np.ndarray) -> float:
    """Mean that tolerates empty / all-NaN arrays.

    Returns ``0.0`` if nothing finite is available — downstream
    validators will catch this as an anomaly and agents can inspect
    the catalog JSON to see which LSU degenerated.
    """
    arr = np.asarray(values, dtype="float64")
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return 0.0
    return float(finite.mean())


def _channel_attrs_by_sub(
    channels_gdf: gpd.GeoDataFrame,
) -> dict[int, dict[str, float]]:
    """Build a ``{sub_id: {channel_id, length_m, slope_pct, width_m, depth_m}}`` lookup.

    When a subbasin has multiple channels (shouldn't happen with
    WBT StreamLinkIdentifier but possible after lake burning), we
    pick the longest one as the "main" channel for that subbasin
    — it's the one SWAT+ routes through.
    """
    out: dict[int, dict[str, float]] = {}
    if "sub_id" not in channels_gdf.columns:
        return out

    def _col(name: str, fallback: float) -> Any:
        """Column lookup with a default when the attribute is missing
        (e.g. a test fixture without the full delineation.py attrs)."""
        return (
            channels_gdf[name]
            if name in channels_gdf.columns
            else np.full(len(channels_gdf), fallback)
        )

    length_col = _col("length_m", 100.0)
    slope_col = _col("slope_m_m", 0.0001)
    width_col = _col("width_m", 1.0)
    depth_col = _col("depth_m", 0.1)
    link_col = _col("link_id", 1)

    for i, row in enumerate(channels_gdf.itertuples()):
        # WBT sometimes leaves a channel centroid outside every subbasin
        # polygon (edge-of-watershed artifacts from the raster→vector
        # conversion).  Those rows come back as NaN from the sjoin above;
        # skip them rather than raise.
        sid_raw = getattr(row, "sub_id", 0)
        try:
            sid = int(sid_raw)
        except (TypeError, ValueError):
            continue
        if sid <= 0:
            continue
        length = float(length_col.iloc[i] if hasattr(length_col, "iloc") else length_col[i])
        if sid in out and out[sid]["length_m"] >= length:
            continue
        slope_m_m = float(slope_col.iloc[i] if hasattr(slope_col, "iloc") else slope_col[i])
        out[sid] = {
            "channel_id": int(link_col.iloc[i] if hasattr(link_col, "iloc") else link_col[i]),
            "length_m": length,
            "slope_pct": slope_m_m * 100.0,
            "width_m": float(width_col.iloc[i] if hasattr(width_col, "iloc") else width_col[i]),
            "depth_m": float(depth_col.iloc[i] if hasattr(depth_col, "iloc") else depth_col[i]),
        }
    return out


def _landuse_name(code: int, lookup: dict[int, str] | None) -> str:
    """Resolve a raster LU code → SWAT+ plant/urban name.

    See :func:`swatplus_builder.gis.landuse.resolve_landuse` for the
    full resolution chain. We pass ``default_lookup=NLCD_TO_SWATPLUS``
    so agents who supply no ``lookup`` at all still get realistic
    plant codes for NLCD rasters.
    """
    return resolve_landuse(code, lookup, default_lookup=NLCD_TO_SWATPLUS)


def _write_lsu_vector(
    path: Path,
    lsu_rows: list[LsuRow],
    subs_gdf: gpd.GeoDataFrame,
    crs: Any,
) -> None:
    """Emit ``lsus.gpkg`` with one polygon per LSU (geometry from subbasins)."""
    sub_geom_by_id = {int(r.sub_id): r.geometry for r in subs_gdf.itertuples()}
    records: list[dict[str, Any]] = []
    geoms: list[Any] = []
    for lsu in lsu_rows:
        geom = sub_geom_by_id.get(lsu.subbasin)
        if geom is None:
            continue
        records.append(
            {
                "lsu_id": lsu.id,
                "sub_id": lsu.subbasin,
                "channel": lsu.channel,
                "category": int(lsu.category),
                "area_ha": lsu.area,
                "slope_pct": lsu.slope,
                "len1_m": lsu.len1,
                "csl_pct": lsu.csl,
                "wid1_m": lsu.wid1,
                "dep1_m": lsu.dep1,
                "lat": lsu.lat,
                "lon": lsu.lon,
                "elev_m": lsu.elev,
            }
        )
        geoms.append(geom)
    gdf = _fiona_safe_gdf(gpd.GeoDataFrame(records, geometry=geoms, crs=crs))
    gdf.to_file(path, driver="GPKG")


def _write_hru_vector(
    path: Path,
    hru_rows: list[HruRow],
    hru_map: np.ndarray,
    transform: rasterio.Affine,
    crs: Any,
    *,
    subs_gdf: gpd.GeoDataFrame,
    dominant_only: bool,
) -> None:
    """Emit ``hrus.gpkg``.

    Dominant mode
        The LSU is the HRU. We copy the parent subbasin's polygon and
        tag it with the HRU attributes.

    Full-overlay mode
        Each HRU's geometry is the union of its pixels, vectorized via
        :func:`rasterio.features.shapes`. This is slower (O(N pixels))
        but necessary so downstream zonal operations work.
    """
    from shapely.geometry import shape as shp_shape
    from shapely.ops import unary_union

    if dominant_only:
        # LSU id == subbasin id == lsu, so we can go straight to the subs GDF.
        sub_geom_by_id = {int(r.sub_id): r.geometry for r in subs_gdf.itertuples()}
        records, geoms = [], []
        for hru in hru_rows:
            geom = sub_geom_by_id.get(hru.lsu)
            if geom is None:
                continue
            records.append(_hru_to_record(hru))
            geoms.append(geom)
        _fiona_safe_gdf(gpd.GeoDataFrame(records, geometry=geoms, crs=crs)).to_file(path, driver="GPKG")
        return

    # Full-overlay: vectorize per-hru pixels.
    records, geoms = [], []
    for hru in hru_rows:
        mask = hru_map == hru.id
        if not mask.any():
            continue
        shapes = rasterio.features.shapes(
            hru_map, mask=mask, transform=transform
        )
        polys = [shp_shape(g) for g, _v in shapes]
        if not polys:
            continue
        records.append(_hru_to_record(hru))
        geoms.append(unary_union(polys))
    _fiona_safe_gdf(gpd.GeoDataFrame(records, geometry=geoms, crs=crs)).to_file(path, driver="GPKG")


def _hru_to_record(hru: HruRow) -> dict[str, Any]:
    """Flatten a :class:`HruRow` into a GPKG-compatible attribute dict."""
    return {
        "hru_id": hru.id,
        "lsu_id": hru.lsu,
        "arsub_ha": hru.arsub,
        "arlsu_ha": hru.arlsu,
        "landuse": hru.landuse,
        "arland_ha": hru.arland,
        "soil": hru.soil,
        "arso_ha": hru.arso,
        "slp": hru.slp,
        "arslp_ha": hru.arslp,
        "slope_pct": hru.slope,
        "lat": hru.lat,
        "lon": hru.lon,
        "elev_m": hru.elev,
    }


def _fiona_safe_gdf(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    import pandas as pd

    out = gdf.copy()
    geometry_name = out.geometry.name if out.geometry is not None else None
    for column in out.columns:
        if column == geometry_name:
            continue
        if pd.api.types.is_extension_array_dtype(out[column].dtype):
            out[column] = out[column].astype("object").where(out[column].notna(), None)
    return out
