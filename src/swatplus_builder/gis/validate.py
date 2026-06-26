"""Post-delineation validation: compare against a reference watershed.

Why validate early?
    Numbers mean nothing until you have a reference. A 10 % area error found now
    costs you 5 minutes. Found after a full SWAT+ run it costs you a day.

Reference sources (in priority order):
    1. User-supplied polygon — shapefile, GeoPackage, or any fiona-readable vector.
    2. USGS NLDI basin — fetched by gauge ID (requires network + pynhd).
    3. None — metrics are computed against the delineated area only (self-check).

Metrics
-------
- ``delineated_area_km2``  — total area of all delineated subbasins
- ``reference_area_km2``   — area of the reference polygon (if available)
- ``area_diff_pct``        — (delineated − reference) / reference × 100
- ``iou_pct``              — intersection / union × 100  (Jaccard index)
- ``centroid_distance_km`` — distance between centroids
- ``passed``               — area error and spatial overlap both meet thresholds

Usage
-----
::

    from swatplus_builder.gis.validate import validate_watershed

    result = validate_watershed(
        ws,
        usgs_id="01547700",       # fetch NLDI reference automatically
        area_tolerance_pct=10.0,
    )
    result.print_report()

    # or supply your own reference polygon
    result = validate_watershed(ws, reference_polygon="my_basin.gpkg")
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

import geopandas as gpd
from pydantic import BaseModel, Field
from shapely.ops import unary_union

from ..types import WatershedResult

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class ValidationResult(BaseModel):
    """Quantitative comparison of the delineated watershed against a reference."""

    delineated_area_km2: float = Field(..., description="Total area of all delineated subbasins.")
    n_subbasins: int

    reference_area_km2: float | None = Field(None, description="Area of the reference polygon.")
    reference_source: str = Field("none", description="'user_polygon', 'usgs_nldi', or 'none'.")

    area_diff_pct: float | None = Field(
        None,
        description="(delineated − reference) / reference × 100. Positive = over-delineated.",
    )
    iou_pct: float | None = Field(None, description="Intersection / union × 100 (Jaccard index).")
    centroid_distance_km: float | None = Field(
        None, description="Great-circle distance between centroids (km)."
    )

    passed: bool = Field(False, description="True if abs(area_diff_pct) < area_tolerance_pct.")
    area_tolerance_pct: float = 10.0
    min_iou_pct: float = 70.0
    notes: list[str] = Field(default_factory=list)

    def print_report(self) -> None:
        """Print a compact, human-readable comparison table."""
        status = "✅ PASS" if self.passed else "❌ FAIL"
        sep = "─" * 52
        print(f"\n{sep}")
        print(f"  swatplus-builder · Watershed Validation  {status}")
        print(sep)
        print(f"  Delineated area   : {self.delineated_area_km2:>10.2f} km²")
        print(f"  Subbasins         : {self.n_subbasins:>10d}")
        if self.reference_area_km2 is not None:
            print(f"  Reference area    : {self.reference_area_km2:>10.2f} km²  [{self.reference_source}]")
            diff = self.area_diff_pct or 0.0
            sign = "+" if diff > 0 else ""
            print(f"  Area difference   : {sign}{diff:>9.1f} %   (tolerance ±{self.area_tolerance_pct:.0f} %)")
        if self.iou_pct is not None:
            print(
                f"  IoU (Jaccard)     : {self.iou_pct:>10.1f} %"
                f"   (minimum {self.min_iou_pct:.0f} %)"
            )
        if self.centroid_distance_km is not None:
            print(f"  Centroid distance : {self.centroid_distance_km:>10.2f} km")
        if self.notes:
            print("\n  Notes:")
            for note in self.notes:
                print(f"    • {note}")
        print(sep)

    def to_dict(self) -> dict:
        return self.model_dump()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def validate_watershed(
    result: WatershedResult,
    *,
    reference_polygon: Path | str | None = None,
    usgs_id: str | None = None,
    area_tolerance_pct: float = 10.0,
    min_iou_pct: float = 70.0,
) -> ValidationResult:
    """Compare a delineated watershed against a reference.

    Args:
        result:               Output of :func:`~swatplus_builder.gis.delineation.delineate`.
        reference_polygon:    Path to a shapefile/GeoPackage with the reference boundary.
                              The first feature is used. If supplied, ``usgs_id`` is ignored.
        usgs_id:              USGS gauge ID. Fetches the NHDPlus basin from the NLDI API.
                              Requires network access and ``pynhd`` (``[hyriver]`` extra).
        area_tolerance_pct:   Pass/fail threshold for |area_diff_pct|. Default 10 %.
        min_iou_pct:           Minimum intersection-over-union with the reference. Default 70 %.

    Returns:
        :class:`ValidationResult` — all metrics plus a ``passed`` flag and a printable report.
    """
    notes: list[str] = []

    # ------------------------------------------------------------------
    # 1. Load delineated boundary
    # ------------------------------------------------------------------
    delineated_gdf = gpd.read_file(result.subbasins_vector)
    delineated_union = unary_union(delineated_gdf.geometry.values)

    # Work in a projected CRS for accurate area in km²
    proj_crs = result.crs
    delineated_gdf = delineated_gdf.to_crs(proj_crs)
    delineated_union = unary_union(delineated_gdf.geometry.values)
    delineated_area_km2 = round(delineated_union.area / 1e6, 3)
    n_subbasins = len(delineated_gdf)

    # ------------------------------------------------------------------
    # 2. Load reference
    # ------------------------------------------------------------------
    ref_polygon = None
    ref_source = "none"

    if reference_polygon is not None:
        ref_source = "user_polygon"
        ref_gdf = gpd.read_file(str(reference_polygon)).to_crs(proj_crs)
        ref_polygon = unary_union(ref_gdf.geometry.values)
        log.info("Validation: using user-supplied reference polygon.")

    elif usgs_id is not None:
        ref_polygon, ref_source = _fetch_nldi_basin(usgs_id, proj_crs, notes)

    # ------------------------------------------------------------------
    # 3. Compute metrics
    # ------------------------------------------------------------------
    ref_area_km2: float | None = None
    area_diff_pct: float | None = None
    iou_pct: float | None = None
    centroid_dist_km: float | None = None
    passed = False

    if ref_polygon is not None and not ref_polygon.is_empty:
        ref_area_km2 = round(ref_polygon.area / 1e6, 3)

        area_diff_pct = round(
            (delineated_area_km2 - ref_area_km2) / ref_area_km2 * 100, 2
        )

        intersection = delineated_union.intersection(ref_polygon).area
        union = delineated_union.union(ref_polygon).area
        iou_pct = round(intersection / union * 100, 2) if union > 0 else 0.0

        # Centroid distance (great-circle via lon/lat)
        d_centroid = delineated_union.centroid
        r_centroid = ref_polygon.centroid
        centroid_dist_km = round(
            _haversine_km(d_centroid.x, d_centroid.y, r_centroid.x, r_centroid.y,
                          proj_crs=proj_crs),
            2,
        )

        passed = (
            abs(area_diff_pct) <= area_tolerance_pct
            and iou_pct >= min_iou_pct
        )

        # Qualitative notes
        if abs(area_diff_pct) > 20:
            notes.append(
                f"Area difference is large ({area_diff_pct:+.1f} %). "
                "Try adjusting stream_threshold_cells or snap_dist_m."
            )
        if iou_pct < 70:
            notes.append(
                f"Low spatial overlap (IoU={iou_pct:.1f} %). "
                "The delineated boundary may not match the reference — check outlet placement."
            )
        if centroid_dist_km > 5:
            notes.append(
                f"Centroid offset is {centroid_dist_km:.1f} km — potential outlet mismatch."
            )
    else:
        notes.append("No reference polygon available — area self-check only.")
        passed = True  # nothing to fail against

    if delineated_area_km2 < 0.5:
        notes.append("Delineated area < 0.5 km² — check outlet snapping and threshold.")

    vr = ValidationResult(
        delineated_area_km2=delineated_area_km2,
        n_subbasins=n_subbasins,
        reference_area_km2=ref_area_km2,
        reference_source=ref_source,
        area_diff_pct=area_diff_pct,
        iou_pct=iou_pct,
        centroid_distance_km=centroid_dist_km,
        passed=passed,
        area_tolerance_pct=area_tolerance_pct,
        min_iou_pct=min_iou_pct,
        notes=notes,
    )
    return vr


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _fetch_nldi_basin(
    usgs_id: str, proj_crs: str, notes: list[str]
) -> tuple[object | None, str]:
    """Fetch the NHDPlus basin polygon from the NLDI API."""
    try:
        from pynhd import NLDI  # type: ignore[import]
    except ImportError:
        notes.append(
            "pynhd not installed — skipping USGS NLDI validation. "
            "Install with: pip install 'swatplus-builder[hyriver]'"
        )
        return None, "none"

    try:
        log.info("Validation: fetching NLDI basin for gauge %s …", usgs_id)
        nldi = NLDI()
        basins = nldi.get_basins(usgs_id)
        if basins.empty:
            notes.append(f"NLDI returned no basin for gauge {usgs_id}.")
            return None, "none"
        basin_gdf = basins.to_crs(proj_crs)
        ref_polygon = unary_union(basin_gdf.geometry.values)
        log.info("Validation: NLDI basin loaded (%.1f km²).", ref_polygon.area / 1e6)
        return ref_polygon, "usgs_nldi"
    except Exception as exc:  # network errors, NLDI outages
        notes.append(f"NLDI fetch failed ({exc}). Skipping reference comparison.")
        log.warning("NLDI fetch failed: %s", exc)
        return None, "none"


def _haversine_km(
    x1: float, y1: float, x2: float, y2: float, *, proj_crs: str
) -> float:
    """Compute great-circle distance (km) between two points.

    Points are in ``proj_crs`` (projected metres); we back-transform to WGS84
    for the haversine formula.
    """
    try:
        from pyproj import Transformer
        transformer = Transformer.from_crs(proj_crs, "EPSG:4326", always_xy=True)
        lon1, lat1 = transformer.transform(x1, y1)
        lon2, lat2 = transformer.transform(x2, y2)
    except Exception:
        # Fallback: treat coordinates as approximate lon/lat
        lon1, lat1, lon2, lat2 = x1, y1, x2, y2

    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
