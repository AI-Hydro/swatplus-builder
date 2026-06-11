"""Basin boundary acquisition with explicit provenance.

The full fallback cascade is intentionally conservative in package code: use
authoritative NLDI basins when available, and fail with a typed provenance note
when no implemented fallback can supply a boundary.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


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


def _fetch_nldi_boundary(usgs_id: str):
    from pynhd import NLDI

    return NLDI().get_basins(usgs_id).to_crs("EPSG:4326")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
