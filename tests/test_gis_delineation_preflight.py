"""Tests for delineation topology preflight gate (check_topology_realism).

No WhiteboxTools or real DEM required — all tests use synthetic stats dicts
that mirror the structure produced by delineate().

The 03339000 contrast-basin failure that motivated this gate had:
  n_subbasins=1, n_channels=5331, n_terminals=19, total_area_km2=0.22
  vs NLDI expected area ~3341 km2.
"""

from __future__ import annotations

import threading
import time

import pytest

from swatplus_builder.errors import SwatBuilderPipelineError
from swatplus_builder.gis.delineation import (
    _check_wbt_output,
    _outlet_link_id,
    _prune_disconnected_components,
    _prune_topology_to_valid_channels,
    _watershed_domain_edge_contact_count,
    check_topology_realism,
)


def test_downstream_split_resolution_keeps_highest_accumulation_receiver() -> None:
    import networkx as nx
    import numpy as np

    from swatplus_builder.gis.delineation import (
        _resolve_downstream_splits_by_flow_accumulation,
    )

    graph = nx.DiGraph([(4, 1), (4, 38), (1, 38), (38, 39)])
    max_acc = np.zeros(40, dtype="float64")
    max_acc[[1, 4, 38, 39]] = [312_620, 312_620, 377_940, 3_432_444]

    removed = _resolve_downstream_splits_by_flow_accumulation(graph, max_acc)

    assert removed == 1
    assert list(graph.successors(4)) == [38]
    assert list(graph.successors(1)) == [38]
    assert nx.is_directed_acyclic_graph(graph)

def test_watershed_domain_edge_contact_count_detects_truncation(tmp_path) -> None:
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    profile = {
        "driver": "GTiff",
        "height": 5,
        "width": 5,
        "count": 1,
        "dtype": "int16",
        "crs": "EPSG:5070",
        "transform": from_origin(0, 5, 1, 1),
        "nodata": -9999,
    }
    dem = tmp_path / "dem.tif"
    watershed = tmp_path / "watershed.tif"
    with rasterio.open(dem, "w", **profile) as dst:
        dst.write(np.ones((5, 5), dtype="int16"), 1)
    interior = np.zeros((5, 5), dtype="int16")
    interior[2, 2] = 1
    with rasterio.open(watershed, "w", **profile) as dst:
        dst.write(interior, 1)
    assert _watershed_domain_edge_contact_count(dem, watershed) == 0

    truncated = np.zeros((5, 5), dtype="int16")
    truncated[0, 2] = 1
    with rasterio.open(watershed, "w", **profile) as dst:
        dst.write(truncated, 1)
    assert _watershed_domain_edge_contact_count(dem, watershed) == 1


def _stats(
    n_subbasins: float = 43,
    n_channels: float = 80,
    n_terminals: float = 1,
    total_area_km2: float = 500.0,
) -> dict[str, float]:
    return {
        "n_subbasins": n_subbasins,
        "n_channels": n_channels,
        "n_terminals": n_terminals,
        "total_area_km2": total_area_km2,
        "mean_slope_m_m": 0.05,
        "stream_threshold_cells": 500.0,
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestValidTopology:
    def test_healthy_basin_passes(self):
        check_topology_realism(_stats(), expected_area_km2=500.0)

    def test_no_expected_area_skips_area_check(self):
        # Even a tiny generated area passes when no expected area is provided.
        check_topology_realism(_stats(total_area_km2=0.1))

    def test_area_exactly_at_threshold_passes(self):
        # 10% of 1000 = 100 km2; generated 100 km2 → exactly at threshold.
        check_topology_realism(_stats(total_area_km2=100.0), expected_area_km2=1000.0)

    def test_multiple_terminals_below_max_passes(self):
        check_topology_realism(_stats(n_terminals=3), max_terminals=5)

    def test_channels_per_subbasin_below_max_passes(self):
        # 49 channels / 1 subbasin = 49 < 50 → passes.
        check_topology_realism(_stats(n_subbasins=1, n_channels=49))

    def test_custom_thresholds_accepted(self):
        # Caller loosens thresholds for a large complex basin.
        check_topology_realism(
            _stats(n_subbasins=2, n_channels=150, n_terminals=7, total_area_km2=50.0),
            expected_area_km2=100.0,
            min_area_ratio=0.4,
            max_channels_per_subbasin=200,
            max_terminals=10,
        )

    def test_routing_graph_prunes_channels_without_surviving_subbasins(self):
        import geopandas as gpd
        import networkx as nx
        from shapely.geometry import LineString, Polygon

        graph = nx.DiGraph()
        graph.add_nodes_from([1, 2, 3])
        graph.add_edge(1, 2)
        channels = gpd.GeoDataFrame(
            {
                "link_id": [1, 2, 3],
                "sub_id": [1, 2, float("nan")],
            },
            geometry=[
                LineString([(0, 0), (1, 0)]),
                LineString([(1, 0), (2, 0)]),
                LineString([(10, 0), (11, 0)]),
            ],
            crs="EPSG:5070",
        )
        subbasins = gpd.GeoDataFrame(
            {"sub_id": [1, 2]},
            geometry=[
                Polygon([(0, -1), (1, -1), (1, 1), (0, 1)]),
                Polygon([(1, -1), (2, -1), (2, 1), (1, 1)]),
            ],
            crs="EPSG:5070",
        )

        pruned = _prune_topology_to_valid_channels(graph, channels, subbasins)

        assert sorted(pruned.nodes) == [1, 2]
        assert sorted(n for n in pruned.nodes if pruned.out_degree(n) == 0) == [2]

    def test_whitebox_output_check_waits_for_delayed_file_visibility(self, tmp_path):
        delayed = tmp_path / "dem_conditioned.tif"

        def create_later() -> None:
            time.sleep(0.2)
            delayed.write_bytes(b"raster")

        thread = threading.Thread(target=create_later)
        thread.start()
        try:
            _check_wbt_output(0, "BreachDepressionsLeastCost", delayed)
        finally:
            thread.join(timeout=2)

        assert delayed.exists()


# ---------------------------------------------------------------------------
# Area ratio failures
# ---------------------------------------------------------------------------

class TestAreaRatioGate:
    def test_03339000_signature_fails(self):
        """Reproduce the exact 03339000 failure: 0.22 km² vs 3341 km² expected."""
        with pytest.raises(SwatBuilderPipelineError, match="area mismatch"):
            check_topology_realism(
                _stats(total_area_km2=0.22),
                expected_area_km2=3340.879,
            )

    def test_error_contains_diagnostic_fields(self):
        with pytest.raises(SwatBuilderPipelineError) as exc_info:
            check_topology_realism(
                _stats(total_area_km2=5.0),
                expected_area_km2=1000.0,
                usgs_id="03339000",
            )
        ctx = exc_info.value.context
        assert ctx["generated_area_km2"] == pytest.approx(5.0)
        assert ctx["expected_area_km2"] == pytest.approx(1000.0)
        assert ctx["usgs_id"] == "03339000"
        assert "area_ratio" in ctx
        assert ctx["area_ratio"] == pytest.approx(0.005, rel=1e-3)

    def test_area_just_below_threshold_fails(self):
        # 9.9% of expected → below 10% threshold.
        with pytest.raises(SwatBuilderPipelineError, match="area mismatch"):
            check_topology_realism(
                _stats(total_area_km2=99.0),
                expected_area_km2=1000.0,
            )

    def test_zero_expected_area_skips_check(self):
        # Guard: if expected_area_km2=0 is passed, don't divide by zero.
        check_topology_realism(_stats(total_area_km2=0.1), expected_area_km2=0.0)

    def test_custom_min_area_ratio(self):
        # With min_area_ratio=0.5, 40% coverage fails.
        with pytest.raises(SwatBuilderPipelineError, match="area mismatch"):
            check_topology_realism(
                _stats(total_area_km2=400.0),
                expected_area_km2=1000.0,
                min_area_ratio=0.5,
            )


# ---------------------------------------------------------------------------
# Channel explosion failures
# ---------------------------------------------------------------------------

class TestChannelExplosionGate:
    def test_03339000_channel_explosion_fails(self):
        """5331 channels / 1 subbasin >>> 50 threshold."""
        with pytest.raises(SwatBuilderPipelineError, match="[Cc]hannel explosion"):
            check_topology_realism(_stats(n_subbasins=1, n_channels=5331))

    def test_error_contains_ratio(self):
        with pytest.raises(SwatBuilderPipelineError) as exc_info:
            check_topology_realism(_stats(n_subbasins=2, n_channels=200))
        ctx = exc_info.value.context
        assert ctx["channels_per_subbasin"] == pytest.approx(100.0)
        assert ctx["max_channels_per_subbasin"] == 50.0

    def test_exactly_at_limit_passes(self):
        # 50 channels / 1 subbasin = 50.0 → NOT above threshold, passes.
        check_topology_realism(_stats(n_subbasins=1, n_channels=50))

    def test_one_above_limit_fails(self):
        with pytest.raises(SwatBuilderPipelineError, match="[Cc]hannel explosion"):
            check_topology_realism(_stats(n_subbasins=1, n_channels=51))

    def test_custom_max_channels_per_subbasin(self):
        # Caller allows up to 200; 150 passes.
        check_topology_realism(
            _stats(n_subbasins=1, n_channels=150),
            max_channels_per_subbasin=200,
        )


# ---------------------------------------------------------------------------
# Terminal explosion failures
# ---------------------------------------------------------------------------

class TestTerminalExplosionGate:
    def test_19_terminals_fails(self):
        """Small basin (43 subbasins): effective threshold = max(5, 3) = 5 → 19 fails."""
        with pytest.raises(SwatBuilderPipelineError, match="[Tt]erminal"):
            check_topology_realism(_stats(n_terminals=19))

    def test_error_contains_terminal_count(self):
        with pytest.raises(SwatBuilderPipelineError) as exc_info:
            check_topology_realism(_stats(n_terminals=10))
        ctx = exc_info.value.context
        assert ctx["n_terminals"] == 10
        # effective_max_terminals = max(5, int(43 * 0.08)) = max(5, 3) = 5
        assert ctx["max_terminals"] == 5

    def test_exactly_at_limit_passes(self):
        check_topology_realism(_stats(n_terminals=5))

    def test_one_above_limit_fails(self):
        with pytest.raises(SwatBuilderPipelineError, match="[Tt]erminal"):
            check_topology_realism(_stats(n_terminals=6))

    def test_custom_max_terminals(self):
        check_topology_realism(_stats(n_terminals=8), max_terminals=10)

    def test_03339000_large_basin_258_terminals_passes(self):
        """03339000 after snap fix: 4023 subbasins, 258 terminals.

        Rate-based threshold: max(5, int(4023 * 0.08)) = 321 → 258 passes.
        These are boundary terminals from DEM truncation, not fragmentation.
        """
        check_topology_realism(
            _stats(n_subbasins=4023, n_channels=5333, n_terminals=258, total_area_km2=2513.8),
            expected_area_km2=3340.879,
        )

    def test_truly_fragmented_large_basin_fails(self):
        """Even a large basin fails when terminal rate exceeds 8%."""
        # 4023 subbasins × 8% = 321 effective threshold; 400 > 321 → fails.
        with pytest.raises(SwatBuilderPipelineError, match="[Tt]erminal"):
            check_topology_realism(
                _stats(n_subbasins=4023, n_channels=5333, n_terminals=400, total_area_km2=2513.8),
                expected_area_km2=3340.879,
            )

    def test_rate_based_threshold_scales_with_basin_size(self):
        """Effective threshold = max(abs, n_sub * rate)."""
        # 1000 subbasins × 8% = 80; terminal count of 70 passes.
        check_topology_realism(_stats(n_subbasins=1000, n_channels=1200, n_terminals=70))
        # Terminal count of 85 fails.
        with pytest.raises(SwatBuilderPipelineError, match="[Tt]erminal"):
            check_topology_realism(_stats(n_subbasins=1000, n_channels=1200, n_terminals=85))


# ---------------------------------------------------------------------------
# Priority: area check fires before channel check
# ---------------------------------------------------------------------------

class TestCheckPriority:
    def test_area_check_fires_first(self):
        """When both area ratio and channel explosion are bad, area error is raised."""
        with pytest.raises(SwatBuilderPipelineError, match="area mismatch"):
            check_topology_realism(
                _stats(total_area_km2=0.1, n_subbasins=1, n_channels=5000),
                expected_area_km2=3000.0,
            )


# ---------------------------------------------------------------------------
# _outlet_link_id — synthetic raster tests
# ---------------------------------------------------------------------------

class TestOutletLinkId:
    def _make_stream_links_raster(self, tmp_path, values):
        """Write a tiny 3×3 int32 raster with the given 2-D values array."""
        import numpy as np
        import rasterio
        from rasterio.transform import from_bounds

        arr = np.array(values, dtype=np.int32)
        transform = from_bounds(0.0, 0.0, 3.0, 3.0, arr.shape[1], arr.shape[0])
        path = tmp_path / "stream_links.tif"
        with rasterio.open(
            path, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1],
            count=1, dtype="int32", crs="EPSG:32614", transform=transform,
        ) as dst:
            dst.write(arr, 1)
        return path

    def test_returns_link_id_at_stream_pixel(self, tmp_path):
        # Centre pixel of a 3×3 raster = stream link 5
        path = self._make_stream_links_raster(tmp_path, [
            [0, 0, 0],
            [0, 5, 0],
            [0, 0, 0],
        ])
        # Centre pixel centre coordinates: x=1.5, y=1.5
        result = _outlet_link_id(path, 1.5, 1.5)
        assert result == 5

    def test_returns_none_for_non_stream_pixel(self, tmp_path):
        path = self._make_stream_links_raster(tmp_path, [
            [0, 0, 0],
            [0, 0, 0],
            [0, 7, 0],
        ])
        result = _outlet_link_id(path, 1.5, 1.5)  # centre → 0
        assert result is None

    def test_returns_none_for_bad_path(self, tmp_path):
        result = _outlet_link_id(tmp_path / "nonexistent.tif", 0.0, 0.0)
        assert result is None

    def test_clamps_to_raster_bounds(self, tmp_path):
        # Far-out coordinates clamp to nearest valid pixel
        path = self._make_stream_links_raster(tmp_path, [
            [3, 0, 0],
            [0, 0, 0],
            [0, 0, 0],
        ])
        # Top-left pixel centre: x=0.5, y=2.5  (rasterio origin is top-left)
        result = _outlet_link_id(path, 0.5, 2.5)
        assert result == 3


# ---------------------------------------------------------------------------
# _prune_disconnected_components — graph pruning tests
# ---------------------------------------------------------------------------

class TestPruneDisconnectedComponents:
    def _make_graph(self, edges, isolated_nodes=()):
        import networkx as nx
        G = nx.DiGraph()
        G.add_edges_from(edges)
        G.add_nodes_from(isolated_nodes)
        return G

    def test_single_component_is_no_op(self):
        G = self._make_graph([(1, 2), (2, 3)])
        pruned, n_pruned, n_comps = _prune_disconnected_components(G, outlet_link_id=3)
        assert n_pruned == 0
        assert n_comps == 0
        assert set(pruned.nodes) == {1, 2, 3}

    def test_keeps_component_containing_outlet(self):
        # Two components: 1→2→3 (outlet=3) and 10→11
        G = self._make_graph([(1, 2), (2, 3), (10, 11)])
        pruned, n_pruned, n_comps = _prune_disconnected_components(G, outlet_link_id=3)
        assert set(pruned.nodes) == {1, 2, 3}
        assert n_pruned == 2
        assert n_comps == 1

    def test_falls_back_to_largest_component_when_outlet_absent(self):
        # outlet_link_id=99 not in graph; largest component is 1→2→3→4→5
        G = self._make_graph([(1, 2), (2, 3), (3, 4), (4, 5), (10, 11)])
        pruned, n_pruned, n_comps = _prune_disconnected_components(G, outlet_link_id=99)
        assert set(pruned.nodes) == {1, 2, 3, 4, 5}
        assert n_pruned == 2

    def test_falls_back_to_largest_when_outlet_is_none(self):
        G = self._make_graph([(1, 2), (2, 3), (10, 11)])
        pruned, n_pruned, _ = _prune_disconnected_components(G, outlet_link_id=None)
        assert set(pruned.nodes) == {1, 2, 3}

    def test_empty_graph_is_no_op(self):
        import networkx as nx
        G = nx.DiGraph()
        pruned, n_pruned, n_comps = _prune_disconnected_components(G, outlet_link_id=None)
        assert n_pruned == 0
        assert n_comps == 0

    def test_multiple_fragments_all_pruned(self):
        # Main: 1→2→3  Fragments: 10, 20→21, 30→31→32
        G = self._make_graph(
            [(1, 2), (2, 3), (20, 21), (30, 31), (31, 32)],
            isolated_nodes=[10],
        )
        pruned, n_pruned, n_comps = _prune_disconnected_components(G, outlet_link_id=3)
        assert set(pruned.nodes) == {1, 2, 3}
        assert n_pruned == 6   # 10, 20, 21, 30, 31, 32
        assert n_comps == 3

    def test_pruned_graph_has_correct_edges(self):
        G = self._make_graph([(1, 2), (2, 3), (10, 11)])
        pruned, _, _ = _prune_disconnected_components(G, outlet_link_id=2)
        assert list(pruned.edges) == [(1, 2), (2, 3)]

    def test_outlet_in_smaller_component_kept_not_largest(self):
        # outlet=99 is in the 2-node component {99, 100}, not the larger {1,2,3,4}
        G = self._make_graph([(1, 2), (2, 3), (3, 4), (99, 100)])
        pruned, n_pruned, _ = _prune_disconnected_components(G, outlet_link_id=99)
        assert set(pruned.nodes) == {99, 100}
        assert n_pruned == 4
