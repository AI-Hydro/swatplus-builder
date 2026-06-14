"""Pure-Python GIS stage. Replaces QSWATPlus's QGIS-dependent modules.

Modules
-------
delineation  — DEM → subbasins/channels/outlets/routing via WhiteboxTools.
landuse      — default NLCD → SWAT+ plant code mapping (+ resolver helper).
soil         — soil raster + SSURGO/gNATSGO tables → SWAT+ soil definitions.
hru          — LU×Soil×Slope overlay → HRUs (dominant or percent-filtered).
tables       — WatershedResult + HRUResult → typed :class:`GisTables` (incl. routing rows).
validate     — post-delineation quality check (area, IoU, centroid vs reference).
"""

from .landuse import NLCD_TO_SWATPLUS, resolve_landuse

__all__ = ["NLCD_TO_SWATPLUS", "resolve_landuse"]
