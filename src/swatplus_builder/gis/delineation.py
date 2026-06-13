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
import shutil
import tempfile
import time
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

def check_topology_realism(
    stats: dict[str, float],
    *,
    expected_area_km2: float | None = None,
    usgs_id: str | None = None,
    min_area_ratio: float = 0.10,
    max_channels_per_subbasin: float = 50.0,
    max_terminals: int = 5,
    max_terminal_rate: float = 0.08,
) -> None:
    """Fail loud when delineation topology is physically implausible.

    Raises:
        SwatBuilderPipelineError: Any topology check fails.
    """
    n_sub = stats.get("n_subbasins", 0.0)
    n_cha = stats.get("n_channels", 0.0)
    n_ter = stats.get("n_terminals", 0.0)
    gen_area = stats.get("total_area_km2", 0.0)

    context: dict[str, object] = {
        "n_subbasins": int(n_sub),
        "n_channels": int(n_cha),
        "n_terminals": int(n_ter),
        "generated_area_km2": gen_area,
    }
    if usgs_id:
        context["usgs_id"] = usgs_id
    if expected_area_km2 is not None:
        context["expected_area_km2"] = expected_area_km2
        context["min_area_ratio"] = min_area_ratio

    # 1. Area ratio: generated watershed must be at least min_area_ratio of expected.
    if expected_area_km2 is not None and expected_area_km2 > 0:
        ratio = gen_area / expected_area_km2
        context["area_ratio"] = round(ratio, 6)
        if ratio < min_area_ratio:
            raise SwatBuilderPipelineError(
                f"Delineation area mismatch: generated {gen_area:.2f} km² is only "
                f"{ratio:.4%} of expected {expected_area_km2:.1f} km² "
                f"(threshold: {min_area_ratio:.0%}). "
                "Likely cause: outlet snap failure or DEM clip boundary mismatch. "
                "Try increasing snap_dist_m or lowering stream_threshold_cells.",
                **context,
            )

    # 2. Channel explosion: channels per subbasin must stay below threshold.
    if n_sub > 0:
        ratio_cha = n_cha / n_sub
        context["channels_per_subbasin"] = round(ratio_cha, 1)
        context["max_channels_per_subbasin"] = max_channels_per_subbasin
        if ratio_cha > max_channels_per_subbasin:
            raise SwatBuilderPipelineError(
                f"Channel explosion: {int(n_cha)} channels across {int(n_sub)} subbasin(s) "
                f"({ratio_cha:.0f} channels/subbasin, threshold: {max_channels_per_subbasin:.0f}). "
                "Likely cause: outlet snapped outside the intended drainage area, "
                "producing a degenerate near-zero watershed with a dense stream network. "
                "Try increasing snap_dist_m or adjusting stream_threshold_cells.",
                **context,
            )

    # 3. Terminal explosion: for large basins, DEM-boundary truncation creates legitimate
    #    boundary terminals. Use rate-based threshold: max(abs, n_sub * rate).
    #    For small basins (<= 60 subbasins) the absolute max_terminals floor applies.
    effective_max_terminals = max(max_terminals, int(n_sub * max_terminal_rate))
    context["max_terminals"] = effective_max_terminals
    context["max_terminal_rate"] = max_terminal_rate
    if int(n_ter) > effective_max_terminals:
        raise SwatBuilderPipelineError(
            f"Multiple routing terminals: {int(n_ter)} terminals detected "
            f"(threshold: {effective_max_terminals} = max({max_terminals}, "
            f"{int(n_sub)}×{max_terminal_rate:.0%})). "
            "Likely cause: disconnected subgraphs from a fragmented delineation. "
            "Try increasing snap_dist_m or using a coarser stream_threshold_cells.",
            **context,
        )


def delineate(
    dem_path: Path | str,
    outlet: Outlet | tuple[float, float],
    workdir: Path | str,
    *,
    stream_threshold_cells: int = 500,
    snap_dist_m: float = 500.0,
    expected_area_km2: float | None = None,
    min_area_ratio: float = 0.10,
    max_channels_per_subbasin: float = 50.0,
    max_terminals: int = 5,
    max_terminal_rate: float = 0.08,
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
        expected_area_km2:      NLDI or user-provided basin area in km². When supplied, the
                                gate raises if the delineated area is < ``min_area_ratio``
                                of this value.
        min_area_ratio:         Minimum fraction of ``expected_area_km2`` the delineated
                                watershed must cover. Default 0.10 (10%).
        max_channels_per_subbasin: Maximum channels-per-subbasin ratio before raising a
                                channel-explosion error. Default 50.
        max_terminals:          Absolute minimum maximum routing-graph terminals before raising.
                                For large basins the effective limit is
                                max(max_terminals, n_subbasins × max_terminal_rate).
                                Default 5.
        max_terminal_rate:      Fraction of subbasins allowed to be terminals. DEM-boundary-
                                truncated large basins legitimately have boundary terminals.
                                Default 0.08 (8%).
        settings:               Runtime overrides (backend, verbosity, …).

    Returns:
        :class:`WatershedResult` — paths to all raster/vector artifacts plus summary stats.

    Raises:
        SwatBuilderInputError:    DEM unreadable, outlet outside DEM extent, CRS invalid.
        SwatBuilderPipelineError: Delineation produced zero subbasins or topology check fails.
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
    _check_wbt_output(rc, "BreachDepressionsLeastCost", dem_cond)

    # ------------------------------------------------------------------
    # 3 & 4. D8 flow direction + accumulation
    # ------------------------------------------------------------------
    log.info("[3/10] D8 flow direction …")
    flow_dir = rasters / "d8_pointer.tif"
    rc = wbt.d8_pointer(str(dem_cond), str(flow_dir))
    _check_wbt_output(rc, "D8Pointer", flow_dir)

    log.info("[4/10] D8 flow accumulation …")
    flow_acc = rasters / "d8_flow_acc.tif"
    rc = wbt.d8_flow_accumulation(str(dem_cond), str(flow_acc), out_type="cells")
    _check_wbt_output(rc, "D8FlowAccumulation", flow_acc)

    # ------------------------------------------------------------------
    # 5. Extract streams
    # ------------------------------------------------------------------
    log.info("[5/10] Extracting streams (threshold=%d cells) …", stream_threshold_cells)
    streams_r = rasters / "streams.tif"
    rc = wbt.extract_streams(str(flow_acc), str(streams_r), stream_threshold_cells)
    _check_wbt_output(rc, "ExtractStreams", streams_r)

    # ------------------------------------------------------------------
    # 6. Stream link identifier (unique int per channel segment)
    # ------------------------------------------------------------------
    log.info("[6/10] Assigning stream link IDs …")
    stream_links = rasters / "stream_links.tif"
    rc = wbt.stream_link_identifier(str(flow_dir), str(streams_r), str(stream_links))
    _check_wbt_output(rc, "StreamLinkIdentifier", stream_links)

    # ------------------------------------------------------------------
    # 7. Subbasins (one subbasin per stream link, same IDs)
    # ------------------------------------------------------------------
    log.info("[7/10] Delineating subbasins …")
    subbasins_r = rasters / "subbasins.tif"
    rc = wbt.subbasins(str(flow_dir), str(streams_r), str(subbasins_r))
    _check_wbt_output(rc, "Subbasins", subbasins_r)

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

    # Scale snap radius for large basins: sqrt(area_km2)*30 m gives ~1730 m
    # for a 3340 km² basin vs the 500 m default — enough to reach the main stem.
    effective_snap_m = _adaptive_snap_dist(snap_dist_m, expected_area_km2)
    if effective_snap_m > snap_dist_m:
        log.info("       Adaptive snap: %.0f m (basin area %.1f km²)",
                 effective_snap_m, expected_area_km2)

    snapped_lon, snapped_lat, snap_diag = _snap_and_watershed(
        wbt, outlet, proj_crs,
        flow_dir, flow_acc, stream_links, subbasins_r,
        outlet_raw, outlet_snapped, watershed_r,
        effective_snap_m,
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
    graph = _prune_topology_to_valid_channels(graph, channels_gdf, subbasins_gdf)

    # Prune isolated fragments — single-gauge delineation must be one connected basin.
    _outlet_lid = _outlet_link_id(
        stream_links,
        snap_diag["outlet_snapped_x"],
        snap_diag["outlet_snapped_y"],
    )
    graph, _n_pruned_isolated, _n_pruned_comps = _prune_disconnected_components(
        graph, _outlet_lid
    )

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
        "n_routing_edges": float(graph.number_of_edges()),
        "n_terminals": float(sum(1 for n in graph.nodes if graph.out_degree(n) == 0)),
        "n_pruned_isolated_nodes": float(_n_pruned_isolated),
        "total_area_km2": round(total_area_km2, 3),
        "mean_slope_m_m": round(mean_slope, 5),
        "outlet_lon": snapped_lon,
        "outlet_lat": snapped_lat,
        "stream_threshold_cells": float(stream_threshold_cells),
        # Snap diagnostics (surfaced for audit/realism checks)
        "snap_dist_used_m": snap_diag["snap_radius_m"],
        "snap_dist_actual_m": snap_diag["snap_dist_actual_m"],
        "flow_acc_raw_km2": snap_diag["flow_acc_raw_km2"],
        "flow_acc_snapped_km2": snap_diag["flow_acc_snapped_km2"],
    }

    # Write snap diagnostic artifact — standalone JSON for traceability
    snap_artifact = workdir / "snap_diagnostic.json"
    snap_artifact_data: dict[str, object] = {
        "usgs_id": outlet.usgs_id if hasattr(outlet, "usgs_id") else None,
        "snap_strategy": "max_accumulation",
        "snap_radius_m": snap_diag["snap_radius_m"],
        "snap_dist_actual_m": snap_diag["snap_dist_actual_m"],
        "outlet_raw": {
            "lon": outlet.lon, "lat": outlet.lat,
            "x_proj": snap_diag["outlet_raw_x"],
            "y_proj": snap_diag["outlet_raw_y"],
            "flow_acc_cells": snap_diag["flow_acc_raw_cells"],
            "flow_acc_km2": snap_diag["flow_acc_raw_km2"],
        },
        "outlet_snapped": {
            "lon": snapped_lon, "lat": snapped_lat,
            "x_proj": snap_diag["outlet_snapped_x"],
            "y_proj": snap_diag["outlet_snapped_y"],
            "flow_acc_cells": snap_diag["flow_acc_snapped_cells"],
            "flow_acc_km2": snap_diag["flow_acc_snapped_km2"],
        },
        "dem_resolution_m": snap_diag["dem_resolution_m"],
        "expected_area_km2": expected_area_km2,
        "generated_area_km2": round(total_area_km2, 3),
    }
    snap_artifact.write_text(json.dumps(snap_artifact_data, indent=2), encoding="utf-8")

    log.info("=== Delineation complete ===")
    log.info("    Subbasins:      %d", int(stats["n_subbasins"]))
    log.info("    Channels:       %d", int(stats["n_channels"]))
    log.info("    Total area:     %.1f km²", stats["total_area_km2"])

    # Enforce package invariant: single-gauge request ⇒ exactly one routing terminal.
    # Isolated fragments were pruned above; if multiple terminals remain on the main
    # component the outlet snap failed to reach the main stem.
    _n_terminals = int(stats["n_terminals"])
    if _n_terminals != 1:
        _terminal_nodes = sorted(n for n in graph.nodes if graph.out_degree(n) == 0)
        raise SwatBuilderPipelineError(
            f"Single-terminal invariant violated: {_n_terminals} routing terminal(s) "
            f"remain after pruning {_n_pruned_isolated} isolated node(s) from "
            f"{_n_pruned_comps} disconnected component(s). "
            "A single-gauge delineation must drain to exactly one terminal. "
            "Likely cause: outlet snapped to a side-channel rather than the main stem, "
            "or stream_threshold_cells too low (fragmented network). "
            "Try increasing snap_dist_m or raising stream_threshold_cells.",
            n_terminals=_n_terminals,
            n_pruned_isolated_nodes=_n_pruned_isolated,
            terminal_nodes=_terminal_nodes[:10],
            outlet_lon=outlet.lon,
            outlet_lat=outlet.lat,
        )

    check_topology_realism(
        stats,
        expected_area_km2=expected_area_km2,
        usgs_id=outlet.usgs_id if hasattr(outlet, "usgs_id") else None,
        min_area_ratio=min_area_ratio,
        max_channels_per_subbasin=max_channels_per_subbasin,
        max_terminals=max_terminals,
        max_terminal_rate=max_terminal_rate,
    )

    # Warn when area coverage is partial (passes gate but may affect calibration).
    if expected_area_km2 and expected_area_km2 > 0:
        area_ratio = total_area_km2 / expected_area_km2
        if area_ratio < 0.90:
            log.warning(
                "TOPOLOGY WARNING: delineated area %.1f km² is %.0f%% of expected %.1f km². "
                "Likely cause: routing graph fragmentation from D8 cycle removal — some "
                "subbasins disconnected from the main outlet. Model will under-represent "
                "upstream inflow for the missing %.0f%%. Consider FillDepressions instead "
                "of BreachDepressionsLeastCost for low-gradient basins.",
                total_area_km2, area_ratio * 100, expected_area_km2,
                (1 - area_ratio) * 100,
            )

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
    writable_dir = _writable_whitebox_dir(Path(wbt.exe_path))
    if writable_dir is not None:
        wbt.set_whitebox_dir(str(writable_dir))
    # whitebox-python passes "-v=false" when verbose is disabled; the bundled
    # WhiteboxTools build can return success without writing raster outputs in
    # that mode. Keep the tool verbose and silence callers at the workflow
    # stream boundary when JSON output is required.
    wbt.verbose = True
    return wbt


def _check_wbt(return_code: int, tool_name: str) -> None:
    if return_code != 0:
        raise SwatBuilderExternalError(
            f"WhiteboxTools '{tool_name}' returned exit code {return_code}.",
            tool=tool_name,
            exit_code=return_code,
        )


def _check_wbt_output(return_code: int, tool_name: str, *outputs: Path) -> None:
    _check_wbt(return_code, tool_name)
    _wait_for_outputs(outputs)
    missing = [str(p) for p in outputs if not Path(p).exists()]
    if missing:
        raise SwatBuilderExternalError(
            f"WhiteboxTools '{tool_name}' did not create expected output.",
            tool=tool_name,
            missing_outputs=missing,
        )


def _wait_for_outputs(outputs: tuple[Path, ...], *, timeout_s: float = 5.0) -> None:
    """Allow slow/cloud-backed filesystems to publish WBT outputs."""
    if not outputs:
        return
    deadline = time.monotonic() + timeout_s
    while True:
        if all(Path(path).exists() for path in outputs):
            return
        if time.monotonic() >= deadline:
            return
        time.sleep(0.1)


def _writable_whitebox_dir(source_dir: Path) -> Path | None:
    binary = source_dir / "whitebox_tools"
    if not binary.exists():
        return None
    target = Path(tempfile.gettempdir()) / "swatplus_builder_whitebox"
    target.mkdir(parents=True, exist_ok=True)
    target_binary = target / "whitebox_tools"
    if not target_binary.exists() or target_binary.stat().st_size != binary.stat().st_size:
        shutil.copy2(binary, target_binary)
    target_binary.chmod(target_binary.stat().st_mode | 0o111)
    return target


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

def _adaptive_snap_dist(default_m: float, expected_area_km2: float | None) -> float:
    """Scale snap radius for large basins.

    For a ~3340 km² basin the main channel can be >700 m from the gauge
    point, well beyond the default 500 m.  sqrt(area_km2) * 30 gives
    ~1730 m for 03339000 and ~320 m for Marsh Creek (floored to default).
    """
    if expected_area_km2 and expected_area_km2 > 0:
        return max(default_m, math.sqrt(expected_area_km2) * 30.0)
    return default_m


def _snap_to_max_accumulation(
    flow_acc: Path,
    px: float,
    py: float,
    radius_m: float,
) -> tuple[float, float, float, float, float]:
    """Find the highest-accumulation cell within radius_m of (px, py).

    Returns (snapped_px, snapped_py, acc_raw_cells, acc_snapped_cells, dist_m).
    Falls back to (px, py) when no valid cells exist in the window.

    This is more robust than WBT SnapPourPoints for large / low-gradient
    basins where the nearest stream may be a tributary, not the main stem.
    The highest-accumulation cell within the radius is always the main stem.
    """
    with rasterio.open(flow_acc) as src:
        res_m = abs(src.res[0])
        radius_cells = int(math.ceil(radius_m / res_m))

        # Clamp outlet row/col to raster bounds
        row, col = src.index(px, py)
        row = max(0, min(src.height - 1, row))
        col = max(0, min(src.width  - 1, col))

        # Flow acc at the raw outlet pixel
        full = src.read(1)
        acc_raw = float(full[row, col])

        # Read the bounding-box window
        r0 = max(0, row - radius_cells)
        r1 = min(src.height, row + radius_cells + 1)
        c0 = max(0, col - radius_cells)
        c1 = min(src.width,  col + radius_cells + 1)

        from rasterio.windows import Window as _W
        win_data = src.read(1, window=_W(c0, r0, c1 - c0, r1 - r0)).astype(np.float64)

        # Mask nodata and cells outside the circular radius
        if src.nodata is not None:
            win_data = np.where(win_data == src.nodata, -1.0, win_data)
        rr = np.arange(r0, r1) - row
        cc = np.arange(c0, c1) - col
        dist_grid = np.sqrt(rr[:, None] ** 2 + cc[None, :] ** 2)
        win_data = np.where(dist_grid <= radius_cells, win_data, -1.0)

        if win_data.max() <= 0:
            return px, py, acc_raw, acc_raw, 0.0

        max_idx = np.unravel_index(int(np.argmax(win_data)), win_data.shape)
        snap_row = r0 + max_idx[0]
        snap_col = c0 + max_idx[1]
        acc_snapped = float(win_data[max_idx])

        snapped_px, snapped_py = src.xy(snap_row, snap_col)
        dist_m = math.sqrt((snapped_px - px) ** 2 + (snapped_py - py) ** 2)

        return float(snapped_px), float(snapped_py), acc_raw, acc_snapped, dist_m


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
) -> tuple[float, float, dict[str, float]]:
    """Snap outlet to highest-accumulation cell, delineate watershed.

    Returns (snapped_lon, snapped_lat, snap_diagnostic_dict).
    """
    assert outlet.lon is not None and outlet.lat is not None

    # Transform WGS84 → projected CRS
    transformer = Transformer.from_crs("EPSG:4326", proj_crs, always_xy=True)
    px, py = transformer.transform(outlet.lon, outlet.lat)

    # Validate outlet is within DEM extent
    with rasterio.open(flow_acc) as src:
        bounds = src.bounds
        res_m = abs(src.res[0])
        if not (bounds.left <= px <= bounds.right and bounds.bottom <= py <= bounds.top):
            raise SwatBuilderInputError(
                "Outlet is outside the DEM extent.",
                outlet_projected=(px, py),
                dem_bounds=(bounds.left, bounds.bottom, bounds.right, bounds.top),
            )

    # Snap to the highest-accumulation cell within snap_dist_m (main-stem robust)
    snapped_px, snapped_py, acc_raw, acc_snapped, snap_dist_actual = (
        _snap_to_max_accumulation(flow_acc, px, py, snap_dist_m)
    )

    log.info(
        "       Snap: raw acc=%.0f cells (%.2f km²), snapped acc=%.0f cells (%.2f km²), dist=%.0f m",
        acc_raw,   acc_raw   * res_m ** 2 / 1e6,
        acc_snapped, acc_snapped * res_m ** 2 / 1e6,
        snap_dist_actual,
    )

    snap_diag: dict[str, float] = {
        "snap_strategy": 0.0,          # 0 = max_accumulation
        "outlet_raw_x": px,
        "outlet_raw_y": py,
        "outlet_snapped_x": snapped_px,
        "outlet_snapped_y": snapped_py,
        "snap_radius_m": snap_dist_m,
        "snap_dist_actual_m": round(snap_dist_actual, 1),
        "flow_acc_raw_cells": acc_raw,
        "flow_acc_snapped_cells": acc_snapped,
        "flow_acc_raw_km2": round(acc_raw   * res_m ** 2 / 1e6, 4),
        "flow_acc_snapped_km2": round(acc_snapped * res_m ** 2 / 1e6, 2),
        "dem_resolution_m": round(res_m, 2),
    }

    # Write snapped outlet shapefile for WBT Watershed tool
    snapped_gdf = gpd.GeoDataFrame(
        {"id": [1]}, geometry=[Point(snapped_px, snapped_py)], crs=proj_crs
    )
    snapped_gdf.to_file(str(outlet_snapped), driver="ESRI Shapefile")

    # Also write raw outlet for provenance
    outlet_gdf = gpd.GeoDataFrame(
        {"id": [1]}, geometry=[Point(px, py)], crs=proj_crs
    )
    outlet_gdf.to_file(str(outlet_raw), driver="ESRI Shapefile")

    # Delineate watershed above snapped outlet
    rc = wbt.watershed(str(flow_dir), str(outlet_snapped), str(watershed_r))
    _check_wbt_output(rc, "Watershed", watershed_r)

    # Back-transform snapped point to WGS84
    inv_transformer = Transformer.from_crs(proj_crs, "EPSG:4326", always_xy=True)
    snapped_lon, snapped_lat = inv_transformer.transform(snapped_px, snapped_py)

    return float(snapped_lon), float(snapped_lat), snap_diag


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

def _remove_back_edges(G: nx.DiGraph) -> None:
    """Remove all back-edges from G in a single O(V+E) DFS coloring pass.

    Uses tri-color DFS (WHITE=unvisited, GRAY=in-stack, BLACK=done).
    A back-edge u→v exists when v is still GRAY (v is an ancestor of u in DFS).
    Removing it breaks the cycle while keeping forward/cross edges intact.
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[int, int] = {n: WHITE for n in G}
    back_edges: list[tuple[int, int]] = []

    # Iterative DFS to avoid Python recursion limit on large graphs.
    for start in G.nodes:
        if color[start] != WHITE:
            continue
        stack = [(start, iter(G.successors(start)))]
        color[start] = GRAY
        while stack:
            node, children = stack[-1]
            try:
                child = next(children)
                if color[child] == GRAY:
                    back_edges.append((node, child))
                elif color[child] == WHITE:
                    color[child] = GRAY
                    stack.append((child, iter(G.successors(child))))
            except StopIteration:
                color[node] = BLACK
                stack.pop()

    n_removed = 0
    for u, v in back_edges:
        if G.has_edge(u, v):
            G.remove_edge(u, v)
            n_removed += 1
    if n_removed:
        log.info("Removed %d back-edge(s) to make routing graph acyclic.", n_removed)


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

    # Validate DAG, remove back-edges in a single O(V+E) coloring DFS.
    # The prior iterative approach (find_cycle + remove one edge, repeat) is
    # O(k × (V+E)) and hangs for large basins with many cycles.
    if not nx.is_directed_acyclic_graph(G):
        log.warning("Routing graph has cycles — removing back-edges.")
        _remove_back_edges(G)

    log.info(
        "Routing graph: %d nodes, %d edges, %d terminal",
        G.number_of_nodes(), G.number_of_edges(),
        sum(1 for n in G.nodes if G.out_degree(n) == 0),
    )
    return G


def _prune_topology_to_valid_channels(
    graph: nx.DiGraph,
    channels_gdf: gpd.GeoDataFrame,
    subbasins_gdf: gpd.GeoDataFrame,
) -> nx.DiGraph:
    """Keep routing graph nodes that can be emitted as SWAT+ channels.

    Raster/vector joins can produce a stream-link node whose channel centroid
    falls outside every surviving subbasin polygon. Such a node cannot be
    emitted into ``gis_channels``/``chandeg.con``. Keeping it in GraphML makes
    downstream terminal diagnostics report graph terminals that the SWAT+
    channel table can never contain.
    """
    if graph.number_of_nodes() == 0 or channels_gdf.empty:
        return graph

    sub_ids = {
        sid
        for sid in (_positive_int(getattr(row, "sub_id", None)) for row in subbasins_gdf.itertuples())
        if sid is not None
    }
    valid_link_ids: set[int] = set()
    for row in channels_gdf.itertuples():
        link_id = _positive_int(getattr(row, "link_id", None))
        if link_id is None:
            continue
        sub_id = _positive_int(getattr(row, "sub_id", None))
        if sub_id in sub_ids or link_id in sub_ids or (sub_id is None and len(sub_ids) == 1):
            valid_link_ids.add(link_id)

    if not valid_link_ids:
        return graph.copy()

    pruned = graph.copy()
    removed: list[int] = []
    for node in list(pruned.nodes):
        node_id = _positive_int(node)
        if node_id is None or node_id in valid_link_ids:
            continue
        preds = list(pruned.predecessors(node))
        succs = list(pruned.successors(node))
        for pred in preds:
            for succ in succs:
                if pred != succ:
                    pruned.add_edge(pred, succ)
        pruned.remove_node(node)
        removed.append(node_id)

    if removed:
        log.warning(
            "Pruned %d routing graph node(s) without valid channel/subbasin rows: %s",
            len(removed),
            ",".join(str(v) for v in sorted(removed)[:20]),
        )
    return pruned


def _positive_int(value: object) -> int | None:
    try:
        if isinstance(value, float) and math.isnan(value):
            return None
        out = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return out if out > 0 else None


def _outlet_link_id(stream_links: Path, px: float, py: float) -> int | None:
    """Return the stream link ID at the snapped outlet pixel.

    Returns None when the pixel falls outside the raster, is not on a
    stream (value ≤ 0), or the read fails for any reason.
    """
    try:
        with rasterio.open(stream_links) as src:
            row, col = src.index(px, py)
            row = max(0, min(src.height - 1, row))
            col = max(0, min(src.width - 1, col))
            val = int(src.read(1)[row, col])
            return val if val > 0 else None
    except Exception:
        return None


def _prune_disconnected_components(
    graph: nx.DiGraph,
    outlet_link_id: int | None,
) -> tuple[nx.DiGraph, int, int]:
    """Prune the routing graph to a single weakly-connected component.

    Single-gauge delineation should produce one connected drainage basin.
    Disconnected fragments are artefacts of raster/vector join mismatches
    (short stream segments that leak through the watershed mask boundary).

    Keeps the component containing ``outlet_link_id`` (the stream link at
    the snapped outlet pixel).  Falls back to the largest component when
    ``outlet_link_id`` is None or absent from the graph.

    Returns:
        (pruned_graph, n_nodes_pruned, n_components_removed)
    """
    if graph.number_of_nodes() == 0:
        return graph, 0, 0

    components = list(nx.weakly_connected_components(graph))
    if len(components) == 1:
        return graph, 0, 0

    main_component: set | None = None
    if outlet_link_id is not None and outlet_link_id in graph:
        for comp in components:
            if outlet_link_id in comp:
                main_component = comp
                break

    if main_component is None:
        main_component = max(components, key=len)

    pruned = graph.subgraph(main_component).copy()
    n_pruned = graph.number_of_nodes() - pruned.number_of_nodes()
    n_removed_comps = len(components) - 1

    if n_pruned > 0:
        anchor = (
            f"outlet link {outlet_link_id}"
            if outlet_link_id is not None
            else "largest component"
        )
        log.warning(
            "Pruned %d isolated routing node(s) from %d disconnected component(s) "
            "(kept %d-node component anchored to %s).",
            n_pruned, n_removed_comps, pruned.number_of_nodes(), anchor,
        )

    return pruned, n_pruned, n_removed_comps


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
