"""Terrain-topography and climate-lapse default disclosure for evidence bundles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_terrain_climate_defaults_block(run_dir: Path | str) -> dict[str, Any]:
    """Inspect topography and lapse settings from retained SWAT+ artifacts.

    This is a disclosure artifact, not a correction. It makes editor/default
    assumptions visible to claim governance and reviewers.
    """

    run = Path(run_dir)
    txt = _find_txtinout(run)
    block: dict[str, Any] = {
        "status": "not_evaluated",
        "txtinout_dir": str(txt) if txt is not None else None,
    }
    if txt is None:
        block.update({"status": "missing_artifacts", "reason": "TxtInOut directory missing"})
        return block

    topography = _topography_summary(txt / "topography.hyd")
    lapse = _lapse_summary(txt / "codes.bsn", txt / "parameters.bsn")
    dem = _dem_relief_summary(run / "delin" / "rasters" / "dem_conditioned.tif")
    metadata = _read_json(run / "metadata.json")
    weather_flags = metadata.get("weather_coverage_flags") if isinstance(metadata, dict) else {}
    if not isinstance(weather_flags, dict):
        weather_flags = {}

    flags: list[str] = []
    if topography.get("constant_slp_len"):
        flags.append("constant_slp_len")
    if topography.get("constant_lat_len"):
        flags.append("constant_lat_len")
    if topography.get("constant_dist_cha"):
        flags.append("constant_dist_cha")
    if lapse.get("lapse_enabled") is False:
        flags.append("lapse_disabled")
    if dem.get("relief_m") is not None and lapse.get("lapse_enabled") is False:
        try:
            if float(dem["relief_m"]) >= 300.0:
                flags.append("lapse_disabled_with_substantial_relief")
        except Exception:
            pass

    block.update(
        {
            "status": "evaluated",
            "topography_hyd": topography,
            "climate_lapse": lapse,
            "dem_relief": dem,
            "weather_station_context": {
                "n_weather_stations": weather_flags.get("n_weather_stations"),
                "station_selection": weather_flags.get("station_selection"),
                "weather_variables": weather_flags.get("weather_variables"),
            },
            "diagnostic_flags": flags,
            "claim_impact": _claim_impact(flags),
        }
    )
    return block


def _find_txtinout(run: Path) -> Path | None:
    for candidate in (
        run / "project" / "Scenarios" / "Default" / "TxtInOut",
        run / "Scenarios" / "Default" / "TxtInOut",
        run / "TxtInOut",
    ):
        if candidate.is_dir():
            return candidate
    return None


def _topography_summary(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"available": False, "path": str(path), "reason": "topography.hyd missing"}
    rows = _read_table(path, required=("name", "slp", "slp_len", "lat_len", "dist_cha"))
    if not rows:
        return {"available": False, "path": str(path), "reason": "no readable topography rows"}
    slp = [_as_float(row.get("slp")) for row in rows]
    slp_len = [_as_float(row.get("slp_len")) for row in rows]
    lat_len = [_as_float(row.get("lat_len")) for row in rows]
    dist_cha = [_as_float(row.get("dist_cha")) for row in rows]
    return {
        "available": True,
        "path": str(path),
        "row_count": len(rows),
        "slope_min": _min(slp),
        "slope_mean": _mean(slp),
        "slope_max": _max(slp),
        "slp_len_unique": _unique_numbers(slp_len),
        "lat_len_unique": _unique_numbers(lat_len),
        "dist_cha_unique": _unique_numbers(dist_cha),
        "constant_slp_len": len(_unique_numbers(slp_len)) == 1,
        "constant_lat_len": len(_unique_numbers(lat_len)) == 1,
        "constant_dist_cha": len(_unique_numbers(dist_cha)) == 1,
        "interpretation": "Topographic lengths are retained as written by SWAT+ Editor; no terrain-derived correction is implied.",
    }


def _lapse_summary(codes_path: Path, params_path: Path) -> dict[str, Any]:
    codes = _read_single_row(codes_path)
    params = _read_single_row(params_path)
    lapse = _as_float(codes.get("lapse"))
    plaps = _as_float(params.get("plaps"))
    tlaps = _as_float(params.get("tlaps"))
    lapse_enabled = None
    if lapse is not None:
        lapse_enabled = int(round(lapse)) != 0
    return {
        "available": bool(codes or params),
        "codes_bsn_path": str(codes_path),
        "parameters_bsn_path": str(params_path),
        "lapse": lapse,
        "plaps": plaps,
        "tlaps": tlaps,
        "lapse_enabled": lapse_enabled,
        "interpretation": "Climate lapse settings are disclosed as written; no lapse correction is inferred from weather-station count.",
    }


def _dem_relief_summary(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"available": False, "path": str(path), "reason": "conditioned DEM missing"}
    try:
        import numpy as np
        import rasterio

        with rasterio.open(path) as src:
            data = src.read(1).astype("float64")
            mask = np.isfinite(data)
            if src.nodata is not None:
                mask &= data != src.nodata
            vals = data[mask]
            if vals.size == 0:
                return {"available": False, "path": str(path), "reason": "no valid DEM cells"}
            mn = float(vals.min())
            mx = float(vals.max())
    except Exception as exc:
        return {"available": False, "path": str(path), "reason": str(exc)}
    return {
        "available": True,
        "path": str(path),
        "elevation_min_m": mn,
        "elevation_max_m": mx,
        "relief_m": mx - mn,
    }


def _read_table(path: Path, *, required: tuple[str, ...]) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    header_idx = next((i for i, line in enumerate(lines) if set(required).issubset(set(line.split()))), None)
    if header_idx is None:
        return []
    columns = lines[header_idx].split()
    rows: list[dict[str, str]] = []
    for line in lines[header_idx + 1 :]:
        tokens = line.split()
        if len(tokens) < len(required):
            continue
        row = {col: tokens[idx] for idx, col in enumerate(columns[: len(tokens)])}
        if all(key in row for key in required):
            rows.append(row)
    return rows


def _read_single_row(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    if len(lines) < 3:
        return {}
    columns = lines[1].split()
    values = lines[2].split()
    return {col: values[idx] for idx, col in enumerate(columns[: len(values)])}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _as_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _unique_numbers(values: list[float | None]) -> list[float]:
    return sorted({round(v, 6) for v in values if v is not None})


def _mean(values: list[float | None]) -> float | None:
    nums = [v for v in values if v is not None]
    return sum(nums) / len(nums) if nums else None


def _min(values: list[float | None]) -> float | None:
    nums = [v for v in values if v is not None]
    return min(nums) if nums else None


def _max(values: list[float | None]) -> float | None:
    nums = [v for v in values if v is not None]
    return max(nums) if nums else None


def _claim_impact(flags: list[str]) -> str:
    if not flags:
        return "terrain_climate_defaults_disclosed_no_default_flags"
    if "lapse_disabled_with_substantial_relief" in flags:
        return "diagnostic_only_until_terrain_lengths_and_lapse_defaults_are_audited"
    return "diagnostic_context_disclosed"
