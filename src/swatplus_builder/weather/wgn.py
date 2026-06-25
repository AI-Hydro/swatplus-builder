"""WGN (Weather Generator) nearest-station lookup from ``swatplus_wgn.sqlite``.

SWAT+ uses WGN stations to fill missing observed data and to produce stochastic
weather. The ``import_weather --import_type=wgn`` action in
:mod:`swatplus_builder.editor.api` needs a WGN db + table name, not a station list;
this module exists for custom pre-filters and validation.
"""

from __future__ import annotations

from pydantic import BaseModel


class WgnStation(BaseModel):
    id: int
    name: str
    lat: float
    lon: float
    elev: float
