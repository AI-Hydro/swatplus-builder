"""Land-use / HRU representation evidence for claim governance."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np

from ..gis.landuse import NLCD_CLASS_DESCRIPTIONS, resolve_landuse

__all__ = ["build_landuse_fidelity_block", "find_nlcd_raster"]


def build_landuse_fidelity_block(
    run_dir: Path | str,
    *,
    sim_start: str | None = None,
    sim_end: str | None = None,
) -> dict[str, Any]:
    """Build the land-use fidelity disclosure block from run artifacts."""

    run = Path(run_dir)
    catalog_path = run / "delin" / "hrus" / "hru_catalog.json"
    nlcd_path = find_nlcd_raster(run)
    nlcd_selection = _read_nlcd_selection(run)
    block: dict[str, Any] = {
        "status": "not_evaluated",
        "hru_catalog_path": str(catalog_path),
        "landuse_raster_path": str(nlcd_path) if nlcd_path else None,
        "landuse_selection_path": str(run / "raw" / "nlcd_selection.json"),
        "landuse_selection": nlcd_selection,
        "sim_window": {"start": sim_start, "end": sim_end},
    }
    if not catalog_path.is_file():
        block.update({"status": "missing_artifacts", "reason": "hru_catalog.json missing"})
        return block

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    stats = catalog.get("stats") if isinstance(catalog, dict) else {}
    if not isinstance(stats, dict):
        stats = {}
    hrus = catalog.get("hrus") if isinstance(catalog, dict) else []
    if not isinstance(hrus, list):
        hrus = []

    dominant_only = bool(stats.get("dominant_only"))
    retained = sorted({str(h.get("landuse")) for h in hrus if isinstance(h, dict) and h.get("landuse")})

    present_codes: list[int] = []
    present_swat_codes: list[str] = []
    present_details: list[dict[str, Any]] = []
    if nlcd_path and nlcd_path.is_file():
        present_codes, present_swat_codes, present_details = _present_landuse_classes(nlcd_path)

    vintage_year = _infer_vintage_year(nlcd_path) if nlcd_path else None
    sim_midpoint = _sim_midpoint_year(sim_start, sim_end)
    mismatch = (
        int(vintage_year) - int(sim_midpoint)
        if vintage_year is not None and sim_midpoint is not None
        else None
    )
    retained_set = set(retained)
    present_set = set(present_swat_codes)
    missing = sorted(present_set - retained_set)
    retained_fraction = (
        len(retained_set & present_set) / len(present_set)
        if present_set
        else None
    )

    block.update(
        {
            "status": "evaluated",
            "hru_mode": "dominant_only" if dominant_only else "full_overlay",
            "dominant_only": dominant_only,
            "n_hrus": _as_int(stats.get("n_hrus"), len(hrus)),
            "n_lsus": _as_int(stats.get("n_lsus"), None),
            "n_subbasins": _as_int(stats.get("n_subbasins"), None),
            "hru_per_subbasin_ratio": _ratio(stats.get("n_hrus"), stats.get("n_subbasins")),
            "landuse_classes_present": present_swat_codes,
            "landuse_nlcd_classes_present": present_codes,
            "landuse_classes_present_count": len(present_swat_codes),
            "landuse_classes_retained": retained,
            "landuse_classes_retained_count": len(retained),
            "landuse_classes_missing_from_hrus": missing,
            "landuse_class_retention_fraction": retained_fraction,
            "landuse_present_details": present_details,
            "landuse_vintage_year": vintage_year,
            "sim_midpoint_year": sim_midpoint,
            "landuse_vintage_mismatch_years": mismatch,
        }
    )
    return block


def find_nlcd_raster(run_dir: Path | str) -> Path | None:
    """Return the authoritative NLCD raster for a run, if one is present."""

    run = Path(run_dir)
    selection = _read_nlcd_selection(run)
    if selection:
        selected_path = selection.get("raster_path")
        if isinstance(selected_path, str) and selected_path:
            candidate = Path(selected_path)
            if not candidate.is_absolute():
                candidate = run / candidate
            if candidate.is_file():
                return candidate
        selected_year = selection.get("selected_year")
        try:
            candidate = run / "raw" / f"nlcd_{int(selected_year)}.tif"
        except Exception:
            candidate = None
        if candidate is not None and candidate.is_file():
            return candidate

    candidates = sorted((run / "raw").glob("nlcd_*.tif"))
    if candidates:
        return candidates[0]
    fallback = run / "raw" / "nlcd_2021.tif"
    return fallback if fallback.is_file() else None


def _read_nlcd_selection(run: Path) -> dict[str, Any] | None:
    path = run / "raw" / "nlcd_selection.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _present_landuse_classes(path: Path) -> tuple[list[int], list[str], list[dict[str, Any]]]:
    import rasterio

    with rasterio.open(path) as src:
        arr = src.read(1)
        mask = np.isfinite(arr)
        if src.nodata is not None:
            mask &= arr != src.nodata
        vals, counts = np.unique(arr[mask].astype("int64"), return_counts=True)

    details: list[dict[str, Any]] = []
    swat_codes: set[str] = set()
    for code, count in zip(vals.tolist(), counts.tolist()):
        code_i = int(code)
        swat = resolve_landuse(code_i)
        swat_codes.add(swat)
        details.append(
            {
                "nlcd_code": code_i,
                "nlcd_class": NLCD_CLASS_DESCRIPTIONS.get(code_i, f"NLCD {code_i}"),
                "swatplus_landuse": swat,
                "pixel_count": int(count),
            }
        )
    return sorted(int(v) for v in vals.tolist()), sorted(swat_codes), details


def _infer_vintage_year(path: Path | None) -> int | None:
    if path is None:
        return None
    match = re.search(r"(19|20)\d{2}", path.name)
    if not match:
        return None
    return int(match.group(0))


def _sim_midpoint_year(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    try:
        y0 = int(str(start)[:4])
        y1 = int(str(end)[:4])
    except Exception:
        return None
    return int(round((y0 + y1) / 2.0))


def _as_int(value: Any, default: int | None) -> int | None:
    try:
        return int(value)
    except Exception:
        return default


def _ratio(numerator: Any, denominator: Any) -> float | None:
    try:
        den = float(denominator)
        if den == 0:
            return None
        return float(numerator) / den
    except Exception:
        return None
