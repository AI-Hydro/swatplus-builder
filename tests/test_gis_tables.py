"""Tests for :mod:`swatplus_builder.gis.tables`.

Wires the synthetic watershed from ``test_gis_hru`` through the HRU
overlay and into a :class:`GisTables`, then asserts:

* every ``gis_*`` row list is populated with the right cardinalities;
* the routing model passes
  :func:`swatplus_builder.db.writer.validate_tables`;
* the full pipeline survives a real :func:`write_all` round-trip into
  a sqlite file.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import networkx as nx
import pytest

from tests.test_gis_hru import mini_watershed  # noqa: F401  (pytest fixture reuse)


def _write_routing_graph(watershed, chans_sub_ids: list[int]) -> Path:
    """Build a trivial linear routing graph sub1 → sub2 → exit."""
    g = nx.DiGraph()
    for sid in chans_sub_ids:
        g.add_node(sid)
    for a, b in zip(chans_sub_ids, chans_sub_ids[1:], strict=False):
        g.add_edge(a, b)
    path = Path(watershed.workdir) / "routing.graphml"
    nx.write_graphml(g, path)
    # Re-wrap the watershed with the new routing graph path.
    return path


class TestBuildTables:
    def test_end_to_end_hru_to_gistables(self, mini_watershed, tmp_path):
        """Full synthetic pipeline:

        synthetic watershed → create_hrus → build_tables → GisTables.
        """
        from swatplus_builder.gis.hru import create_hrus
        from swatplus_builder.gis.tables import build_tables
        from swatplus_builder.types import WatershedResult

        # The fixture's watershed uses a placeholder outlets/routing;
        # replace them with real ones.
        ws: WatershedResult = mini_watershed["watershed"]
        # Outlet point: snap to the middle of sub 2's channel.
        import geopandas as gpd
        from shapely.geometry import Point
        outlet_path = Path(ws.workdir) / "shapes" / "outlets.gpkg"
        outlet_pt = Point(500_180.0, 4_499_880.0)  # inside sub 2
        gpd.GeoDataFrame(
            {"outlet_id": [1]}, geometry=[outlet_pt], crs=ws.crs
        ).to_file(outlet_path, driver="GPKG")

        # Routing: channel 101 (sub 1) → channel 102 (sub 2) → exit.
        g = nx.DiGraph()
        g.add_node(101)
        g.add_node(102)
        g.add_edge(101, 102)
        routing_path = Path(ws.workdir) / "routing.graphml"
        nx.write_graphml(g, routing_path)

        # Rewrap the watershed with the real paths.
        ws = ws.model_copy(update={
            "outlets_vector": outlet_path,
            "routing_graph": routing_path,
        })

        hru_result = create_hrus(
            ws,
            mini_watershed["landuse_raster"],
            mini_watershed["soil_raster"],
        )

        tables = build_tables(ws, hru_result)

        # Cardinalities: 2 subbasins → 2 each of every category that's
        # 1-to-1 with the subbasin, plus 2 channels, plus 2 HRUs
        # (dominant mode), plus 1 outlet point.
        assert len(tables.subbasins) == 2
        assert len(tables.channels) == 2
        assert len(tables.lsus) == 2
        assert len(tables.hrus) == 2
        assert len(tables.aquifers) == 2
        assert len(tables.deep_aquifers) == 2
        assert len(tables.points) == 1
        assert len(tables.water) == 0

        # Routing: 2 HRU→CH + 2 CH→(CH|X) + 2 AQU→CH + 2 DAQ→X + 1 PT→CH
        assert len(tables.routing) == 2 + 2 + 2 + 2 + 1

    def test_routing_sums_to_100_per_group(self, mini_watershed):
        """Each ``(sourceid, sourcecat, hyd_typ)`` group must sum to 100
        for :func:`validate_tables` to accept the payload."""
        from collections import defaultdict

        from swatplus_builder.gis.hru import create_hrus
        from swatplus_builder.gis.tables import build_tables

        import geopandas as gpd
        from shapely.geometry import Point
        ws = mini_watershed["watershed"]
        outlet_path = Path(ws.workdir) / "shapes" / "outlets.gpkg"
        gpd.GeoDataFrame(
            {"outlet_id": [1]}, geometry=[Point(500_180.0, 4_499_880.0)],
            crs=ws.crs,
        ).to_file(outlet_path, driver="GPKG")

        g = nx.DiGraph(); g.add_node(101); g.add_node(102); g.add_edge(101, 102)
        routing_path = Path(ws.workdir) / "routing.graphml"
        nx.write_graphml(g, routing_path)

        ws = ws.model_copy(update={
            "outlets_vector": outlet_path, "routing_graph": routing_path,
        })

        hru_result = create_hrus(
            ws, mini_watershed["landuse_raster"], mini_watershed["soil_raster"],
        )
        tables = build_tables(ws, hru_result)

        sums: dict[tuple[int, str, str | None], float] = defaultdict(float)
        for r in tables.routing:
            sums[(r.sourceid, r.sourcecat, r.hyd_typ)] += r.percent
        for key, total in sums.items():
            assert total == pytest.approx(100.0, abs=0.5), (
                f"routing percent for {key} = {total}"
            )

    def test_terminal_channel_routes_to_exit(self, mini_watershed):
        """Channel 102 is downstream of 101; it should route to
        ``sinkcat='X', sinkid=0`` (the reserved watershed outlet)."""
        from swatplus_builder.gis.hru import create_hrus
        from swatplus_builder.gis.tables import build_tables

        import geopandas as gpd
        from shapely.geometry import Point
        ws = mini_watershed["watershed"]
        outlet_path = Path(ws.workdir) / "shapes" / "outlets.gpkg"
        gpd.GeoDataFrame(
            {"outlet_id": [1]}, geometry=[Point(500_180.0, 4_499_880.0)],
            crs=ws.crs,
        ).to_file(outlet_path, driver="GPKG")

        g = nx.DiGraph(); g.add_node(101); g.add_node(102); g.add_edge(101, 102)
        routing_path = Path(ws.workdir) / "routing.graphml"
        nx.write_graphml(g, routing_path)

        ws = ws.model_copy(update={
            "outlets_vector": outlet_path, "routing_graph": routing_path,
        })
        hru_result = create_hrus(
            ws, mini_watershed["landuse_raster"], mini_watershed["soil_raster"],
        )
        tables = build_tables(ws, hru_result)

        ch_routes = {r.sourceid: r for r in tables.routing if r.sourcecat == "CH"}
        # Channel 101 → Channel 102 (not terminal).
        assert ch_routes[101].sinkcat == "CH"
        assert ch_routes[101].sinkid == 102
        # Channel 102 is terminal → exit.
        assert ch_routes[102].sinkcat == "X"
        assert ch_routes[102].sinkid == 0

    def test_write_all_round_trip_to_sqlite(self, mini_watershed, tmp_path):
        """The end-game proof: synthetic watershed → tables → actual
        ``project.sqlite`` with ``gis_*`` rows populated."""
        from swatplus_builder.db.project import create_project_db
        from swatplus_builder.db.writer import write_all
        from swatplus_builder.gis.hru import create_hrus
        from swatplus_builder.gis.tables import build_tables

        import geopandas as gpd
        from shapely.geometry import Point
        ws = mini_watershed["watershed"]
        outlet_path = Path(ws.workdir) / "shapes" / "outlets.gpkg"
        gpd.GeoDataFrame(
            {"outlet_id": [1]}, geometry=[Point(500_180.0, 4_499_880.0)],
            crs=ws.crs,
        ).to_file(outlet_path, driver="GPKG")

        g = nx.DiGraph(); g.add_node(101); g.add_node(102); g.add_edge(101, 102)
        routing_path = Path(ws.workdir) / "routing.graphml"
        nx.write_graphml(g, routing_path)

        ws = ws.model_copy(update={
            "outlets_vector": outlet_path, "routing_graph": routing_path,
        })

        hru_result = create_hrus(
            ws, mini_watershed["landuse_raster"], mini_watershed["soil_raster"],
        )
        tables = build_tables(ws, hru_result)

        db_path = create_project_db("mini", tmp_path)
        counts = write_all(db_path, tables)
        assert counts["subbasins"] == 2
        assert counts["channels"] == 2
        assert counts["hrus"] == 2
        assert counts["lsus"] == 2
        assert counts["aquifers"] == 2
        assert counts["deep_aquifers"] == 2
        assert counts["points"] == 1
        assert counts["routing"] == 2 + 2 + 2 + 2 + 1

        # Sanity check: a few rows survived in the DB.
        with sqlite3.connect(db_path) as conn:
            n_hrus = conn.execute("SELECT COUNT(*) FROM gis_hrus").fetchone()[0]
            n_routing = conn.execute("SELECT COUNT(*) FROM gis_routing").fetchone()[0]
            (flag_delin,) = conn.execute(
                "SELECT delineation_done FROM project_config"
            ).fetchone()
        assert n_hrus == 2
        assert n_routing == 9
        assert flag_delin == 1

    def test_routing_walks_past_dropped_channels(self, mini_watershed, tmp_path):
        """Regression for Phase 2 Step 8 (real-basin run).

        When a channel from the WhiteboxTools routing graph is NOT in the
        ``channels`` list (e.g. its centroid landed outside every subbasin
        polygon and was skipped by ``_build_channel_rows``),
        ``_build_routing_rows`` must NOT emit a CH→CH row pointing at the
        missing channel — otherwise the SWAT+ Editor's ``import_gis``
        raises ``KeyError`` on the orphan sinkid.  The expected behaviour
        is to walk the graph downstream past the gap and route to the
        next channel that IS in the list, or to ``X`` if none exists.
        """
        from swatplus_builder.gis.tables import _build_routing_rows
        from swatplus_builder.types import (
            AquiferRow,
            ChannelRow,
            DeepAquiferRow,
            HruRow,
            PointRow,
        )

        # Chain: ch 1 → ch 2 (DROPPED) → ch 3 → ch 4 (terminal).
        # Only 1, 3, 4 appear in ``channels`` — 2 was skipped.
        def ch(id_: int, sub_id: int) -> ChannelRow:
            return ChannelRow(
                id=id_, subbasin=sub_id, areac=1.0, strahler=1,
                len2=100.0, slo2=0.01, wid2=1.0, dep2=0.1,
                elevmin=0.0, elevmax=10.0, midlat=0.0, midlon=0.0,
            )

        channels = [ch(1, 1), ch(3, 3), ch(4, 4)]  # channel 2 dropped

        g = nx.DiGraph()
        for n in (1, 2, 3, 4):
            g.add_node(n)
        g.add_edges_from([(1, 2), (2, 3), (3, 4)])

        routing = _build_routing_rows(
            hru_rows=[
                HruRow(
                    id=1, lsu=1, arsub=1.0, arlsu=1.0, landuse="FRST",
                    arland=1.0, soil="gnatsgo_1", arso=1.0, slp="0-5",
                    arslp=1.0, slope=1.0, lat=0.0, lon=0.0, elev=0.0,
                ),
            ],
            channels=channels,
            aquifers=[],
            deep_aquifers=[],
            points=[],
            routing_graph=g,
            terminal_channel_ids={4},
        )

        ch_routes = {r.sourceid: r for r in routing if r.sourcecat == "CH"}

        # Ch 1 should skip past the dropped ch 2 and target ch 3.
        assert ch_routes[1].sinkcat == "CH"
        assert ch_routes[1].sinkid == 3

        # Ch 3 targets ch 4 directly.
        assert ch_routes[3].sinkcat == "CH"
        assert ch_routes[3].sinkid == 4

        # Ch 4 is terminal → outlet.
        assert ch_routes[4].sinkcat == "X"
        assert ch_routes[4].sinkid == 0

        # No routing row ever points at the missing channel 2.
        for r in routing:
            assert not (r.sinkcat == "CH" and r.sinkid == 2), (
                "routing must not reference dropped channels"
            )

    def test_routing_terminates_at_X_when_all_downstream_is_missing(self):
        """If the only downstream channel is missing and there's no further
        path, the source channel should be treated as terminal (sink=X/0).
        """
        from swatplus_builder.gis.tables import _build_routing_rows
        from swatplus_builder.types import ChannelRow

        channels = [
            ChannelRow(
                id=1, subbasin=1, areac=1.0, strahler=1,
                len2=100.0, slo2=0.01, wid2=1.0, dep2=0.1,
                elevmin=0.0, elevmax=10.0, midlat=0.0, midlon=0.0,
            ),
        ]
        g = nx.DiGraph()
        g.add_nodes_from([1, 2])
        g.add_edge(1, 2)  # 2 is NOT in channels, no further successor

        routing = _build_routing_rows(
            hru_rows=[], channels=channels,
            aquifers=[], deep_aquifers=[], points=[],
            routing_graph=g, terminal_channel_ids=set(),
        )
        ch1 = next(r for r in routing if r.sourcecat == "CH" and r.sourceid == 1)
        assert ch1.sinkcat == "X"
        assert ch1.sinkid == 0

    def test_missing_subbasins_raises_input_error(self, mini_watershed, tmp_path):
        from swatplus_builder.errors import SwatBuilderInputError
        from swatplus_builder.gis.hru import create_hrus
        from swatplus_builder.gis.tables import build_tables

        hru_result = create_hrus(
            mini_watershed["watershed"],
            mini_watershed["landuse_raster"],
            mini_watershed["soil_raster"],
        )
        ws = mini_watershed["watershed"].model_copy(
            update={"subbasins_vector": tmp_path / "missing.gpkg"}
        )
        with pytest.raises(SwatBuilderInputError):
            build_tables(ws, hru_result)
