"""Error hierarchy for swatplus-builder.

Three well-scoped classes. Every instance carries a ``.context`` dict with
debugging metadata so agents can introspect failures without string parsing.
"""

from __future__ import annotations

from typing import Any


class SwatBuilderError(Exception):
    """Base class. Never raised directly; catch subclasses."""

    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context)


class SwatBuilderInputError(SwatBuilderError):
    """Caller-supplied inputs are malformed or inconsistent.

    Examples:
        - outlet lon/lat outside the DEM extent
        - DEM and landuse rasters in incompatible CRS
        - ``sim_start`` after ``sim_end``
    """


class SwatBuilderPipelineError(SwatBuilderError):
    """An internal stage produced invalid output.

    Examples:
        - delineation returned zero subbasins
        - routing graph has a cycle
        - ``gis_*`` referential integrity check failed
    """


class SwatBuilderExternalError(SwatBuilderError):
    """An external tool (WhiteboxTools, SWAT+ engine, editor API subprocess)
    returned a non-zero status or could not be located.
    """
