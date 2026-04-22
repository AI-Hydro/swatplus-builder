"""WGN (Weather Generator) nearest-station lookup from ``swatplus_wgn.sqlite``.

SWAT+ uses WGN stations to fill missing observed data and to produce stochastic
weather. The ``import_weather --import_type=wgn`` action in
:mod:`swatplus_builder.editor.api` needs a WGN db + table name, not a station list;
this module exists for custom pre-filters and validation.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel


class WgnStation(BaseModel):
    id: int
    name: str
    lat: float
    lon: float
    elev: float


def nearest_station(
    wgn_db: Path | str,
    lat: float,
    lon: float,
    *,
    table: str = "wgn_cfsr_world",
) -> WgnStation:
    """Return the nearest WGN station to ``(lat, lon)``."""
    # TODO(phase1): haversine-sorted sqlite query.
    raise NotImplementedError("wgn.nearest_station is a Phase 1 deliverable.")
