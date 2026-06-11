"""Optional SoilGrids v2.0 coarse-profile fallback.

This module exists so the package-owned full-mode builder can classify coarse
soil fallback availability explicitly instead of failing with an import error.
Live SoilGrids calls are opt-in via ``SWATPLUS_ENABLE_SOILGRIDS_LIVE=1`` because
the endpoint is an external provider and the resulting profile is lower
authority than gNATSGO/SDA evidence.
"""

from __future__ import annotations

import logging
import os

import requests

from swatplus_builder.soil.models import SoilProfile
from swatplus_builder.soil.params import horizon_from_chorizon

log = logging.getLogger(__name__)

SOILGRIDS_URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"


def fetch_soilgrids_profile(lon: float, lat: float, *, mukey: int) -> SoilProfile | None:
    """Fetch one coarse SoilGrids-derived profile for ``lon``/``lat``.

    Returns ``None`` when live SoilGrids access is disabled or unavailable.  The
    caller must treat any profile returned here as degraded-provenance fallback,
    not as high-fidelity research-grade soil evidence.
    """
    if os.environ.get("SWATPLUS_ENABLE_SOILGRIDS_LIVE") != "1":
        log.info("SoilGrids live fallback disabled; set SWATPLUS_ENABLE_SOILGRIDS_LIVE=1 to enable.")
        return None

    try:
        payload = _query_soilgrids(lon, lat)
        values = _extract_means(payload)
    except Exception as exc:
        log.warning("SoilGrids query failed for mukey=%s: %s", mukey, exc)
        return None

    if not values:
        return None

    horizon = horizon_from_chorizon(
        layer_num=1,
        hzdepb_cm=200.0,
        sandtotal_r=values.get("sand", 33.3),
        silttotal_r=values.get("silt", 33.3),
        claytotal_r=values.get("clay", 33.4),
        ksat_umps=10.0,
        dbthirdbar=values.get("bdod", 140.0) / 100.0,
        wthirdbar_pct=values.get("wv0033", 300.0) / 10.0,
        wfifteenbar_pct=values.get("wv1500", 150.0) / 10.0,
        om_r=max(values.get("soc", 10.0) / 10.0 * 1.724, 0.1),
    )
    return SoilProfile(
        name=f"gnatsgo_{int(mukey)}",
        hyd_grp=_hyd_group_from_texture(values.get("clay", 33.4), values.get("sand", 33.3)),
        texture="soilgrids_coarse",
        description=f"SoilGrids v2.0 coarse fallback profile for mukey={int(mukey)}",
        source="soilgrids_v2_coarse",
        layers=[horizon],
    )


def _query_soilgrids(lon: float, lat: float) -> dict:
    params: list[tuple[str, str | float]] = [
        ("lon", float(lon)),
        ("lat", float(lat)),
        ("value", "mean"),
    ]
    for prop in ("clay", "sand", "silt", "bdod", "soc", "wv0033", "wv1500"):
        params.append(("property", prop))
    for depth in ("0-5cm", "5-15cm", "15-30cm", "30-60cm", "60-100cm", "100-200cm"):
        params.append(("depth", depth))
    resp = requests.get(SOILGRIDS_URL, params=params, timeout=30.0)
    resp.raise_for_status()
    payload = resp.json()
    return payload if isinstance(payload, dict) else {}


def _extract_means(payload: dict) -> dict[str, float]:
    layers = (
        payload.get("properties", {})
        .get("layers", [])
    )
    means: dict[str, float] = {}
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        name = str(layer.get("name") or "")
        depths = layer.get("depths") if isinstance(layer.get("depths"), list) else []
        vals = []
        for depth in depths:
            if not isinstance(depth, dict):
                continue
            mean = depth.get("values", {}).get("mean") if isinstance(depth.get("values"), dict) else None
            if isinstance(mean, (int, float)):
                vals.append(float(mean))
        if vals:
            means[name] = sum(vals) / len(vals)
    return means


def _hyd_group_from_texture(clay_pct: float, sand_pct: float) -> str:
    if clay_pct >= 40.0:
        return "D"
    if clay_pct >= 30.0:
        return "C"
    if sand_pct >= 70.0 and clay_pct < 15.0:
        return "A"
    return "B"
