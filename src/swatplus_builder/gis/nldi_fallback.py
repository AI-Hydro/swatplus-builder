"""Basin boundary acquisition and NHD flowline fetch with explicit provenance.

The full fallback cascade is intentionally conservative in package code: use
authoritative NLDI basins when available, and fail with a typed provenance note
when no implemented fallback can supply a boundary.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BoundaryProvenance:
    usgs_id: str
    source: str
    tier: int
    generated_at: str
    notes: list[str] = field(default_factory=list)
    fallback_attempts: list[dict[str, str]] = field(default_factory=list)

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


def fetch_basin_boundary_cascade(usgs_id: str, *, dem_path: Path | None = None):
    """Fetch a basin boundary and return ``(GeoDataFrame, provenance)``.

    Tier 1 is USGS NLDI. Later fallback tiers are represented in provenance but
    are not silently simulated; if NLDI fails, callers receive a clear package
    error instead of a fabricated watershed polygon.
    """
    attempts: list[dict[str, str]] = []
    try:
        basin = _fetch_nldi_boundary(usgs_id)
        if basin.empty:
            raise RuntimeError("NLDI returned an empty basin GeoDataFrame")
        provenance = BoundaryProvenance(
            usgs_id=usgs_id,
            source="nldi_authoritative",
            tier=1,
            generated_at=_utc_now(),
            notes=["USGS NLDI basin polygon returned successfully"],
            fallback_attempts=attempts,
        )
        return basin, provenance
    except Exception as exc:
        attempts.append({"source": "nldi_authoritative", "status": "failed", "message": str(exc)})

    notes = [
        "NLDI basin boundary acquisition failed.",
        "Additional WBD/StreamStats/NHDPlus/DEM fallback tiers are not yet implemented in package code.",
    ]
    if dem_path is not None:
        notes.append(f"DEM fallback requested with dem_path={Path(dem_path)} but is not implemented.")
    raise RuntimeError(
        "basin_boundary_unavailable: "
        + "; ".join(f"{a['source']}={a['message']}" for a in attempts)
    )


def fetch_nhd_flowlines(usgs_id: str, out_gpkg: Path) -> Path | None:
    """Fetch NHD upstream flowlines for a USGS gauge via NLDI.

    Returns path to saved GPKG, or None when NLDI fails or returns empty.
    Used as a stream-burn vector input to correct D8 flow direction on flat
    terrain before WhiteboxTools delineation.
    """
    try:
        from pynhd import NLDI
        flowlines = NLDI().navigate_byid(
            "nwissite",
            f"USGS-{usgs_id}",
            "upstreamTributaries",
            "nhdflowline_network",
            distance=9999,
        )
        if flowlines is None or flowlines.empty:
            log.warning("NLDI returned no NHD flowlines for %s.", usgs_id)
            return None
        out_gpkg.parent.mkdir(parents=True, exist_ok=True)
        flowlines.to_file(out_gpkg, driver="GPKG")
        log.info("NHD flowlines: %d features saved to %s", len(flowlines), out_gpkg.name)
        return out_gpkg
    except Exception as exc:
        log.warning("NHD flowlines fetch failed for %s: %s", usgs_id, exc)
        return None


def _fetch_nldi_boundary(usgs_id: str):
    from pynhd import NLDI

    return NLDI().get_basins(usgs_id).to_crs("EPSG:4326")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
