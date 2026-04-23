"""DEM → subbasins + channels + routing topology via WhiteboxTools.

Pipeline (in order)
-------------------
1.  Ensure projected CRS             — reproject geographic DEMs to UTM or user CRS
2.  BreachDepressionsLeastCost       — hydrologically condition the DEM
3.  D8Pointer                        — single-direction flow direction raster
4.  D8FlowAccumulation               — upstream contributing cells per pixel
5.  ExtractStreams                   — boolean stream raster (threshold in cells)
6.  StreamLinkIdentifier             — unique integer ID per channel segment
7.  Subbasins                        — subbasin raster matching stream link IDs
8.  Snap outlet → stream             — reproject and snap lon/lat to stream pixel
9.  Watershed                        — clip to drainage area above outlet
10. Polygonize subbasins             — GeoDataFrame via rasterio.features.shapes
11. Vectorize channels               — via wbt.raster_streams_to_vector
12. Build topology graph             — networkx DiGraph (upstream→downstream)
13. Attribute channels               — length, slope, width/depth (SWAT regressions)
14. Save manifest                    — WatershedResult JSON + GraphML

All intermediate rasters land in ``<workdir>/rasters/``.
Final vector products land in ``<workdir>/shapes/``.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

import geopandas as gpd
import networkx as nx
import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.crs import CRS
from rasterio.features import shapes as rasterio_shapes
from rasterio.warp import Resampling, calculate_default_transform, reproject
from shapely.geometry import Point, mapping, shape
from shapely.ops import unary_union

from ..config import DEFAULT_SETTINGS, Settings
from ..errors import SwatBuilderExternalError, SwatBuilderInputError, SwatBuilderPipelineError
from ..types import Outlet, WatershedResult

log = logging.getLogger(__name__)

# WBT D8 pointer encoding → (row_offset, col_offset)
_D8_OFFSETS: dict[int, tuple[int, int]] = {
    1: (0, 1),     # E
    2: (-1, 1),    # NE
    4: (-1, 0),    # N
    8: (-1, -1),   # NW
    16: (0, -1),   # W
    32: (1, -1),   # SW
    64: (1, 0),    # S
    128: (1, 1),   # SE
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def delineate(
    dem_path: Path | str,
    outlet: Outlet | tuple[float, float],
    workdir: Path | str,
    *,
    stream_threshold_cells: int = 500,
    snap_dist_m: float = 500.0,
    settings: Settings = DEFAULT_SETTINGS,
) -> WatershedResult:
    """Delineate subbasins and channels from a DEM and a pour point.

    Args:
        dem_path:               GeoTIFF DEM. Any CRS; reprojected internally if geographic.
        outlet:                 ``(lon, lat)`` in WGS84 or an :class:`~swatplus_builder.types.Outlet`.
                                For USGS gauges, set ``Outlet(usgs_id="01547700")`` and call
                                :func:`swatplus_builder.gis.delineation.resolve_usgs_outlet` first.
        workdir:                Output directory; created if missing. All artifacts land here.
        stream_threshold_cells: Minimum flow-accumulation (cells) to define a stream.
                                Lower → denser network; higher → fewer, longer channels.
                                Typical range: 100 (small basin, fine DEM) – 5000 (large basin).
        snap_dist_m:            Outlet snap radius in metres. The outlet point is moved to the
                                nearest high-accumulation cell within this radius.
        settings:               Runtime overrides (backend, verbosity, …).

    Returns:
        :class:`WatershedResult` — paths to all raster/vector artifacts plus summary stats.

    Raises:
        SwatBuilderInputError:    DEM unreadable, outlet outside DEM extent, CRS invalid.
        SwatBuilderPipelineError: Delineation produced zero subbasins.
        SwatBuilderExternalError: WhiteboxTools binary missing or returned non-zero.
    """
    # Normalise inputs
    dem_path = Path(dem_path).resolve()
    workdir = Path(workdir).resolve()
    if isinstance(outlet, tuple):
        outlet = Outlet(lon=outlet[0], lat=outlet[1])

    if outlet.lon is None or outlet.lat is None:
        raise SwatBuilderInputError(
            "outlet must have lon/lat. For USGS gauges call resolve_usgs_outlet() first.",
            outlet=outlet.model_dump(),
        )

    if not dem_path.exists():
        raise SwatBuilderInputError("DEM file not found.", dem_path=str(dem_path))

    # Prepare directories
    rasters = workdir / "rasters"
    shapes_dir = workdir / "shapes"
    rasters.mkdir(parents=True, exist_ok=True)
    shapes_dir.mkdir(parents=True, exist_ok=True)

    log.info("=== swatplus-builder: watershed delineation ===")
    log.info("DEM:     %s", dem_path)
    log.info("Outlet:  lon=%.4f  lat=%.4f", outlet.lon, outlet.lat)
    log.info("Workdir: %s", workdir)

    wbt = _init_wbt(settings)

    # ------------------------------------------------------------------
    # 1. Ensure projected CRS
    # ------------------------------------------------------------------
    log.info("[1/10] Ensuring projected CRS …")
    dem_proj, proj_crs = _ensure_projected_dem(dem_path, rasters, settings)
    log.info("       CRS: %s", proj_crs)

    # ------------------------------------------------------------------
    # 2. Breach/fill depressions (hydrological conditioning)
    # ------------------------------------------------------------------
    log.info("[2/10] Conditioning DEM (BreachDepressionsLeastCost) …")
    dem_cond = rasters / "dem_conditioned.tif"
    rc = wbt.breach_depressions_least_cost(
        str(dem_proj), str(dem_cond), dist=5, fill=True
    )
    _check_wbt(rc, "BreachDepressionsLeastCost")

    # ------------------------------------------------------------------
    # 3 & 4. D8 flow direction + accumulation
    # ------------------------------------------------------------------
    log.info("[3/10] D8 flow direction …")
    flow_dir = rasters / "d8_pointer.tif"
    rc = wbt.d8_pointer(str(dem_cond), str(flow_dir))
    _check_wbt(rc, "D8Pointer")

    log.info("[4/10] D8 flow accumulation …")
    flow_acc = rasters / "d8_flow_acc.tif"
    rc = wbt.d8_flow_accumulation(str(dem_cond), str(flow_acc), out_type="cells")
    _check_wbt(rc, "D8FlowAccumulation")

    # ------------------------------------------------------------------
    # 5. Extract streams
    # ------------------------------------------------------------------
    log.info("[5/10] Extracting streams (threshold=%d cells) …", stream_threshold_cells)
    streams_r = rasters / "streams.tif"
    rc = wbt.extract_streams(str(flow_acc), str(streams_r), stream_threshold_cells)
    _check_wbt(rc, "ExtractStreams")

    # ------------------------------------------------------------------
    # 6. Stream link identifier (unique int per channel segment)
    # ------------------------------------------------------------------
    log.info("[6/10] Assigning stream link IDs …")
    stream_links = rasters / "stream_links.tif"
    rc = wbt.stream_link_identifier(str(flow_dir), str(streams_r), str(stream_links))
    _check_wbt(rc, "StreamLinkIdentifier")

    # ------------------------------------------------------------------
    # 7. Subbasins (one subbasin per stream link, same IDs)
    # ------------------------------------------------------------------
    log.info("[7/10] Delineating subbasins …")
    subbasins_r = rasters / "subbasins.tif"
    rc = wbt.subbasins(str(flow_dir), str(streams_r), str(subbasins_r))
    _check_wbt(rc, "Subbasins")

    # ------------------------------------------------------------------
    # 8. Snap outlet to stream + watershed clip
    # ------------------------------------------------------------------
    log.info("[8/10] Snapping outlet and clipping to drainage area …")
    # WhiteboxTools (2.4.x) only reads ESRI Shapefile vectors.  GPKG input
    # crashes the tool with a generic ``Unrecognized ShapeType`` panic.  We
    # produce and consume ``.shp`` files here; higher-level GIS artifacts
    # (subbasins, channels) still use GPKG.
    outlet_raw = shapes_dir / "outlet_raw.shp"
    outlet_snapped = shapes_dir / "outlet_snapped.shp"
    watershed_r = rasters / "watershed.tif"

    snapped_lon, snapped_lat = _snap_and_watershed(
        wbt, outlet, proj_crs,
        flow_dir, flow_acc, stream_links, subbasins_r,
        outlet_raw, outlet_snapped, watershed_r,
        snap_dist_m,
    )

    # ------------------------------------------------------------------
    # 9. Polygonize subbasins (masked to watershed)
    # ------------------------------------------------------------------
    log.info("[9/10] Vectorising subbasins and channels …")
    subbasins_gdf = _polygonize_subbasins(subbasins_r, watershed_r, proj_crs)

    if len(subbasins_gdf) == 0:
        raise SwatBuilderPipelineError(
            "Delineation produced zero subbasins. "
            "Try lowering stream_threshold_cells or increasing snap_dist_m.",
            outlet=outlet.model_dump(),
            stream_threshold_cells=stream_threshold_cells,
        )

    log.info("       %d subbasins", len(subbasins_gdf))

    # Vectorise channels
    channels_gdf = _vectorize_channels(
        wbt, stream_links, flow_dir, watershed_r, subbasins_gdf, proj_crs, shapes_dir
    )
    log.info("       %d channel segments", len(channels_gdf))

    # ------------------------------------------------------------------
    # 10. Routing topology + channel attributes
    # ------------------------------------------------------------------
    log.info("[10/10] Building routing graph and channel attributes …")
    graph = _build_topology(stream_links, watershed_r, channels_gdf)
    _attribute_channels(channels_gdf, subbasins_gdf, dem_cond, flow_acc)

    # ------------------------------------------------------------------
    # Save vectors + graph
    # ------------------------------------------------------------------
    sub_path = shapes_dir / "subbasins.gpkg"
    cha_path = shapes_dir / "channels.gpkg"
    out_path = shapes_dir / "outlets.gpkg"
    graph_path = workdir / "routing_graph.graphml"

    subbasins_gdf.to_file(sub_path, driver="GPKG")
    channels_gdf.to_file(cha_path, driver="GPKG")

    # Snapped outlet vector
    outlet_gdf = gpd.GeoDataFrame(
        {"outlet_id": [1], "lon": [snapped_lon], "lat": [snapped_lat]},
        geometry=[Point(snapped_lon, snapped_lat)],
        crs="EPSG:4326",
    ).to_crs(proj_crs)
    outlet_gdf.to_file(out_path, driver="GPKG")

    nx.write_graphml(graph, graph_path)

    # ------------------------------------------------------------------
    # Summary stats
    # ------------------------------------------------------------------
    total_area_km2 = float(subbasins_gdf.to_crs(proj_crs).area.sum() / 1e6)
    mean_slope = float(subbasins_gdf["mean_slope_m_m"].mean()) if "mean_slope_m_m" in subbasins_gdf else 0.0

    stats: dict[str, float] = {
        "n_subbasins": float(len(subbasins_gdf)),
        "n_channels": float(len(channels_gdf)),
        "total_area_km2": round(total_area_km2, 3),
        "mean_slope_m_m": round(mean_slope, 5),
        "outlet_lon": snapped_lon,
        "outlet_lat": snapped_lat,
        "stream_threshold_cells": float(stream_threshold_cells),
    }

    log.info("=== Delineation complete ===")
    log.info("    Subbasins:      %d", int(stats["n_subbasins"]))
    log.info("    Channels:       %d", int(stats["n_channels"]))
    log.info("    Total area:     %.1f km²", stats["total_area_km2"])

    result = WatershedResult(
        workdir=workdir,
        crs=proj_crs,
        dem_conditioned=dem_cond,
        flow_dir=flow_dir,
        flow_acc=flow_acc,
        streams_raster=streams_r,
        subbasins_vector=sub_path,
        channels_vector=cha_path,
        outlets_vector=out_path,
        routing_graph=graph_path,
        stats=stats,
    )

    # Persist manifest for resumption
    manifest = workdir / "watershed_result.json"
    manifest.write_text(result.model_dump_json(indent=2), encoding="utf-8")

    return result


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def load_result(workdir: Path | str) -> WatershedResult:
    """Re-load a WatershedResult from a workdir persisted by a previous run."""
    p = Path(workdir) / "watershed_result.json"
    if not p.exists():
        raise SwatBuilderInputError(
            "No watershed_result.json found. Run delineate() first.", workdir=str(workdir)
        )
    return WatershedResult.model_validate_json(p.read_text(encoding="utf-8"))


def resolve_usgs_outlet(usgs_id: str) -> Outlet:
    """Fetch the outlet lon/lat for a USGS gauge via the NLDI API.

    Requires network access and the ``pynhd`` package (``pip install pynhd``).
    """
    try:
        from pynhd import NLDI  # type: ignore[import]
    except ImportError as exc:
        raise SwatBuilderExternalError(
            "pynhd is required for USGS gauge lookup. "
            "Install with: pip install 'swatplus-builder[hyriver]'",
        ) from exc

    nldi = NLDI()
    # get_basins returns a GeoDataFrame; centroid of the outlet point
    basins = nldi.get_basins(usgs_id)
    if basins.empty:
        raise SwatBuilderInputError("NLDI returned no basin for gauge.", usgs_id=usgs_id)
    # NLDI also has get_features — use the outlet point
    sites = nldi.getfeature_byid("nwissite", f"USGS-{usgs_id}")
    geom = sites.geometry.iloc[0]
    return Outlet(lon=float(geom.x), lat=float(geom.y), usgs_id=usgs_id)


# ---------------------------------------------------------------------------
# Private helpers — WhiteboxTools
# ---------------------------------------------------------------------------

def _init_wbt(settings: Settings) -> Any:
    """Lazily import and configure WhiteboxTools."""
    try:
        import whitebox  # type: ignore[import]
    except ImportError as exc:
        raise SwatBuilderExternalError(
            "whitebox-python is not installed. "
            "Install with: pip install 'swatplus-builder[gis]'",
        ) from exc

    wbt = whitebox.WhiteboxTools()
    wbt.verbose = settings.whitebox_verbose
    return wbt


def _check_wbt(return_code: int, tool_name: str) -> None:
    if return_code != 0:
        raise SwatBuilderExternalError(
            f"WhiteboxTools '{tool_name}' returned exit code {return_code}.",
            tool=tool_name,
            exit_code=return_code,
        )


def _ensure_projected_dem(
    dem_path: Path,
    rasters_dir: Path,
    settings: Settings,
) -> tuple[Path, str]:
    """Return (path_to_projected_dem, epsg_string).

    If the DEM is already in a projected CRS (units in metres) it is returned
    unchanged. Geographic DEMs (EPSG:4326 etc.) are reprojected to UTM.
    """
    with rasterio.open(dem_path) as src:
        crs = src.crs
        if crs is None:
            raise SwatBuilderInputError("DEM has no CRS.", dem_path=str(dem_path))
        if not crs.is_geographic:
            epsg = crs.to_epsg()
            return dem_path, f"EPSG:{epsg}" if epsg else crs.to_string()

        # Geographic → reproject to UTM
        lon = (src.bounds.left + src.bounds.right) / 2
        lat = (src.bounds.bottom + src.bounds.top) / 2

    utm_epsg = _utm_epsg(lon, lat)
    log.info("       DEM is geographic; reprojecting to %s …", utm_epsg)

    out_path = rasters_dir / "dem_projected.tif"
    _reproject_raster(dem_path, out_path, utm_epsg)
    return out_path, utm_epsg


def _utm_epsg(lon: float, lat: float) -> str:
    """Return the UTM zone EPSG string for a given lon/lat."""
    zone = int((lon + 180) / 6) + 1
    if lat >= 0:
        return f"EPSG:{32600 + zone}"
    return f"EPSG:{32700 + zone}"


def _reproject_raster(src_path: Path, dst_path: Path, dst_epsg: str) -> None:
    dst_crs = CRS.from_epsg(int(dst_epsg.split(":")[1]))
    with rasterio.open(src_path) as src:
        transform, width, height = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds
        )
        kwargs = src.meta.copy()
        kwargs.update({"crs": dst_crs, "transform": transform, "width": width, "height": height})
        with rasterio.open(dst_path, "w", **kwargs) as dst:
            for band in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, band),
                    destination=rasterio.band(dst, band),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=dst_crs,
                    resampling=Resampling.bilinear,
                )


# ---------------------------------------------------------------------------
# Private helpers — outlet snapping + watershed
# ---------------------------------------------------------------------------

def _snap_and_watershed(
    wbt: Any,
    outlet: Outlet,
    proj_crs: str,
    flow_dir: Path,
    flow_acc: Path,
    stream_links: Path,
    subbasins_r: Path,
    outlet_raw: Path,
    outlet_snapped: Path,
    watershed_r: Path,
    snap_dist_m: float,
) -> tuple[float, float]:
    """Snap outlet to nearest stream, delineate watershed. Returns snapped (lon, lat)."""
    assert outlet.lon is not None and outlet.lat is not None

    # Transform WGS84 → projected CRS
    transformer = Transformer.from_crs("EPSG:4326", proj_crs, always_xy=True)
    px, py = transformer.transform(outlet.lon, outlet.lat)

    # Validate outlet is within DEM extent
    with rasterio.open(flow_acc) as src:
        bounds = src.bounds
        if not (bounds.left <= px <= bounds.right and bounds.bottom <= py <= bounds.top):
            raise SwatBuilderInputError(
                "Outlet is outside the DEM extent.",
                outlet_projected=(px, py),
                dem_bounds=(bounds.left, bounds.bottom, bounds.right, bounds.top),
            )

    # Write raw outlet shapefile (WBT needs a vector file)
    outlet_gdf = gpd.GeoDataFrame(
        {"id": [1]}, geometry=[Point(px, py)], crs=proj_crs
    )
    outlet_gdf.to_file(str(outlet_raw), driver="ESRI Shapefile")

    # Snap to nearest stream cell
    rc = wbt.snap_pour_points(
        str(outlet_raw), str(flow_acc), str(outlet_snapped), snap_dist_m
    )
    _check_wbt(rc, "SnapPourPoints")

    # Read back snapped location.  WBT writes .shp without .prj.
    snapped_gdf = gpd.read_file(str(outlet_snapped))
    if snapped_gdf.crs is None:
        snapped_gdf = snapped_gdf.set_crs(proj_crs, allow_override=True)
    snapped_proj = snapped_gdf.geometry.iloc[0]

    # Delineate watershed above snapped outlet
    rc = wbt.watershed(str(flow_dir), str(outlet_snapped), str(watershed_r))
    _check_wbt(rc, "Watershed")

    # Back-transform snapped point to WGS84
    inv_transformer = Transformer.from_crs(proj_crs, "EPSG:4326", always_xy=True)
    snapped_lon, snapped_lat = inv_transformer.transform(snapped_proj.x, snapped_proj.y)

    return float(snapped_lon), float(snapped_lat)


# ---------------------------------------------------------------------------
# Private helpers — vectorisation
# ---------------------------------------------------------------------------

def _polygonize_subbasins(
    subbasins_r: Path,
    watershed_r: Path,
    proj_crs: str,
) -> gpd.GeoDataFrame:
    """Convert subbasin raster to a GeoDataFrame, one row per subbasin.

    Only pixels that fall within the watershed mask are included.
    """
    with rasterio.open(subbasins_r) as src:
        sub_arr = src.read(1).astype(np.int32)
        transform = src.transform
        nodata = src.nodata or 0

    with rasterio.open(watershed_r) as wsrc:
        ws_arr = wsrc.read(1)
        ws_nodata = wsrc.nodata

    # Build watershed mask
    if ws_nodata is not None:
        ws_mask = ws_arr != ws_nodata
    else:
        ws_mask = ws_arr > 0

    # Mask subbasins to watershed
    sub_masked = np.where(ws_mask, sub_arr, 0).astype(np.int32)

    # Polygonize: each unique non-zero value → polygon
    polys = []
    for geom_dict, value in rasterio_shapes(sub_masked, mask=(sub_masked > 0), transform=transform):
        polys.append({"sub_id": int(value), "geometry": shape(geom_dict)})

    if not polys:
        return gpd.GeoDataFrame(columns=["sub_id", "geometry"], crs=proj_crs)

    gdf = gpd.GeoDataFrame(polys, crs=proj_crs)

    # Dissolve duplicate IDs (rasterio may return multiple polygons for same value)
    gdf = gdf.dissolve(by="sub_id", as_index=False)
    gdf["area_ha"] = (gdf.geometry.area / 1e4).round(4)
    gdf["area_km2"] = (gdf.geometry.area / 1e6).round(6)

    return gdf.reset_index(drop=True)


def _vectorize_channels(
    wbt: Any,
    stream_links: Path,
    flow_dir: Path,
    watershed_r: Path,
    subbasins_gdf: gpd.GeoDataFrame,
    proj_crs: str,
    shapes_dir: Path,
) -> gpd.GeoDataFrame:
    """Convert stream links to a LineString GeoDataFrame with basic attributes."""
    raw_shp = shapes_dir / "channels_raw.shp"
    rc = wbt.raster_streams_to_vector(str(stream_links), str(flow_dir), str(raw_shp))
    _check_wbt(rc, "RasterStreamsToVector")

    # WhiteboxTools writes a Shapefile without a .prj sidecar, so the
    # GeoDataFrame comes back with a naive CRS.  The coordinates ARE in the
    # projected CRS of the input rasters — we just need to attach that CRS
    # rather than attempt a transform.
    channels_raw = gpd.read_file(str(raw_shp))
    if channels_raw.crs is None:
        channels_raw = channels_raw.set_crs(proj_crs, allow_override=True)
    channels = channels_raw.to_crs(proj_crs)
    channels = channels.rename(columns={"STRM_VAL": "link_id"})
    channels["link_id"] = channels["link_id"].astype(int)
    channels["length_m"] = channels.geometry.length.round(2)

    # Spatial join: which subbasin does each channel fall in?
    channels["centroid"] = channels.geometry.centroid
    cha_centroids = gpd.GeoDataFrame(channels.drop(columns=["geometry"]), geometry="centroid", crs=proj_crs)
    joined = gpd.sjoin(cha_centroids, subbasins_gdf[["sub_id", "geometry"]], how="left", predicate="within")
    channels["sub_id"] = joined["sub_id"].values

    return channels.drop(columns=["centroid"], errors="ignore").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Private helpers — topology
# ---------------------------------------------------------------------------

def _build_topology(stream_links: Path, watershed_r: Path, channels_gdf=None) -> nx.DiGraph:
    """Build a DiGraph of channel links.

    Nodes are stream link IDs (ints). An edge (A -> B) means A drains into B.
    The unique outlet node has no successors.

    Strategy
    --------
    1. D8 raster pixel-level adjacency (fast, but misses short segments).
    2. Spatial endpoint snapping from channels_gdf: downstream end of A
       near upstream start of B catches connections that D8 misses.
    """
    with rasterio.open(stream_links) as src:
        links = src.read(1).astype(np.int32)

    d8_path = stream_links.parent / "d8_pointer.tif"
    with rasterio.open(d8_path) as src:
        d8 = src.read(1).astype(np.int32)

    unique_ids = np.unique(links)
    unique_ids = unique_ids[unique_ids > 0]

    G: nx.DiGraph = nx.DiGraph()
    G.add_nodes_from(int(uid) for uid in unique_ids)

    with rasterio.open(watershed_r) as src:
        ws = src.read(1)
        ws_nodata = src.nodata
    ws_mask = (ws != ws_nodata) if ws_nodata is not None else (ws > 0)

    rows, cols = np.where((links > 0) & ws_mask)
    nrows, ncols = links.shape
    edge_set: set[tuple[int, int]] = set()

    for r, c in zip(rows, cols):
        link_id = int(links[r, c])
        d8_val = int(d8[r, c])
        offset = _D8_OFFSETS.get(d8_val)
        if offset is None:
            continue
        nr, nc = r + offset[0], c + offset[1]
        if 0 <= nr < nrows and 0 <= nc < ncols:
            neighbor_id = int(links[nr, nc])
            if neighbor_id > 0 and neighbor_id != link_id:
                edge = (link_id, neighbor_id)
                if edge not in edge_set:
                    edge_set.add(edge)
                    G.add_edge(link_id, neighbor_id)

    # --- Augment with spatial endpoint snapping ---
    # The D8 approach misses connections where short channel segments don't
    # share raster pixel borders.  The downstream end of each channel
    # (last coordinate) should be very close to another channel's upstream
    # start (first coordinate).
    if channels_gdf is not None:
        try:
            from shapely.geometry import Point as _Point

            if "link_id" in channels_gdf.columns:
                ds_pts: dict[int, _Point] = {}
                us_pts: dict[int, _Point] = {}
                for _, row in channels_gdf.iterrows():
                    lid = int(row["link_id"])
                    coords = list(row.geometry.coords)
                    if len(coords) >= 2:
                        us_pts[lid] = _Point(coords[0])
                        ds_pts[lid] = _Point(coords[-1])

                snap_tol = 150.0  # metres
                link_ids_list = list(ds_pts.keys())
                for a in link_ids_list:
                    best_dist = float("inf")
                    best_b: int | None = None
                    for b in link_ids_list:
                        if b == a or b not in us_pts:
                            continue
                        d = ds_pts[a].distance(us_pts[b])
                        if d < snap_tol and d < best_dist:
                            best_dist = d
                            best_b = b
                    if best_b is not None:
                        edge = (a, best_b)
                        if edge not in edge_set:
                            edge_set.add(edge)
                            G.add_edge(a, best_b)
                            log.debug("topology snap: %d -> %d  (%.1f m)", a, best_b, best_dist)
        except Exception as exc:
            log.warning("Spatial topology augmentation failed: %s", exc)
    else:
        # Fallback: try reading from disk
        shapes_dir = stream_links.parent.parent / "shapes"
        channels_gpkg = shapes_dir / "channels.gpkg"
        if channels_gpkg.is_file():
            try:
                import geopandas as gpd
                _augment_topology_from_gpkg(G, edge_set, gpd.read_file(channels_gpkg))
            except Exception as exc:
                log.warning("Spatial topology (disk fallback) failed: %s", exc)

    # Validate DAG, remove back-edges if needed
    if not nx.is_directed_acyclic_graph(G):
        log.warning("Routing graph has cycles — removing back-edges.")
        while not nx.is_directed_acyclic_graph(G):
            try:
                cycle = nx.find_cycle(G, orientation="original")
                G.remove_edge(cycle[-1][0], cycle[-1][1])
            except nx.NetworkXNoCycle:
                break

    log.info(
        "Routing graph: %d nodes, %d edges, %d terminal",
        G.number_of_nodes(), G.number_of_edges(),
        sum(1 for n in G.nodes if G.out_degree(n) == 0),
    )
    return G



# ---------------------------------------------------------------------------
# Private helpers — channel attributes
# ---------------------------------------------------------------------------

def _attribute_channels(
    channels: gpd.GeoDataFrame,
    subbasins: gpd.GeoDataFrame,
    dem_cond: Path,
    flow_acc: Path,
) -> None:
    """Compute per-channel slope, width, depth in place.

    Width/depth use SWAT+ empirical regressions:
        width  = 1.29 × area_km²^0.6
        depth  = 0.13 × area_km²^0.4

    Slope = (upstream elev − downstream elev) / channel length.
    """
    with rasterio.open(dem_cond) as dsrc:
        dem_arr = dsrc.read(1, masked=True)
        dem_transform = dsrc.transform

    with rasterio.open(flow_acc) as fsrc:
        acc_arr = fsrc.read(1, masked=True)
        acc_transform = fsrc.transform
        cell_area_m2 = abs(acc_transform.a * acc_transform.e)

    def _raster_value(arr: np.ma.MaskedArray, transform: Any, x: float, y: float) -> float:
        row, col = rasterio.transform.rowcol(transform, x, y)
        nrows, ncols = arr.shape
        if 0 <= row < nrows and 0 <= col < ncols and not arr.mask[row, col]:
            return float(arr[row, col])
        return float("nan")

    slopes, widths, depths, elev_mins, elev_maxs = [], [], [], [], []

    for _, row in channels.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            slopes.append(0.0)
            widths.append(1.0)
            depths.append(0.1)
            elev_mins.append(float("nan"))
            elev_maxs.append(float("nan"))
            continue

        # Start = upstream (first coord), end = downstream (last coord)
        coords = list(geom.coords)
        x_up, y_up = coords[0]
        x_dn, y_dn = coords[-1]

        elev_up = _raster_value(dem_arr, dem_transform, x_up, y_up)
        elev_dn = _raster_value(dem_arr, dem_transform, x_dn, y_dn)
        length_m = row.get("length_m", geom.length)

        slope = (elev_up - elev_dn) / max(length_m, 1.0) if not any(
            math.isnan(v) for v in [elev_up, elev_dn]
        ) else 0.001

        # Contributing area from flow accumulation at downstream end
        acc_cells = _raster_value(acc_arr, acc_transform, x_dn, y_dn)
        area_km2 = (acc_cells * cell_area_m2 / 1e6) if not math.isnan(acc_cells) else 1.0
        area_km2 = max(area_km2, 0.01)

        width = round(1.29 * area_km2 ** 0.6, 3)
        depth = round(0.13 * area_km2 ** 0.4, 3)

        slopes.append(max(slope, 0.0001))
        widths.append(width)
        depths.append(depth)
        elev_mins.append(min(elev_up, elev_dn) if not any(math.isnan(v) for v in [elev_up, elev_dn]) else float("nan"))
        elev_maxs.append(max(elev_up, elev_dn) if not any(math.isnan(v) for v in [elev_up, elev_dn]) else float("nan"))

    channels["slope_m_m"] = np.clip(slopes, 0.0001, 1.0)
    channels["width_m"] = widths
    channels["depth_m"] = depths
    channels["elev_min_m"] = elev_mins
    channels["elev_max_m"] = elev_maxs
