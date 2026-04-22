from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from swatplus_builder.config import DEFAULT_SETTINGS, Settings
from swatplus_builder.errors import (
    SwatBuilderExternalError,
    SwatBuilderInputError,
    SwatBuilderPipelineError,
)
from swatplus_builder.soil.models import SoilProfile
from swatplus_builder.soil.params import collapse_dual_hyd_group, horizon_from_chorizon

log = logging.getLogger(__name__)

DEFAULT_PC_STAC_URL: str = "https://planetarycomputer.microsoft.com/api/stac/v1"

_MUAGGATT_COLS: tuple[str, ...] = ("mukey", "hydgrpdcd")
_MUAGGATT_OPTIONAL_COLS: tuple[str, ...] = (
    "aws025wta", "aws050wta", "aws0100wta", "aws0150wta",
    "brockdepmin", "wtdepannmin",
)

_AGG_LAYER_BREAKS_MM: tuple[float, ...] = (300.0, 1000.0, 1500.0)
_AGG_MIN_LAYERS: int = 2

@dataclass(frozen=True)
class GnatsgoFetchOptions:
    """Tunable knobs for Planetary Computer fetching."""
    stac_url: str = DEFAULT_PC_STAC_URL
    tables_collection: str = "gnatsgo-tables"
    cache_dir: Path | None = None

def _resolve_cache_dir(cache_dir: Path | None, settings: Settings) -> Path:
    if cache_dir is not None:
        return Path(cache_dir).expanduser().resolve()
    root = Path(settings.reference_db_dir).expanduser().resolve().parent
    return root / "gnatsgo_cache"

def _is_nan(x: Any) -> bool:
    try:
        import pandas as pd
        return bool(pd.isna(x))
    except Exception:
        try:
            v = (x != x)
            return bool(v) if isinstance(v, bool) else True
        except Exception:
            return False

def _num(value: Any, *, default: float | None) -> float | None:
    if value is None or _is_nan(value):
        return default
    try:
        return float(value)
    except Exception:
        return default

def _ksat_mmph_for_hydgrp(hydgrp: str) -> float:
    return {"A": 50.0, "B": 20.0, "C": 8.0, "D": 2.0}.get(hydgrp.upper(), 2.0)

def fetch_aggregated_profiles(
    mukeys: Iterable[int], 
    options: GnatsgoFetchOptions | None = None,
    settings: Settings = DEFAULT_SETTINGS
) -> dict[int, SoilProfile]:
    """Tier 1: Guaranteed synthetic profiles using PC muaggatt defaults."""
    
    mukey_set = {int(m) for m in mukeys if isinstance(m, int) and m >= 0}
    if not mukey_set:
        return {}

    opts = options or GnatsgoFetchOptions()
    cache_dir = _resolve_cache_dir(opts.cache_dir, settings)
    
    # Fast path: try loading muaggatt
    try:
        import pystac_client # type: ignore
        import planetary_computer # type: ignore
        import pandas as pd # type: ignore

        catalog = pystac_client.Client.open(
            opts.stac_url, modifier=planetary_computer.sign_inplace
        )
        search = catalog.search(collections=[opts.tables_collection])
        items = {item.id: item for item in search.items()}
        
        if "muaggatt" not in items:
            raise SwatBuilderPipelineError("Missing muaggatt in STAC.")

        signed_item = planetary_computer.sign(items["muaggatt"])
        asset = signed_item.assets["data"]
        href = asset.href
        storage_options = asset.extra_fields.get("table:storage_options", {})
        
        cols = list(_MUAGGATT_COLS + _MUAGGATT_OPTIONAL_COLS)
        df = pd.read_parquet(href, columns=cols, storage_options=storage_options)
        
        # filter
        mask = df["mukey"].isin(mukey_set)
        if not bool(mask.any()) and len(df) > 0:
            coerced = pd.to_numeric(df["mukey"], errors="coerce")
            mask = coerced.isin(mukey_set)
        df_mu = df.loc[mask]
        
        # cache mechanism best-effort
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            df_mu.to_parquet(cache_dir / "pc_muaggatt.parquet")
        except Exception:
            pass
            
    except Exception as exc:
        log.warning(f"Planetary Computer fetch failed, falling back to local pure-synthetic: {exc}")
        import pandas as pd
        df_mu = pd.DataFrame(columns=list(_MUAGGATT_COLS + _MUAGGATT_OPTIONAL_COLS))

    profiles = {}
    for mukey in sorted(mukey_set):
        match = df_mu[df_mu["mukey"].astype("int64") == mukey]
        row = match.iloc[0] if not match.empty else None
        
        hydgrp = collapse_dual_hyd_group(str(row.get("hydgrpdcd")) if row is not None and row.get("hydgrpdcd") is not None else None) if row is not None else "D"
        
        dp_tot_cm = _num(row.get("brockdepmin"), default=150.0) if row is not None else 150.0
        dp_tot_cm = max(30.0, min(250.0, dp_tot_cm))
        dp_tot_mm = dp_tot_cm * 10.0
        
        breaks_mm: list[float] = []
        for b in _AGG_LAYER_BREAKS_MM:
            if b < dp_tot_mm:
                breaks_mm.append(float(b))
        breaks_mm.append(float(dp_tot_mm))
        if len(breaks_mm) < _AGG_MIN_LAYERS:
            first = min(_AGG_LAYER_BREAKS_MM[0], dp_tot_mm)
            breaks_mm = [float(first), float(dp_tot_mm)]
            
        aws_25 = _num(row.get("aws025wta"), default=None) if row is not None else None
        aws_50 = _num(row.get("aws050wta"), default=None) if row is not None else None
        aws_100 = _num(row.get("aws0100wta"), default=None) if row is not None else None
        aws_150 = _num(row.get("aws0150wta"), default=None) if row is not None else None
        
        def cum_aws(depth_cm: float) -> float | None:
            if depth_cm <= 25 and aws_25 is not None: return aws_25
            if depth_cm <= 50 and aws_50 is not None: return aws_50
            if depth_cm <= 100 and aws_100 is not None: return aws_100
            if depth_cm <= 150 and aws_150 is not None: return aws_150
            return None

        def awc_for_segment(top_cm: float, bot_cm: float) -> float:
            thickness_cm = max(1e-6, bot_cm - top_cm)
            c_top = cum_aws(top_cm) or 0.0
            c_bot = cum_aws(bot_cm)
            if c_bot is None:
                for depth, val in ((150.0, aws_150), (100.0, aws_100), (50.0, aws_50), (25.0, aws_25)):
                    if val is not None:
                        c_bot = float(val) * (bot_cm / depth)
                        break
            if c_bot is None:
                return 0.15 
            seg_cm_water = max(0.0, float(c_bot) - float(c_top))
            awc = seg_cm_water / thickness_cm
            return max(0.01, min(0.35, awc))
            
        ksat_umps = _ksat_mmph_for_hydgrp(hydgrp) / 3.6
        layers = []
        top_cm = 0.0
        for layer_num, bot_mm in enumerate(breaks_mm, start=1):
            bot_cm = bot_mm / 10.0
            awc = awc_for_segment(top_cm, bot_cm)
            wthird = 30.0
            wfifteen = max(0.0, wthird - awc * 100.0)
            
            layers.append(horizon_from_chorizon(
                layer_num=layer_num, hzdepb_cm=bot_cm,
                sandtotal_r=40.0, silttotal_r=40.0, claytotal_r=20.0,
                ksat_umps=ksat_umps, dbthirdbar=1.4,
                wthirdbar_pct=wthird, wfifteenbar_pct=wfifteen, om_r=1.0
            ))
            top_cm = bot_cm
            
        source_label = "pc_muaggatt" if row is not None else "synthetic_default"
        
        profiles[mukey] = SoilProfile(
            name=f"gnatsgo_{mukey}", 
            hyd_grp=hydgrp, 
            texture=None,
            description=f"{source_label} dp_tot_cm={dp_tot_cm:.0f}",
            source=source_label,
            layers=layers
        )
        
    return profiles
