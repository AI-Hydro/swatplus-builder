"""Mukey raster → unique-mukey-set extractor (GIS side of the soil pipeline).

This module is the glue between the GIS stage (delineation → watershed
polygon) and the tabular soil stage (:mod:`swatplus_builder.soil.gnatsgo`
→ :class:`~swatplus_builder.types.SoilProfile`). Its single job is to
answer "which map unit keys (mukeys) touch this watershed?" so
``fetch_gnatsgo_profiles`` knows which rows to pull from the gNATSGO
Parquet tables.

Scope is deliberately narrow — we do NOT emit ``soils_sol`` rows from
here; that lives in :mod:`swatplus_builder.soil.writer`. The legacy
stub's ``SoilRow`` / ``SoilLayerRow`` / ``build_soil_rows`` API is
removed: it conflated three concerns (raster I/O, tabular joins, DB
writes) and has been superseded by the typed
:class:`~swatplus_builder.types.SoilProfile` pipeline.

Two entry points, both stream-of-consciousness obvious:

* :func:`extract_unique_mukeys` — pure-local: given a GeoTIFF mukey
  raster (+ optional clipping polygon), return the set of int mukeys
  present.
* :func:`fetch_mukey_raster` — cloud: given a watershed boundary,
  query Microsoft Planetary Computer's ``gnatsgo-rasters`` collection,
  clip the mukey asset, and drop a local GeoTIFF.
* :func:`extract_mukeys_for_watershed` — agent-facing: takes a
  :class:`~swatplus_builder.types.WatershedResult` and returns the
  ready-to-pass ``set[int]`` for
  :func:`swatplus_builder.soil.gnatsgo.fetch_gnatsgo_profiles`. BYO
  raster path or let us fetch one.

Lazy imports
------------

``rasterio`` / ``shapely`` / ``geopandas`` are already runtime
dependencies of the ``[gis]`` extra used by every other ``gis.*``
module, so they import at module top level. Planetary Computer deps
(``pystac-client``, ``planetary-computer``) live in the ``[soils]``
extra and are lazy-imported inside :func:`fetch_mukey_raster` — we
never want the raster-only path to require an Azure client.

Nodata handling
---------------

gNATSGO mukey rasters are ``uint32`` with a canonical nodata of
``2_147_483_647`` (int32 max, because upstream toolchains often promote
to int32). We honor ``src.nodata`` when set AND drop the literal
value ``0`` because gNATSGO assigns ``0`` to "no map unit / water /
urban land" — none of which can anchor a SWAT+ soil row. Callers can
override via ``nodata_sentinels``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import rasterio
import rasterio.mask
import rasterio.warp
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

from ..config import DEFAULT_SETTINGS, Settings
from ..errors import (
    SwatBuilderExternalError,
    SwatBuilderInputError,
    SwatBuilderPipelineError,
)

if TYPE_CHECKING:
    from ..types import WatershedResult

log = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_PC_STAC_URL",
    "DEFAULT_RASTERS_COLLECTION",
    "extract_mukeys_for_watershed",
    "extract_unique_mukeys",
    "fetch_mukey_raster",
]

DEFAULT_PC_STAC_URL: str = "https://planetarycomputer.microsoft.com/api/stac/v1"
"""Microsoft Planetary Computer STAC root. Stable URL; override only
for testing against a local mirror."""

DEFAULT_RASTERS_COLLECTION: str = "gnatsgo-rasters"
"""Planetary Computer collection id for gNATSGO raster assets."""

# Default nodata sentinels for gNATSGO mukey rasters. ``0`` is
# "no map unit"; the int32 MAX is rioxarray's post-read nodata after
# promoting from uint32 (see rioxarray#525).
_DEFAULT_NODATA_SENTINELS: tuple[int, ...] = (0, 2_147_483_647)


# ---------------------------------------------------------------------------
# extract_unique_mukeys — local, fast, no cloud
# ---------------------------------------------------------------------------


def extract_unique_mukeys(
    raster_path: Path | str,
    *,
    boundary: BaseGeometry | None = None,
    boundary_crs: str | int | None = None,
    nodata_sentinels: Iterable[int] = _DEFAULT_NODATA_SENTINELS,
) -> set[int]:
    """Return the set of distinct mukeys that touch ``boundary``.

    Args:
        raster_path: Path to a single-band integer GeoTIFF whose pixel
            values are SSURGO/gNATSGO map unit keys. Must be readable
            by rasterio.
        boundary: Optional Shapely geometry. If provided, only pixels
            *inside* it contribute mukeys. If ``None``, the full
            raster is scanned — useful when the raster was already
            clipped to the watershed upstream.
        boundary_crs: CRS of ``boundary``, as an EPSG int (``4326``),
            an authority string (``"EPSG:5070"``), or a proj string.
            Ignored when ``boundary`` is ``None``. If ``None`` and
            ``boundary`` is passed, we assume the boundary is already
            in the raster's CRS (caller's responsibility).
        nodata_sentinels: Integer values treated as "no data" and
            removed from the result. Defaults to ``(0, 2**31 - 1)``
            which covers gNATSGO's conventions; override when reading
            non-gNATSGO mukey rasters.

    Returns:
        A ``set[int]`` of unique mukey values. Empty set is a valid
        (but usually unexpected) result; the caller should treat it
        as "no overlap / bad raster".

    Raises:
        SwatBuilderInputError: raster doesn't exist or isn't readable.
        SwatBuilderPipelineError: raster has unexpected shape (multi-
            band, float dtype, etc.) — mukey rasters are always
            single-band integer.
    """
    p = Path(raster_path).expanduser().resolve()
    if not p.is_file():
        raise SwatBuilderInputError(
            f"mukey raster does not exist: {p}", raster_path=str(p)
        )

    with rasterio.open(p) as src:
        if src.count != 1:
            raise SwatBuilderPipelineError(
                f"mukey raster must be single-band, got {src.count} bands",
                raster_path=str(p),
                bands=src.count,
            )
        if not np.issubdtype(np.dtype(src.dtypes[0]), np.integer):
            raise SwatBuilderPipelineError(
                f"mukey raster must be integer dtype, got {src.dtypes[0]}",
                raster_path=str(p),
                dtype=str(src.dtypes[0]),
            )

        if boundary is None:
            arr = src.read(1)
        else:
            geom = _reproject_geom_to_raster(
                boundary, src_crs=boundary_crs, dst_crs=src.crs
            )
            try:
                masked, _transform = rasterio.mask.mask(
                    src,
                    [mapping(geom)],
                    crop=True,
                    filled=True,
                    indexes=1,
                    nodata=src.nodata if src.nodata is not None else 0,
                )
            except ValueError as exc:
                # Most commonly: boundary outside the raster extent.
                raise SwatBuilderPipelineError(
                    f"boundary did not intersect raster extent: {exc}",
                    raster_path=str(p),
                    raster_bounds=tuple(src.bounds),
                ) from exc
            arr = masked  # single-band return when indexes=1

        raster_nodata = src.nodata

    # Pull unique values once; exclude nodata + sentinels.
    uniques: set[int] = {int(v) for v in np.unique(arr)}
    if raster_nodata is not None:
        uniques.discard(int(raster_nodata))
    for sentinel in nodata_sentinels:
        uniques.discard(int(sentinel))
    return uniques


# ---------------------------------------------------------------------------
# fetch_mukey_raster — Planetary Computer ``gnatsgo-rasters``
# ---------------------------------------------------------------------------


def fetch_mukey_raster(
    boundary: BaseGeometry,
    *,
    output_path: Path | str,
    boundary_crs: str | int = 4326,
    stac_url: str = DEFAULT_PC_STAC_URL,
    collection: str = DEFAULT_RASTERS_COLLECTION,
    settings: Settings = DEFAULT_SETTINGS,
) -> Path:
    """Download a mukey GeoTIFF clipped to ``boundary`` from gNATSGO on PC.

    Args:
        boundary: Watershed polygon (Shapely) in ``boundary_crs``. Used
            to derive the STAC bbox query (in EPSG:4326) and to clip
            the returned raster pixel-for-pixel.
        output_path: Where to write the clipped GeoTIFF. Parent dir is
            created if missing.
        boundary_crs: CRS of ``boundary`` as EPSG int, ``"EPSG:…"``
            string, or proj string. Defaults to WGS84 (``4326``).
        stac_url: Override for the PC STAC endpoint. Mostly for tests.
        collection: STAC collection id. Defaults to
            ``"gnatsgo-rasters"``.
        settings: Runtime overrides (future-proofing; unused today).

    Returns:
        Absolute path to the written GeoTIFF (== ``output_path``
        resolved).

    Raises:
        SwatBuilderExternalError: missing optional extras (`[soils]`),
            PC query failed, or no raster items cover the boundary.
        SwatBuilderPipelineError: the returned item has no ``mukey``
            asset (PC schema drift).

    Notes:
        The gNATSGO raster collection is tiled at the state level.
        For a single-state watershed we expect one item; for a
        multi-state watershed we may need to mosaic. This function
        currently takes the **first** matching item and clips to
        ``boundary`` — acceptable for the tests we target (single-
        state US watersheds). Mosaic support is a follow-up.
    """
    _ = settings  # reserved for future cache/timeout knobs
    try:
        import planetary_computer  # type: ignore[import-untyped]
        import pystac_client  # type: ignore[import-untyped]
    except ImportError as exc:
        raise SwatBuilderExternalError(
            "fetch_mukey_raster requires optional extras. "
            "Install with: pip install 'swatplus-builder[soils]'",
            missing=str(exc),
            extra_install="swatplus-builder[soils]",
        ) from exc

    out = Path(output_path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    # STAC expects bbox in WGS84 degrees. Reproject the boundary envelope
    # rather than the full polygon — faster and no geometry surprises.
    bbox_wgs84 = _boundary_bbox_wgs84(boundary, boundary_crs)

    try:
        catalog = pystac_client.Client.open(
            stac_url, modifier=planetary_computer.sign_inplace
        )
        search = catalog.search(collections=[collection], bbox=bbox_wgs84)
        items = list(search.items())
    except Exception as exc:
        raise SwatBuilderExternalError(
            f"Planetary Computer STAC query failed: {exc}",
            stac_url=stac_url,
            collection=collection,
            bbox=list(bbox_wgs84),
        ) from exc

    if not items:
        raise SwatBuilderExternalError(
            f"no {collection!r} items intersect boundary",
            bbox=list(bbox_wgs84),
            collection=collection,
        )

    item = items[0]
    if "mukey" not in item.assets:
        raise SwatBuilderPipelineError(
            f"STAC item {item.id!r} has no 'mukey' asset",
            available=sorted(item.assets),
            item_id=item.id,
        )
    href = item.assets["mukey"].href  # signed via modifier above

    # Open the remote COG, reproject the boundary into its CRS, clip,
    # and write. rasterio handles /vsicurl for signed URLs transparently.
    try:
        with rasterio.open(href) as src:
            geom = _reproject_geom_to_raster(
                boundary, src_crs=boundary_crs, dst_crs=src.crs
            )
            clipped, transform = rasterio.mask.mask(
                src,
                [mapping(geom)],
                crop=True,
                filled=True,
                indexes=1,
                nodata=src.nodata if src.nodata is not None else 0,
            )
            profile = src.profile.copy()
            profile.update(
                height=clipped.shape[0],
                width=clipped.shape[1],
                transform=transform,
                count=1,
                compress="deflate",
            )
            with rasterio.open(out, "w", **profile) as dst:
                dst.write(clipped, 1)
    except rasterio.errors.RasterioIOError as exc:
        raise SwatBuilderExternalError(
            f"reading/writing mukey raster failed: {exc}",
            href=href,
            output_path=str(out),
        ) from exc

    log.info("wrote mukey raster: %s (item=%s)", out, item.id)
    return out


# ---------------------------------------------------------------------------
# Agent-facing wrapper
# ---------------------------------------------------------------------------


def extract_mukeys_for_watershed(
    watershed: "WatershedResult",
    *,
    mukey_raster: Path | str | None = None,
    cache_dir: Path | str | None = None,
    settings: Settings = DEFAULT_SETTINGS,
) -> set[int]:
    """Agent tool: watershed → ``set[int]`` of unique mukeys.

    Args:
        watershed: Output of :func:`swatplus_builder.tools.build_watershed`.
            We use ``subbasins_vector`` to assemble the basin boundary
            and ``crs`` as the boundary CRS for mask operations.
        mukey_raster: Optional path to an already-downloaded mukey
            GeoTIFF (e.g. from a prior run or a user-supplied
            SSURGO product). If ``None``, we fetch from Planetary
            Computer via :func:`fetch_mukey_raster`.
        cache_dir: Where to cache the fetched raster. If ``None``, a
            ``mukey.tif`` lands in ``watershed.workdir / 'rasters'``.
            Ignored when ``mukey_raster`` is supplied.
        settings: Runtime overrides.

    Returns:
        ``set[int]`` of unique mukeys present inside the watershed
        boundary — ready to pass to
        :func:`swatplus_builder.soil.gnatsgo.fetch_gnatsgo_profiles`.

    Raises:
        SwatBuilderInputError: subbasins shapefile can't be read.
        SwatBuilderExternalError / SwatBuilderPipelineError: propagated
            from :func:`fetch_mukey_raster` or
            :func:`extract_unique_mukeys`.
    """
    import geopandas as gpd
    from shapely.ops import unary_union

    # 1. Boundary = union of all subbasin polygons.
    try:
        gdf = gpd.read_file(watershed.subbasins_vector)
    except Exception as exc:
        raise SwatBuilderInputError(
            f"failed reading subbasins vector: {exc}",
            path=str(watershed.subbasins_vector),
        ) from exc
    if gdf.empty:
        raise SwatBuilderPipelineError(
            "subbasins vector is empty",
            path=str(watershed.subbasins_vector),
        )

    boundary = unary_union(list(gdf.geometry))
    boundary_crs = gdf.crs.to_string() if gdf.crs else watershed.crs

    # 2. Resolve (or fetch) the mukey raster.
    if mukey_raster is None:
        cache = (
            Path(cache_dir).expanduser().resolve()
            if cache_dir is not None
            else Path(watershed.workdir).expanduser().resolve() / "rasters"
        )
        cache.mkdir(parents=True, exist_ok=True)
        mukey_raster = fetch_mukey_raster(
            boundary,
            output_path=cache / "mukey.tif",
            boundary_crs=boundary_crs,
            settings=settings,
        )

    # 3. Extract uniques within the boundary for defense-in-depth even
    # if the raster is pre-clipped — a tight intersection never
    # introduces new mukeys, only removes spurious ones at tile
    # boundaries.
    return extract_unique_mukeys(
        mukey_raster, boundary=boundary, boundary_crs=boundary_crs
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _reproject_geom_to_raster(
    geom: BaseGeometry,
    *,
    src_crs: str | int | None,
    dst_crs: rasterio.crs.CRS | None,
) -> BaseGeometry:
    """Reproject ``geom`` from ``src_crs`` into ``dst_crs``.

    If either CRS is unknown we trust the caller. The fast path
    (CRSs equal) avoids any geometry allocation.
    """
    from shapely.geometry import shape

    if src_crs is None or dst_crs is None:
        return geom
    src = rasterio.crs.CRS.from_user_input(src_crs)
    if src == dst_crs:
        return geom
    try:
        projected = rasterio.warp.transform_geom(
            src, dst_crs, mapping(geom), precision=-1
        )
    except (rasterio.errors.CRSError, ValueError, Exception) as exc:
        # GDAL raises ``CPLE_AppDefinedError`` (a bare ``Exception``
        # subclass, not a typed rasterio error) when a reprojection
        # is mathematically invalid — typically a geometry far
        # outside the destination projection's zone of validity.
        # Surface this as a pipeline error so the caller can triage.
        raise SwatBuilderPipelineError(
            f"geometry reprojection {src.to_string()} → "
            f"{dst_crs.to_string() if hasattr(dst_crs, 'to_string') else dst_crs} "
            f"failed: {exc}",
            src_crs=str(src),
            dst_crs=str(dst_crs),
        ) from exc
    return shape(projected)


def _boundary_bbox_wgs84(
    boundary: BaseGeometry, boundary_crs: str | int
) -> tuple[float, float, float, float]:
    """Return the boundary's envelope as a WGS84 (minx, miny, maxx, maxy)."""
    src = rasterio.crs.CRS.from_user_input(boundary_crs)
    wgs84 = rasterio.crs.CRS.from_epsg(4326)
    if src == wgs84:
        minx, miny, maxx, maxy = boundary.bounds
    else:
        minx, miny, maxx, maxy = rasterio.warp.transform_bounds(
            src, wgs84, *boundary.bounds, densify_pts=21
        )
    return (float(minx), float(miny), float(maxx), float(maxy))
