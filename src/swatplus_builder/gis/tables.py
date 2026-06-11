"""Stitch :class:`WatershedResult` + :class:`HRUResult` → :class:`GisTables`.

This module is the final "convert GIS artifacts into DB rows" step. It
has no rendering, no rasterization, no overlay work — all the heavy
lifting already happened in :mod:`gis.delineation` (subbasins,
channels, routing graph) and :mod:`gis.hru` (LSUs + HRUs in the catalog
JSON). Here we just read those outputs and produce the typed row lists
that :func:`swatplus_builder.db.writer.write_all` consumes.

Scope (Phase 2 MVP)
-------------------

What we emit:

* :class:`SubbasinRow` — one per subbasin. Derived from
  ``subbasins.gpkg`` for geometry / area, and from the one-LSU-per-
  subbasin assumption for slope / elevation (LSU row stats are
  authoritative because they were computed on the exact raster grid
  used for HRU overlay).
* :class:`ChannelRow` — one per row in ``channels.gpkg``. Attributes
  passed through 1-to-1; drainage area (``areac``) is filled from the
  parent subbasin's area because WBT's per-link accumulation isn't
  exposed on the current vector.
* :class:`LsuRow` / :class:`HruRow` — loaded from the HRU catalog via
  :func:`swatplus_builder.gis.hru.load_lsus_hrus`. No re-validation
  here; those rows are already pydantic-valid.
* :class:`AquiferRow` — one floodplain aquifer per subbasin
  (``category=1``). Same centroid / area / elevation as the LSU. SWAT+
  requires at least one aquifer per subbasin for the water balance
  to close.
* :class:`DeepAquiferRow` — one per subbasin, same geometry as the
  subbasin. Matches QSWATPlus's default ("all deep aquifer is
  regional, one per subbasin").
* :class:`PointRow` — exactly one outlet point (``ptype='O'``),
  located at the snapped outlet in ``outlets.gpkg``.
* :class:`RoutingRow` — a minimal-but-valid surface-water routing
  graph. For a watershed with ``N`` subbasins and ``N`` channels we
  emit, per HRU, per channel, per aquifer, per deep aquifer, the
  surface / total hydrograph routing rows needed for
  :func:`swatplus_builder.db.writer.validate_tables` to accept the
  DB and for ``import_gis`` in the vendored editor to expand it into
  the model tables:

  * ``HRU → CH`` (tot, 100%) — HRU surface runoff to its parent
    channel.
  * ``CH → CH`` (tot, 100%) — channel to the downstream channel in
    the routing graph; terminal channels point at ``sinkid=0,
    sinkcat='X'`` (the reserved watershed outlet).
  * ``AQU → CH`` (tot, 100%) — floodplain aquifer baseflow to its
    subbasin's channel.
  * ``DAQ → X`` (tot, 100%) — deep aquifer recharge leaves the
    watershed. For a single-DAQ-per-subbasin model this is the
    simplest closed balance.
  * ``PT → CH`` (tot, 100%) — the outlet point is attached to its
    host channel.

  Upslope LSUs, lake routing, irrigation diversions, and HRU →
  downslope-LSU splits are Phase 3 follow-ups.

Design notes
------------

* **Coordinate system.** The watershed is stored in the project's
  UTM projection; all SWAT+ DB rows use WGS84 lat/lon. We use a
  single :class:`pyproj.Transformer` to go from the subbasins /
  channels CRS → EPSG:4326 so we never mix projections.
* **Id reuse.** We reuse ``sub_id`` as the subbasin / LSU / aquifer /
  deep-aquifer id. This is safe because each of those categories
  is 1-to-1 with the subbasin in the MVP. Channels use their own
  ``link_id``. HRUs are globally 1-indexed across the watershed.
* **Deterministic ordering.** Row lists are sorted by id so the
  output of :func:`build_tables` is byte-identical for a given
  input (modulo floating-point rounding). Agents can diff two runs
  directly.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import geopandas as gpd
import networkx as nx
from pyproj import Transformer

from ..errors import SwatBuilderInputError
from ..types import (
    AquiferRow,
    ChannelRow,
    DeepAquiferRow,
    GisTables,
    HRUResult,
    HruRow,
    LsuRow,
    PointRow,
    RoutingRow,
    SubbasinRow,
    WatershedResult,
)
from .hru import load_lsus_hrus

log = logging.getLogger(__name__)

__all__ = ["build_tables"]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_tables(
    watershed: WatershedResult,
    hru_result: HRUResult,
    *,
    outlet_subbasin: int | None = None,
) -> GisTables:
    """Assemble the full :class:`GisTables` payload for ``db.writer.write_all``.

    Args:
        watershed: Output of :func:`swatplus_builder.gis.delineation.delineate`.
        hru_result: Output of :func:`swatplus_builder.gis.hru.create_hrus`.
        outlet_subbasin: Optional id of the subbasin that drains to
            the watershed outlet. If ``None``, inferred as the
            subbasin whose channel is terminal in the routing graph
            (the channel with no out-edges).

    Returns:
        A fully-populated :class:`GisTables` ready to pass to
        :func:`swatplus_builder.db.writer.write_all`.

    Raises:
        SwatBuilderInputError: a required GIS artifact (subbasins,
            channels, outlets, routing graph, or HRU catalog) is
            missing.
    """
    # --- Typed inputs ---
    lsu_rows, hru_rows = load_lsus_hrus(hru_result)

    subs_gdf = _read_vector(watershed.subbasins_vector, "subbasins_vector")
    chans_gdf = _read_vector(watershed.channels_vector, "channels_vector")
    outlets_gdf = _read_vector(watershed.outlets_vector, "outlets_vector")
    routing_graph = _load_routing_graph(watershed.routing_graph)

    # Shared WGS84 transformer.
    ref_crs = subs_gdf.crs if subs_gdf.crs is not None else watershed.crs
    to_wgs84 = Transformer.from_crs(ref_crs, "EPSG:4326", always_xy=True)

    # --- Build per-category row lists ---
    subbasins = _build_subbasin_rows(subs_gdf, lsu_rows, chans_gdf, to_wgs84)
    channels = _build_channel_rows(chans_gdf, subs_gdf, to_wgs84)

    aquifers = _build_aquifer_rows(subbasins)
    deep_aquifers = _build_deep_aquifer_rows(subbasins)

    # Terminal channel = no out-edge in the routing graph. We default
    # the outlet subbasin to that channel's parent subbasin.
    terminal_channel_ids = _terminal_channel_ids(routing_graph, chans_gdf)
    if outlet_subbasin is None:
        if terminal_channel_ids:
            first_terminal = sorted(terminal_channel_ids)[0]
            outlet_subbasin = _channel_parent_subbasin(chans_gdf, first_terminal)
        else:
            outlet_subbasin = subbasins[0].id
    valid_sub_ids = {s.id for s in subbasins}
    if outlet_subbasin not in valid_sub_ids:
        # Guard against clipped/degenerate delineations where inferred
        # outlet subbasin id does not exist in the surviving subbasin rows.
        outlet_subbasin = subbasins[0].id

    points = _build_point_rows(outlets_gdf, outlet_subbasin, to_wgs84)

    routing = _build_routing_rows(
        hru_rows=hru_rows,
        channels=channels,
        aquifers=aquifers,
        deep_aquifers=deep_aquifers,
        points=points,
        routing_graph=routing_graph,
        terminal_channel_ids=terminal_channel_ids,
    )

    return GisTables(
        subbasins=sorted(subbasins, key=lambda r: r.id),
        channels=sorted(channels, key=lambda r: r.id),
        lsus=sorted(lsu_rows, key=lambda r: r.id),
        hrus=sorted(hru_rows, key=lambda r: r.id),
        water=[],
        points=sorted(points, key=lambda r: r.id),
        routing=routing,
        aquifers=sorted(aquifers, key=lambda r: r.id),
        deep_aquifers=sorted(deep_aquifers, key=lambda r: r.id),
    )


# ---------------------------------------------------------------------------
# Row builders
# ---------------------------------------------------------------------------


def _build_subbasin_rows(
    subs_gdf: gpd.GeoDataFrame,
    lsu_rows: list[LsuRow],
    chans_gdf: gpd.GeoDataFrame,
    to_wgs84: Transformer,
) -> list[SubbasinRow]:
    """Emit ``SubbasinRow`` list. LSU stats are authoritative for
    slope / elevation because they were computed on the exact raster
    grid used downstream."""
    lsu_by_sub = {l.subbasin: l for l in lsu_rows}
    # Channel length per subbasin → `len1` (longest flow path proxy).
    length_by_sub: dict[int, float] = {}
    if "sub_id" in chans_gdf.columns and "length_m" in chans_gdf.columns:
        for c in chans_gdf.itertuples():
            sid_raw = getattr(c, "sub_id", 0)
            try:
                sid = int(sid_raw)
            except (TypeError, ValueError):
                # WBT sometimes emits channels whose centroid falls just
                # outside every subbasin polygon (raster→vector edge
                # artifact).  Skip those rather than crash.
                continue
            if sid <= 0:
                continue
            length_by_sub[sid] = max(length_by_sub.get(sid, 0.0), float(c.length_m))

    rows: list[SubbasinRow] = []
    for s in subs_gdf.itertuples():
        sid = int(s.sub_id)
        lsu = lsu_by_sub.get(sid)
        if lsu is None:
            log.warning("subbasin %s has no matching LSU row; skipping", sid)
            continue

        geom = s.geometry
        area_ha = float(geom.area) / 1e4 if geom is not None else float(lsu.area)
        centroid = geom.centroid if geom is not None else None
        if centroid is not None:
            lon, lat = to_wgs84.transform(centroid.x, centroid.y)
        else:
            lat, lon = lsu.lat, lsu.lon

        rows.append(
            SubbasinRow(
                id=sid,
                area=round(area_ha, 6),
                slo1=round(lsu.slope, 6),
                len1=round(length_by_sub.get(sid, lsu.len1), 3),
                sll=round(length_by_sub.get(sid, lsu.len1), 3),
                lat=round(float(lat), 8),
                lon=round(float(lon), 8),
                elev=round(lsu.elev, 3),
                # MVP: we don't track min/max separately from mean; use the
                # same value so downstream validators don't trip. Real
                # delineation.py pass will fill these when it reads the DEM.
                elevmin=round(lsu.elev, 3),
                elevmax=round(lsu.elev, 3),
                waterid=0,
            )
        )
    return rows


def _build_channel_rows(
    chans_gdf: gpd.GeoDataFrame,
    subs_gdf: gpd.GeoDataFrame,
    to_wgs84: Transformer,
) -> list[ChannelRow]:
    """Emit ``ChannelRow`` list. Uses attributes produced by
    :func:`gis.delineation._attribute_channels`."""
    sub_area_by_id: dict[int, float] = {
        int(s.sub_id): float(s.geometry.area) / 1e4
        for s in subs_gdf.itertuples()
    }

    rows: list[ChannelRow] = []
    for c in chans_gdf.itertuples():
        link_id = 0
        try:
            link_id = int(getattr(c, "link_id", 0))
        except (TypeError, ValueError):
            link_id = 0

        raw_sub_id = getattr(c, "sub_id", 0)
        try:
            sub_id = int(raw_sub_id)
        except (TypeError, ValueError):
            sub_id = 0

        # Some raster->vector joins can leave channel sub_id unset (0/NaN).
        # In our delineation graph, link_id and subbasin id are aligned, so
        # recover the subbasin assignment when possible instead of dropping
        # the channel and breaking network connectivity.
        if sub_id <= 0 and link_id in sub_area_by_id:
            sub_id = link_id
        elif sub_id <= 0 and len(sub_area_by_id) == 1:
            # Pathological but real on some large basins when clipping can
            # collapse polygonized subbasins to one feature while channels
            # remain segmented. Keep channels connected by assigning them to
            # the lone subbasin instead of dropping all channel rows.
            sub_id = next(iter(sub_area_by_id))

        if link_id <= 0 or sub_id <= 0:
            log.warning(
                "channel row missing link_id/sub_id; skipping: %r", c
            )
            continue
        geom = c.geometry
        if geom is None or geom.is_empty:
            continue
        midpt = geom.interpolate(0.5, normalized=True)
        lon, lat = to_wgs84.transform(midpt.x, midpt.y)

        length_m = float(getattr(c, "length_m", geom.length))
        slope_m_m = float(getattr(c, "slope_m_m", 0.0001))
        width_m = float(getattr(c, "width_m", 1.0))
        depth_m = float(getattr(c, "depth_m", 0.1))
        elev_min = float(getattr(c, "elev_min_m", 0.0))
        elev_max = float(getattr(c, "elev_max_m", elev_min))

        rows.append(
            ChannelRow(
                id=link_id,
                subbasin=sub_id,
                areac=round(sub_area_by_id.get(sub_id, 0.0), 6),
                strahler=1,
                len2=round(length_m, 3),
                slo2=round(slope_m_m * 100.0, 6),
                wid2=round(width_m, 3),
                dep2=round(depth_m, 3),
                elevmin=round(elev_min, 3),
                elevmax=round(elev_max, 3),
                midlat=round(float(lat), 8),
                midlon=round(float(lon), 8),
            )
        )
    return rows


def _build_aquifer_rows(subbasins: list[SubbasinRow]) -> list[AquiferRow]:
    """One floodplain aquifer per subbasin. Id reuses ``sub_id``."""
    return [
        AquiferRow(
            id=s.id,
            category=1,
            subbasin=s.id,
            deep_aquifer=s.id,
            area=s.area,
            lat=s.lat,
            lon=s.lon,
            elev=s.elev,
        )
        for s in subbasins
    ]


def _build_deep_aquifer_rows(
    subbasins: list[SubbasinRow],
) -> list[DeepAquiferRow]:
    """One deep aquifer per subbasin. Id reuses ``sub_id``."""
    return [
        DeepAquiferRow(
            id=s.id,
            subbasin=s.id,
            area=s.area,
            lat=s.lat,
            lon=s.lon,
            elev=s.elev,
        )
        for s in subbasins
    ]


def _build_point_rows(
    outlets_gdf: gpd.GeoDataFrame,
    outlet_subbasin: int,
    to_wgs84: Transformer,
) -> list[PointRow]:
    """Emit a single outlet ``PointRow``. QSWATPlus always has at least
    one outlet point (ptype=``'O'``)."""
    if outlets_gdf.empty:
        raise SwatBuilderInputError(
            "outlets vector is empty; delineation must produce one outlet."
        )
    geom = outlets_gdf.iloc[0].geometry
    lon, lat = to_wgs84.transform(geom.x, geom.y)
    return [
        PointRow(
            id=1,
            subbasin=outlet_subbasin,
            ptype="O",
            xpr=float(geom.x),
            ypr=float(geom.y),
            lat=round(float(lat), 8),
            lon=round(float(lon), 8),
            elev=0.0,
        )
    ]


def _build_routing_rows(
    *,
    hru_rows: list[HruRow],
    channels: list[ChannelRow],
    aquifers: list[AquiferRow],
    deep_aquifers: list[DeepAquiferRow],
    points: list[PointRow],
    routing_graph: nx.DiGraph,
    terminal_channel_ids: set[int],
) -> list[RoutingRow]:
    """Emit the minimal surface-water routing graph.

    Every ``(sourceid, sourcecat, hyd_typ)`` group sums to 100 by
    construction — each source routes to exactly one sink here.
    """
    routing: list[RoutingRow] = []

    # Look up: subbasin → channel id (in MVP, 1 channel per subbasin).
    channel_by_sub: dict[int, int] = {}
    for ch in channels:
        # First-seen wins; MVP has one channel per subbasin anyway.
        channel_by_sub.setdefault(ch.subbasin, ch.id)

    # Index the routing graph by channel id (delineation stored
    # channel / link ids as node labels).
    # Downstream lookup: channel -> next channel id (or None if terminal).
    # Walk past any skipped channels — a channel may drain into another
    # channel we dropped because its raster→vector centroid fell outside
    # every subbasin polygon.  Follow successors until we find a channel
    # that is still in ``known_ch_ids``, or hit the watershed outlet.
    known_ch_ids: set[int] = {ch.id for ch in channels}
    downstream: dict[int, int | None] = {}
    for ch in channels:
        if not routing_graph.has_node(ch.id):
            downstream[ch.id] = None
            continue
        node = ch.id
        visited: set[int] = {node}
        nxt: int | None = None
        while True:
            succs = list(routing_graph.successors(node))
            if not succs:
                nxt = None
                break
            cand = int(succs[0])
            if cand in known_ch_ids:
                nxt = cand
                break
            if cand in visited:
                nxt = None  # pathological cycle; treat as terminal
                break
            visited.add(cand)
            node = cand
        downstream[ch.id] = nxt

    # --- HRU → CH (tot, 100%) ---
    # Map HRU.lsu (== subbasin id) to channel.
    # Also collect unique LSU ids for the LSU→CH block below.
    lsu_to_ch: dict[int, int] = {}
    outlet_subbasin = int(points[0].subbasin) if points else None
    outlet_ch_id = (
        channel_by_sub.get(outlet_subbasin)
        if outlet_subbasin is not None
        else None
    )
    for hru in hru_rows:
        sub_id = hru.lsu  # MVP: lsu id == sub id
        ch_id = channel_by_sub.get(sub_id)
        if ch_id is None:
            # Edge case: one LSU may lose its channel during raster->vector
            # cleanup. Keep routing connected by falling back to the outlet
            # channel instead of emitting an un-routed HRU (which can crash
            # SWAT+ hyd_connect initialization).
            if outlet_ch_id is None:
                log.warning(
                    "HRU %s has lsu %s with no channel and no outlet fallback; routing row skipped",
                    hru.id, hru.lsu,
                )
                continue
            log.warning(
                "HRU %s has lsu %s with no channel; routing to outlet channel %s",
                hru.id,
                hru.lsu,
                outlet_ch_id,
            )
            ch_id = outlet_ch_id
        routing.append(
            RoutingRow(
                sourceid=hru.id, sourcecat="HRU", hyd_typ="tot",
                sinkid=ch_id, sinkcat="CH", percent=100.0,
            )
        )
        lsu_to_ch[sub_id] = ch_id

    # --- LSU -> CH (sur + lat, 100% each) ---
    # The SWAT+ Editor's import_gis.insert_connections() queries gis_routing
    # for sourcecat='LSU' to populate rout_unit_con_out.  Without these rows
    # rout_unit.con gets out_tot=0 for every RTU, so no water ever enters
    # the stream network and the engine segfaults on travel-time calculation.
    # Use explicit surface/lateral hydrograph routes. A single total-flow route
    # plus explicit sur/lat routes double-counts water in sdc/chandeg full-mode
    # runs, which is visible as surq_cha+latq_cha ~= 2 * wateryld.
    for lsu_id, ch_id in sorted(lsu_to_ch.items()):
        for hyd_typ in ("sur", "lat"):
            routing.append(
                RoutingRow(
                    sourceid=lsu_id, sourcecat="LSU", hyd_typ=hyd_typ,
                    sinkid=ch_id, sinkcat="CH", percent=100.0,
                )
            )

    # --- CH → CH (tot, 100%) or CH → X for terminal ---
    for ch in channels:
        ds = downstream.get(ch.id)
        if ds is None or ch.id in terminal_channel_ids:
            routing.append(
                RoutingRow(
                    sourceid=ch.id, sourcecat="CH", hyd_typ="tot",
                    sinkid=0, sinkcat="X", percent=100.0,
                )
            )
        else:
            routing.append(
                RoutingRow(
                    sourceid=ch.id, sourcecat="CH", hyd_typ="tot",
                    sinkid=ds, sinkcat="CH", percent=100.0,
                )
            )

    # --- AQU → CH (tot, 100%) ---
    for aq in aquifers:
        ch_id = channel_by_sub.get(aq.subbasin)
        if ch_id is None:
            continue
        routing.append(
            RoutingRow(
                sourceid=aq.id, sourcecat="AQU", hyd_typ="tot",
                sinkid=ch_id, sinkcat="CH", percent=100.0,
            )
        )

    # --- DAQ → X (tot, 100%) ---
    for daq in deep_aquifers:
        routing.append(
            RoutingRow(
                sourceid=daq.id, sourcecat="DAQ", hyd_typ="tot",
                sinkid=0, sinkcat="X", percent=100.0,
            )
        )

    # --- PT → CH (tot, 100%) ---
    # Outlet point lives on the outlet subbasin's channel.
    for pt in points:
        ch_id = channel_by_sub.get(pt.subbasin)
        if ch_id is None:
            continue
        routing.append(
            RoutingRow(
                sourceid=pt.id, sourcecat="PT", hyd_typ="tot",
                sinkid=ch_id, sinkcat="CH", percent=100.0,
            )
        )

    return routing


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_vector(path: Path | str, label: str) -> gpd.GeoDataFrame:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise SwatBuilderInputError(
            f"{label} not found: {p}", label=label, path=str(p)
        )
    return gpd.read_file(p)


def _load_routing_graph(path: Path | str) -> nx.DiGraph:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        # An empty graph is a valid degenerate case (single subbasin
        # with one channel, no routing).
        return nx.DiGraph()
    g = nx.read_graphml(p)
    # Coerce string labels from graphml back to int where possible so
    # downstream lookups work the same as the in-memory graph.
    mapping: dict[Any, Any] = {}
    for node in g.nodes:
        try:
            mapping[node] = int(node)
        except (TypeError, ValueError):
            mapping[node] = node
    return nx.relabel_nodes(g, mapping)


def _terminal_channel_ids(
    routing_graph: nx.DiGraph, chans_gdf: gpd.GeoDataFrame
) -> set[int]:
    """Channels with no successor in the routing graph."""
    if routing_graph.number_of_nodes() == 0:
        # Degenerate: every channel terminates at the outlet.
        if "link_id" in chans_gdf.columns:
            return {int(c) for c in chans_gdf["link_id"].tolist()}
        return set()
    terms: set[int] = set()
    for node in routing_graph.nodes:
        try:
            nid = int(node)
        except (TypeError, ValueError):
            continue
        if routing_graph.out_degree(node) == 0:
            terms.add(nid)
    return terms


def _channel_parent_subbasin(
    chans_gdf: gpd.GeoDataFrame, link_id: int
) -> int:
    if "link_id" not in chans_gdf.columns or "sub_id" not in chans_gdf.columns:
        return 1
    match = chans_gdf[chans_gdf["link_id"].astype(int) == link_id]
    if match.empty:
        # Fallback to any valid channel sub_id in this basin.
        valid = chans_gdf["sub_id"].dropna()
        if valid.empty:
            return 1
        try:
            sid = int(valid.iloc[0])
            return sid if sid > 0 else 1
        except (TypeError, ValueError):
            return 1
    raw = match.iloc[0]["sub_id"]
    try:
        sid = int(raw)
        if sid > 0:
            return sid
    except (TypeError, ValueError):
        pass
    # Matched channel exists but has NaN/invalid sub_id; recover from any
    # other valid channel row so build_tables can continue.
    valid = chans_gdf["sub_id"].dropna()
    if not valid.empty:
        try:
            sid = int(valid.iloc[0])
            if sid > 0:
                return sid
        except (TypeError, ValueError):
            pass
    return 1
