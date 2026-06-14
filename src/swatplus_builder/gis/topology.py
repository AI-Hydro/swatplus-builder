"""Routing graph construction: topology -> gis_routing rows.

Takes the channel DiGraph from :mod:`gis.delineation` plus the HRU/LSU layout
from :mod:`gis.hru` and emits the complete list of routing records that
SWAT+ Editor's ``import_gis`` expects.

Phase 1 scope (enough for a minimal single-outlet run):
    - HRU -> LSU (tot)
    - LSU -> CH  (sur, lat)
    - CH  -> CH  (tot)  along the network downstream
    - CH  -> X   (tot)  at the outlet (sinkcat='X')
    - AQU -> CH  (aqu)  one aquifer per subbasin
    - HRU -> AQU (aqu)

Phase 2:
    - reservoir / pond routing (RES/PND as sinks on a channel; exit as a source)
    - tile drainage (til)
    - point sources (PT -> CH)
"""

from __future__ import annotations

from pathlib import Path

import networkx as nx
from pydantic import BaseModel

from ..types import HydType, ObjectCat


class RoutingEdge(BaseModel):
    """One row of ``gis_routing``."""

    sourceid: int
    sourcecat: ObjectCat
    hyd_typ: HydType
    sinkid: int
    sinkcat: ObjectCat
    percent: float = 1.0


def build_routing(
    channel_graph: nx.DiGraph,
    subbasin_ids: list[int],
    lsu_ids: list[int],
    hru_ids: list[int],
    hru_to_lsu: dict[int, int],
    lsu_to_channel: dict[int, int],
    *,
    include_aquifer: bool = True,
) -> list[RoutingEdge]:
    """Assemble the complete ``gis_routing`` edge list.

    Args:
        channel_graph:  DiGraph with channel ids as nodes; edges go downstream.
                        The unique sink (0-indegree node at the outlet) marks basin exit.
        subbasin_ids:   Sorted list of subbasin ids (== channel ids, one per subbasin).
        lsu_ids:        Sorted list of LSU ids.
        hru_ids:        Sorted list of HRU ids.
        hru_to_lsu:     {hru_id: lsu_id}.
        lsu_to_channel: {lsu_id: channel_id}.
        include_aquifer: If True, emit one aquifer per subbasin and the AQU <-> HRU/CH edges.

    Returns:
        List of :class:`RoutingEdge`. Caller persists via :mod:`db.writer`.

    Raises:
        SwatBuilderPipelineError: routing graph has a cycle or multiple sinks.
    """
    raise NotImplementedError("topology.build_routing is not yet implemented.")


def validate_dag(edges: list[RoutingEdge]) -> None:
    """Assert the routing graph is a DAG with exactly one ``sinkcat='X'``."""
    raise NotImplementedError("topology.validate_dag is not yet implemented.")


def save_graphml(graph: nx.DiGraph, output_path: Path | str) -> Path:
    """Persist the channel DiGraph alongside other watershed artifacts."""
    path = Path(output_path)
    nx.write_graphml(graph, path)
    return path
